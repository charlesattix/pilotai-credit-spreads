# Reconciler Overhaul Review
**Commit:** d5e6319
**Reviewer:** cc-spy-maint session
**Date:** 2026-03-20

---

## Summary

The 5-fix reconciler overhaul is **correct and well-structured**. The design is conservative, idempotent, and handles the primary failure modes from the IC wing-ID mismatch bug. Test suite is **1384 passed / 0 failed** after one regression fix (see below).

---

## Fix-by-Fix Assessment

### Fix 1 — IC Wing Order IDs Stored in DB ✅
`execution_engine.py` now writes `alpaca_put_order_id = client_id + "-put"` and `alpaca_call_order_id = client_id + "-call"` into the trade record at submission time. Reconciler uses these stored IDs first, falls back to deriving `client_id + "-put/call"` for legacy records.
**Correct.** The deterministic suffix scheme is idempotent and crash-safe.

### Fix 2 — Batch Fetch Limit 100 → 500 ✅
`get_orders(status="all", limit=500)`. At ~3 IC trades/day × 2 wing orders × 30 days = ~180 orders in the lookback window. 500 provides a 2.7× safety margin.
**Correct.** Consider raising to 1000 if the system runs continuously for 60+ days without a restart, but 500 is fine for current volume.

### Fix 3 — Wing Suffix Belt-and-Suspenders ✅
Before age-based `failed_open`, reconciler checks `client_id + "-put"` and `client_id + "-call"` in the batch. Prevents false-positive failures for any IC trade where `strategy_type` might not include "condor" (e.g., data corruption, legacy records).
**Correct.** The "leave pending" behavior is safe — worst case it stays pending until the 4h age threshold.

### Fix 4 — failed_open Recovery Path ✅
`_detect_orphan_positions()` now builds `failed_trade_by_symbol` from all `failed_open` trades. When an orphan Alpaca position matches a failed_open trade's OCC symbol, the trade is promoted to `open` instead of creating a new `unmanaged` record.
**Correct.** The dedup loop (`del failed_trade_by_symbol[sym]` for all syms of the recovered trade) prevents double-recovery of the same trade. See edge cases below.

### Fix 5 — Periodic Orphan Detection ✅
`reconcile_pending_only()` (called every monitor cycle) now runs orphan detection every 30 min via `_should_run_orphan_check()`. Previously orphan detection only ran at startup via `reconcile()`.
**Correct.** The 30-min throttle prevents API spam. Timestamp is persisted to `scanner_state` so it survives process restarts.

---

## Regression Introduced (Fixed in This Review)

**`alerts/telegram_bot.py`** — the commit switched `send_alert` from synchronous to `asyncio.run()` but removed `read_timeout=10, write_timeout=10` parameters. This broke `test_send_alert_calls_bot`.

**Fixes applied:**
1. Restored `read_timeout=10, write_timeout=10` to the `asyncio.run(self.bot.send_message(...))` call
2. Updated `test_telegram_bot.py::test_send_alert_calls_bot` to use `AsyncMock` for `mock_bot.send_message` (required for async coroutine mocking with python-telegram-bot v21)

---

## Edge Cases Identified

### EC-1: One IC Wing Fills, Other Gets Rejected (HANDLED — but note the asymmetry)
`_reconcile_ic_pending()` correctly marks `failed_open` if any wing is in `_TERMINAL_ORDER_STATES`.
However, when the put wing fills and the call wing is rejected, the **put spread is now live in Alpaca** but the trade is marked `failed_open`. On the next full `reconcile()`, Fix 4 will recover the IC trade to `open` via the orphan path.

**Gap:** The recovered IC will have `status=open` but the P&L calculation will be based on the full IC credit, not just the put wing's credit. If only the put spread executed, `alpaca_fill_price` will reflect the full put+call fill sum (which is wrong for a partial IC).

**Recommendation:** When only one wing exists in Alpaca during Fix 4 recovery, record `partial_fill=True` on the trade and flag for manual review rather than silently promoting to `open`. The position monitor may try to close both wings but only one exists.

### EC-2: Partial Fill on Multi-Leg Order (UNHANDLED)
Alpaca can return `status="partially_filled"` for a multi-leg order. The reconciler's `_reconcile_pending_opens()` handles this correctly — it falls through to the `else` branch:
```python
else:
    # Order still live (submitted, pending_new, partially_filled, etc.)
    logger.debug("Trade %s order status=%s — leaving as pending_open", ...)
```
This is fine for brief partial fills. **But:** if an order stays `partially_filled` for hours (e.g., illiquid strikes), it will never hit `_TERMINAL_ORDER_STATES` and will never age out (only `order is None` triggers the age check). It will stay `pending_open` indefinitely.

**Recommendation:** Add `partially_filled` age-based handling: if order has been `partially_filled` for > `_PENDING_MAX_AGE_HOURS`, mark as `failed_open` and log a warning for manual review of the partially-filled legs in Alpaca.

### EC-3: Race Condition Between Scan and Reconciliation (LOW RISK — mitigated)
`reconcile_pending_only()` is called on the monitor cycle. The scan cycle runs on a separate cron (`scan-cron.sh`). Both can call `upsert_trade()` on the same trade simultaneously.

SQLite's default WAL mode serializes writes. The trade record has no multi-field atomicity guarantee — a partial update is possible in theory. However, `upsert_trade()` calls replace the entire record, so the last writer wins.

**Worst case:** reconciler reads `status=pending_open`, promotes to `open`, writes. Scanner reads the same record milliseconds later (before the write lands) and also sees `pending_open`. Scanner doesn't write status directly (it only calls `submit_opportunity` for NEW trades), so the race is not a realistic problem in the current architecture.

**Verdict:** Low risk. No fix needed.

### EC-4: Failed_open Recovery with Matching Ticker Prefix but Wrong Expiration
`_expected_symbols()` builds full OCC symbols including expiration date. If a `failed_open` trade has a wrong expiration (e.g., due to the `actual_exp` substitution path in `ExecutionEngine`), its OCC symbols won't match the live Alpaca position, and Fix 4 won't fire. The position becomes an unmanaged orphan.

**This is safe behavior** — conservative (correct). The only risk is the trade stays `failed_open` and the position stays `unmanaged` until manual review.

**Recommendation:** When the expiration substitution path fires (`actual_exp != expiration`), also update `alpaca_put_order_id`/`alpaca_call_order_id` if it's an IC, to prevent downstream symbol mismatches. (This is already partially handled — the DB record gets the correct expiration — but worth verifying in integration.)

### EC-5: `orphan_id` Collision for Multi-Leg Orphans
When creating unmanaged orphan records, the ID is built as:
```python
orphan_id = f"orphan-{symbol[:20]}"
```
For an IC with 4 orphan legs, this creates 4 separate unmanaged records (one per symbol). Each `upsert_trade` call will overwrite the previous one if the ticker prefix matches. Since each symbol is unique (different strike/type), this is fine — `symbol[:20]` differentiates them.

**Verified safe.** No fix needed.

---

## Test Coverage Assessment

| Area | Tests | Coverage |
|------|-------|----------|
| Fix 1 (wing IDs in DB) | 5 tests | ✅ Full happy path + fallback + failure |
| Fix 2 (batch limit 500) | 1 test | ✅ Verifies call args |
| Fix 3 (wing suffix fallback) | 2 tests | ✅ Both branches |
| Fix 4 (failed_open recovery) | 2 tests | ✅ Recovery + no-match fallback |
| Fix 5 (periodic orphan check) | 7 tests | ✅ All throttle branches |
| IC lifecycle integration | 1 test | ✅ Submit → fill → reconcile |

**Missing test:** EC-2 (partial fill age-out). EC-1 partial IC recovery is tested via Fix 4 but the `partial_fill` metadata gap is not tested.

---

## Verdict

**SHIP-READY** with the telegram regression fixed. The 5 core fixes are correct, conservative, and idempotent. The two actionable gaps (EC-1 partial IC fill metadata, EC-2 partial fill age-out) are medium priority — they won't cause data loss but may cause incorrect P&L or stuck `pending_open` records. Recommend addressing in the next maintenance window.
