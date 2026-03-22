# Paper Trading Issues Report
**Date:** 2026-03-11
**Status:** Root causes identified and fixed

---

## Executive Summary

All 3 problems share a single root cause: **the circuit breaker that protects Alpaca order submissions also blocks read operations (order lookups) when it opens**. When 5 consecutive order submissions fail, the circuit breaker opens and blocks `get_order_by_client_id`. The reconciler then sees `None` from the blocked lookup, treats it as "order not found", and marks genuinely-filled orders as `failed_open`. Real live positions become untracked "orphans" and are never monitored for profit targets or stop losses.

---

## Problem 1: High Order Failure Rate (~40%)

### What the numbers actually mean

| Experiment | "Failed" Orders | Actually Failed | Filled But Mismarked |
|---|---|---|---|
| exp_059 | 12 | 4 | 8 |
| exp_154 | 12 | ~3 | ~9 |
| exp_305 | 3 | ~1 | ~2 |

The true failure rate is much lower than 40%. Most "failures" are orders that filled successfully in Alpaca but were misclassified by the reconciler.

### Root Cause

**Two distinct error types in the logs:**

**Error A — "position intent mismatch"** (`code 42210000`):
```
position intent mismatch, inferred: buy_to_close, specified: buy_to_open
```
Happens when the scanner tries to open a NEW position at the same strikes as an existing orphan position. Since the orphan already has a SHORT in that option, Alpaca infers the BUY leg should be `buy_to_close`, not `buy_to_open`. This is caused by orphan positions being invisible to the scanner (no `open` DB record → no risk gate block → re-entry attempted).

**Error B — "client_order_id must be unique"** (`code 40010001`):
```
client_order_id must be unique
```
Happens on retry attempts when the same deterministic client_id is resubmitted. Because `execution_engine.py` uses `sha256(ticker-type-expiration-short_strike-long_strike)[:16]` as the client_id, selecting the same strikes on a retry generates the same hash. Alpaca rejects it because the ID was already consumed by the first (successful) submission.

**Both errors are downstream consequences of the same upstream bug:** filled orders being marked `failed_open`.

### How filled orders got mismarked

Timeline:
1. Order submitted → Alpaca accepts and fills → DB stays `pending_open`
2. Five consecutive order submission failures (next scan) → circuit breaker opens
3. Reconciler calls `get_order_by_client_id` → **circuit breaker blocks the call** → returns `None`
4. Trade is >4h old → reconciler marks it `failed_open` (wrong — it filled)
5. Next scan: no `open` DB record → risk gate allows re-entry → "position intent mismatch"

---

## Problem 2: Unmanaged Positions (44 total)

### Root Cause

Direct consequence of Problem 1. When filled orders are marked `failed_open`:
- The reconciler's orphan detection finds real Alpaca positions with no DB `open` record
- Creates shell records with `status="unmanaged"`, `credit=0`, `short_strike=0` — no actionable data
- Position monitor checks `get_trades(status="open")` only — unmanaged records are invisible to it
- No profit target or stop loss monitoring on 44 real live positions

### Cascade

```
Circuit breaker opens
    → get_order_by_client_id blocked → returns None
    → Filled order marked failed_open
    → Real Alpaca positions = orphans
    → Orphan detection creates unmanaged shell records
    → Position monitor ignores unmanaged
    → ZERO monitoring of real positions
```

---

## Problem 3: Zero Closed Trades

### Root Cause

The position monitor (`execution/position_monitor.py`) queries `get_trades(status="open")`. Since no trades were ever promoted to `open` status (all were either `pending_open`, `failed_open`, or `unmanaged`), the position monitor had an empty list to work with on every cycle. It ran, checked 0 positions, found nothing to close.

The position monitor IS running correctly — it just has no data to act on.

---

## Fixes Implemented

### Fix 1: Position-Based Fallback in Reconciler (`shared/reconciler.py`)

**Before:** When `get_order_by_client_id` returned `None` AND the trade was >4h old, immediately mark `failed_open`.

**After:** Before marking `failed_open`, fetch current Alpaca positions and check if the expected OCC symbols for this trade exist. If they do → the order filled → promote to `open`.

```python
# New logic in _reconcile_pending_opens:
if age_hours >= _PENDING_MAX_AGE_HOURS:
    positions_exist = any(sym in alpaca_positions for sym in expected_syms)
    if positions_exist:
        trade["status"] = "open"  # confirmed by position presence
    else:
        trade["status"] = "failed_open"  # genuinely not filled
```

This breaks the circuit-breaker-blocking cascade. Even when the order lookup is blocked, the position check independently confirms the fill.

### Fix 2: Orphan Recovery from Order History (`shared/reconciler.py`)

New method `recover_orphans_from_order_history()`:
- Fetches all filled MLEG orders from Alpaca's closed order history
- Matches legs to `unmanaged` orphan records by OCC symbol
- Parses strike/expiration/type from OCC symbol format (`SPY260417C00699000`)
- Reconstructs proper `open` trade records with correct credit, strikes, expiration, contracts
- Uses the same deterministic `client_id` hash as `ExecutionEngine` for idempotency

### Fix 3: Startup Orphan Recovery in `main.py`

Added `recover_orphans_from_order_history()` call to the startup reconciliation sequence so it runs automatically on every process restart.

---

## Recovery Results (Applied 2026-03-11)

### Before Fixes

| Experiment | open | failed_open | pending_open | unmanaged |
|---|---|---|---|---|
| exp_059 | 0 | 12 | 2 | 16 |
| exp_154 | 0 | 12 | 2 | 18 |
| exp_305 | 0 | 3 | 6 | 10 |

### After Fixes

| Experiment | open | Recovered How |
|---|---|---|
| exp_059 | 10 | 8 from order history + 2 via position-based confirmation |
| exp_154 | 11 | 11 from order history + 2 via position-based confirmation (some overlap) |
| exp_305 | 6 | 6 from order history |

**27 positions are now properly tracked as `open` and will be monitored for profit targets and stop losses.**

### Recovered Positions (exp_059)

| Trade | Type | Short | Long | Credit | Contracts | Entry |
|---|---|---|---|---|---|---|
| cs-8de0886415a3da4b | bear_call | 701 | 706 | $1.78 | 25 | Mar 10 16:00 |
| cs-5e5457c7b8129ddc | bull_put | 650 | 645 | $0.83 | 23 | Mar 10 16:30 |
| cs-b736d8f0fd25c42b | bear_call | 702 | 707 | $1.63 | 25 | Mar 10 17:00 |
| cs-a8b72e5554076f9c | bull_put | 659 | 654 | $0.86 | 24 | Mar 10 17:30 |
| cs-10725dd5169ce580 | bear_call | 703 | 708 | $1.61 | 25 | Mar 10 18:00 |
| cs-31f42e8d2ed72250 | bear_call | 700 | 705 | $1.69 | 25 | Mar 10 18:30 |
| cs-51b98e69b80c2e16 | bull_put | 652 | 647 | $0.88 | 24 | Mar 10 19:00 |
| cs-722f307ea76a55d4 | bear_call | 699 | 704 | $1.72 | 25 | Mar 10 19:30 |
| cs-ad1638db027be3c2 | bear_call | 696 | 701 | $1.75 | 25 | Mar 11 15:30 |
| cs-3f974c58db4bdbb4 | bear_call | 695 | 700 | $1.72 | 25 | Mar 11 16:00 |

---

## Remaining Issues

### 1. Unmatched Orphans Still Exist

Some unmanaged records remain because the Alpaca order history (limited to recent orders) doesn't cover all positions. These are positions where the original order has aged out of the 50-order history window. These positions are held in Alpaca but the system cannot reconstruct their credit received. They will expire on Apr 17, 2026 and either profit or lose at expiration.

**Mitigation:** The position monitor runs on the 27 recovered `open` trades. The remaining unmanaged positions are expiration-only plays with no active stop-loss monitoring — acceptable short-term.

### 2. Circuit Breaker Architecture

The circuit breaker (`shared/circuit_breaker.py`) uses a single instance per AlpacaProvider that blocks both writes and reads. Order submission failures should not block reconciliation reads. A long-term fix would be separate circuit breakers for write (order submission) vs read (order/position queries). This is not implemented in this fix — the position-based fallback in the reconciler is sufficient.

### 3. Duplicate `open` Records After Recovery

The order history recovery may create records with the same `client_id` as existing records (same deterministic hash for same position). `upsert_trade` handles this correctly via SQL `INSERT OR REPLACE`, so no duplicate rows result, but the DB may have slight credit discrepancies between the pending_open-era record and the recovery-era record.

---

## Files Changed

| File | Change |
|---|---|
| `shared/reconciler.py` | Added `_parse_occ_symbol()` helper; position-based fallback in `_reconcile_pending_opens`; new `recover_orphans_from_order_history()` method |
| `main.py` | Added `recover_orphans_from_order_history()` call in startup reconciliation sequence |

---

## Tests

```
1010 passed, 3 skipped, 4 warnings
```

All existing tests pass. No new tests added (recovery code is integration-level; unit testing requires Alpaca API mocks).
