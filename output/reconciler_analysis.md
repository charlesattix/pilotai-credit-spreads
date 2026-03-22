# Reconciler Root Cause Analysis

**Date:** 2026-03-20
**Scope:** `shared/reconciler.py`, `execution/execution_engine.py`, `execution/position_monitor.py`
**Status:** Analysis only — no code changes.

---

## Executive Summary

Three independent bugs interact to produce two failure modes:

1. **IC (iron condor) `pending_open` trades are permanently stuck** — they can never be promoted to `open` because the reconciler looks up the wrong `client_order_id`.
2. **Orphan positions accumulate silently** — once an IC trade is incorrectly marked `failed_open`, its actual filled legs remain live in Alpaca with no managed DB record.

---

## Bug 1: IC `client_order_id` Suffix Mismatch (Root Cause)

### Where it breaks

`ExecutionEngine._submit_iron_condor()` submits two separate MLEG orders with **suffixed** IDs:

```python
# execution_engine.py lines 403–421
put_result = self.alpaca.submit_credit_spread(
    ...
    client_order_id=client_id + "-put",   # e.g. "cs-abc123def456-put"
)
call_result = self.alpaca.submit_credit_spread(
    ...
    client_order_id=client_id + "-call",  # e.g. "cs-abc123def456-call"
)
```

But the DB record written before Alpaca submission stores the **bare** ID:

```python
# execution_engine.py line 189
trade_record = {
    "id": client_id,                             # "cs-abc123def456"
    "alpaca_client_order_id": client_id,         # "cs-abc123def456" — NO suffix
    ...
}
```

### Why the reconciler can't find the order

`_reconcile_pending_opens()` does:

```python
client_order_id = trade.get("alpaca_client_order_id")  # → "cs-abc123def456"
order = orders_by_client_id.get(client_order_id)       # → None (key doesn't exist)
if order is None:
    order = self.alpaca.get_order_by_client_id(client_order_id)  # → also None or 404
```

Alpaca's order list contains `"cs-abc123def456-put"` and `"cs-abc123def456-call"` — not `"cs-abc123def456"`. The bare ID matches nothing. The reconciler then hits the age check:

```python
age_hours = self._trade_age_hours(trade, now)
if age_hours >= _PENDING_MAX_AGE_HOURS:    # 4 hours
    trade["status"] = "failed_open"
    trade["exit_reason"] = "alpaca_order_not_found"
```

**Result:** Every IC trade is marked `failed_open` after 4 hours, even when both wings filled successfully.

---

## Bug 2: MLEG 404 on Per-Trade Fallback

For non-IC spreads, the batch fetch (`get_orders(status="all", limit=100)`) was added specifically to work around Alpaca returning 404 for MLEG orders via `GET /v2/orders/{client_order_id}`. The fallback path:

```python
order = self.alpaca.get_order_by_client_id(client_order_id)
```

…still returns 404 for any multi-leg option order. If a trade's order is not in the batch (see Bug 3), the per-trade fallback will also fail, producing the same `failed_open` outcome.

---

## Bug 3: Batch Fetch `limit=100` Too Small

`_fetch_recent_orders_by_client_id()` fetches only the 100 most recent orders:

```python
orders = self.alpaca.get_orders(status="all", limit=100)
```

When two experiments run simultaneously, each 5-minute scan cycle submits multiple orders. Under normal load, 100 recent orders spans roughly 30–60 minutes. An order submitted earlier in the session, or while the batch is filled by the second experiment's traffic, may fall outside the 100-order window. That order then falls through to the MLEG-404 fallback and gets stuck.

---

## Why Orphan Positions Accumulate

The orphan lifecycle has two entry points:

### Entry Point A: IC wing submitted but cancel failed

When the call wing fails during IC submission, `_submit_iron_condor()` attempts to cancel the put wing. If the cancel fails:

```python
logger.error("CRITICAL — put wing cancel FAILED ... Manual intervention required.")
```

The put wing order stays live in Alpaca. When it fills, a real option position exists with no `open` DB record. At startup, `_detect_orphan_positions()` catches this and creates an `unmanaged` record. But `unmanaged` positions are never managed — no close logic, no P&L tracking.

### Entry Point B: IC fills but gets mismarked `failed_open`

This is the larger source. The sequence:

1. IC submitted → DB has `pending_open` with `alpaca_client_order_id = "cs-abc123def456"`
2. Both wings fill in Alpaca (orders `cs-abc123def456-put` and `cs-abc123def456-call` → filled)
3. Reconciler looks for `cs-abc123def456` → not found (Bug 1)
4. After 4 hours → trade marked `failed_open`
5. `failed_open` removes the trade from the "managed" set
6. At next startup, `_detect_orphan_positions()` checks managed symbols from `open` + `pending_open` trades only — `failed_open` excluded
7. The filled IC legs appear in Alpaca as option positions with no matching managed symbol → `unmanaged` record created

### Why orphans persist indefinitely

`_detect_orphan_positions()` only runs at startup (called from `reconcile()`, not `reconcile_pending_only()`). The `unmanaged` record has:

```python
orphan_record = {
    "id": orphan_id,
    "status": "unmanaged",
    ...
}
```

There is no code path anywhere in the system that transitions `unmanaged` → anything else. The actual Alpaca position continues to exist (accruing P&L) until it expires or is manually closed, but the system neither tracks its value nor attempts to close it at the exit conditions (stop-loss, profit target, DTE limit).

---

## Secondary Issue: `closed_external` False Positives

`position_monitor.py`'s `_all_legs_missing()` checks whether OCC symbols for an `open` trade are absent from Alpaca positions. OCC symbols are constructed from DB fields. If the DB stores a slightly different expiration format than what Alpaca uses (e.g., `2026-04-17` vs `20260417`), the symbol comparison fails and a live position is misidentified as closed. This would mark a genuinely open trade as `closed_external`, remove it from the managed set, and the legs become orphans by the same mechanism above.

---

## Proposed Fix (Implementation Guidance Only)

### Fix 1: Store suffixed IDs for IC legs in the DB

When an IC is submitted, record both wing order IDs so the reconciler can look them up:

- Add `alpaca_put_order_id` and `alpaca_call_order_id` fields to the trade record after `_submit_iron_condor()` returns
- Change `_reconcile_pending_opens()` to check for IC trades specially: if `alpaca_client_order_id` is not in the batch, also try `client_order_id + "-put"` and `client_order_id + "-call"`
- An IC trade is `filled` only when **both** wings are `filled`; it is `failed_open` only when **any** wing is in a terminal state

### Fix 2: Increase batch fetch limit or paginate

Replace `limit=100` with `limit=500` or implement pagination. Given the order volume, 500 covers ~2.5× the current 100-order window and eliminates the gap under dual-experiment load without requiring API pagination complexity.

### Fix 3: Include IC wing IDs in `alpaca_client_order_id` fallback search

As a belt-and-suspenders measure, before marking `failed_open` for age, also search the batch for `client_order_id + "-put"` — if either wing is found, the IC is live.

### Fix 4: Add a recovery path for `failed_open` with live Alpaca positions

At startup, during `_detect_orphan_positions()`, before creating a new `unmanaged` record, check if there is an existing `failed_open` trade whose OCC symbols match the Alpaca position. If so, promote the `failed_open` → `open` with a reconciliation event rather than creating a duplicate orphan record.

### Fix 5: Periodic orphan detection

Move `_detect_orphan_positions()` into `reconcile_pending_only()` (or run it every N cycles, e.g., every 30 min) so orphans created intraday are detected without requiring a restart.

---

## Impact Summary

| Symptom | Root Cause | Effect |
|---------|-----------|--------|
| IC trades stuck in `pending_open` | Bug 1: suffix mismatch | All ICs marked `failed_open` after 4h |
| Non-IC trades occasionally stuck | Bug 2+3: MLEG 404 + limit=100 | Intermittent `failed_open` under load |
| Orphan positions in Alpaca | Mismarked `failed_open` + IC wing cancel failure | Unmanaged, untracked positions |
| `unmanaged` records never resolved | No state machine exit from `unmanaged` | Silent P&L leakage; possible margin exposure |
| Possible false `closed_external` | OCC symbol format mismatch | Live positions removed from managed set |

The most urgent fix is **Bug 1** (IC suffix mismatch) because it guarantees 100% failure for every IC trade with no workaround.
