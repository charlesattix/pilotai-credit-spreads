# Code Review: Operation Unified Front (`maximus/unified-front`)

**Reviewer:** AI Code Review Agent  
**Date:** 2026-03-15  
**Branch:** `maximus/unified-front` (commit `4d9eb8b`)  
**Test Suite:** ✅ 1121 passed, 3 skipped, 0 failures

---

## Executive Summary

This branch unifies the live trading entry/exit path with the backtester's strategy classes (`CreditSpreadStrategy`, `IronCondorStrategy`, `StraddleStrangleStrategy`). It introduces three new bridge files (`snapshot_builder.py`, `strategy_factory.py`, `signal_scorer.py`) and significantly refactors `main.py`, `position_monitor.py`, and `execution_engine.py`. The architecture is sound and the tests all pass, but there are several issues worth addressing before merge.

**Overall Quality:** Good — clean architecture, well-documented, but has a dedup persistence bug and some removed safety features that need conscious sign-off.

---

## CRITICAL Issues

### C1. Dedup `alert_type` not persisted to DB — dedup key mismatch after restart
**File:** `alerts/alert_router.py` (lines ~309-322, ~335-340)  
**File:** `shared/database.py` (line 338)

The in-memory dedup key is a 3-tuple `(ticker, direction, alert_type)`, but `upsert_dedup_entry()` only stores `(ticker, direction)` — `alert_type` is never written to the DB. On restart, `_load_dedup_from_db()` reads `entry.get("alert_type", "credit_spread")` which always returns `"credit_spread"`.

**Impact:** After a restart, an iron condor or straddle/strangle that was deduped before the restart will NOT be deduped (wrong key reconstruction). Could cause duplicate trades.

**Fix:** Add `alert_type` column to the `alert_dedup` table and persist it in `upsert_dedup_entry()`.

### C2. Drawdown circuit breaker removed from execution engine
**File:** `execution/execution_engine.py`

The entire `_check_drawdown_cb()` method and its invocation before order submission were deleted. The config still has `drawdown_cb_pct: 40` in `paper_exp401.yaml`. This means there is **no drawdown protection** on the live execution path anymore.

**Impact:** If account equity drops 40%+, the system will continue opening new positions.

**Question for author:** Was this intentional? If drawdown CB is now handled elsewhere (e.g., RiskGate), document it. If not, this needs to be restored.

### C3. IC close retry logic removed — single-attempt close
**File:** `execution/position_monitor.py` (`_submit_ic_close`)

The 3-attempt retry with 5s delay for iron condor closes was removed. A transient Alpaca API error now causes an immediate failure with no retry, potentially leaving positions unhedged.

**Impact:** Higher risk of partial closes on transient API failures for 4-leg positions.

**Fix:** Restore at least a simple retry (even 1 retry) for IC closes, or add retry at a higher level.

---

## WARNING Issues

### W1. `notify_api_failure` removed but tests still reference it
**File:** `shared/telegram_alerts.py`, `execution/position_monitor.py`  
**File:** `tests/test_api_failure_alerts.py`

The `notify_api_failure()` function was removed from `telegram_alerts.py` and all call sites. However, `tests/test_api_failure_alerts.py` still imports and tests it. These tests likely pass only because they're patching the import path.

**Fix:** Delete or update `tests/test_api_failure_alerts.py` to match the new code.

### W2. `manage_dte` default changed from 0 (disabled) to 21 in PositionMonitor
**File:** `execution/position_monitor.py` (line ~168)

The default `manage_dte` changed from `0` (disabled, matching backtester) to `21`. The `paper_exp401.yaml` config sets `manage_dte: 0`, so this default won't bite for EXP-401, but any config that omits `manage_dte` will now close positions at 21 DTE instead of never.

**Impact:** Silent behavior change for configs that rely on the old default.

**Fix:** Keep default at `0` (disabled) and require explicit opt-in, or document the change prominently.

### W3. Commission default changed from $0.65 to $0.00
**File:** `execution/position_monitor.py` (line ~1269)

`commission_per_contract` default changed from `0.65` to `0.0`. While this makes sense for paper trading, if a live config forgets to set it, P&L calculations will be overstated.

**Fix:** Add a startup warning if `commission_per_contract` is 0 and `paper_mode` is false.

### W4. Regime fallback changed from BULL to NEUTRAL on detector failure
**File:** `main.py` (line ~401)

When `ComboRegimeDetector` fails, the fallback changed from `BULL` (conservative — blocks ICs) to `NEUTRAL` (allows ICs). The old comment explained BULL was intentionally conservative.

**Impact:** On detector failure, ICs are now allowed when they shouldn't be (regime unknown).

**Fix:** Consider keeping `BULL` as the safe fallback, or use a dedicated `UNKNOWN` regime that blocks non-CS strategies.

### W5. Feature logger and deviation tracker removed
**File:** `execution/execution_engine.py`, `execution/position_monitor.py`

ML feature logging (`FeatureLogger`) and deviation tracking (`record_deviation`) were completely removed from the entry and exit paths.

**Impact:** Loss of ML training data collection and paper-vs-backtest deviation monitoring.

**Question for author:** Is this intentional cleanup of unused features, or should these be re-integrated after the unified path stabilizes?

### W6. PositionMonitor exit snapshot uses hardcoded market defaults
**File:** `execution/position_monitor.py` (`_build_exit_snapshot`)

The minimal snapshot for `manage_position()` uses hardcoded values: `vix=20.0`, `iv_rank=25.0`, `rsi=50.0`. These feed into strategy exit decisions.

**Impact:** Strategy exit logic that depends on VIX, IV rank, or RSI will get stale/default values, potentially making wrong exit decisions.

**Fix:** Fetch real VIX and ticker data for exit snapshots, even if cached/lightweight.

### W7. Straddle close uses `submit_single_leg` for open but `close_single_leg` for close
**File:** `execution/position_monitor.py` (lines ~904, ~918)

The straddle close path correctly changed from `submit_single_leg` to `close_single_leg` (which uses `BUY_TO_CLOSE`/`SELL_TO_CLOSE` intents). Good change. However, there's no integration test verifying the close flow end-to-end with the new method.

### W8. `reprice_signals_from_chain` hardcodes 0.05 slippage
**File:** `shared/snapshot_builder.py` (line ~136)

```python
signal.net_credit = round(total_credit - 0.05, 4)  # slippage
```

The 0.05 slippage deduction is hardcoded. Should come from config (`risk.slippage` is available in `paper_exp401.yaml`).

---

## INFO Issues

### I1. `score_signal` straddle POP heuristic may produce odd values
**File:** `shared/signal_scorer.py` (line ~96)

For straddles, `spread_width` is 0, so the standard POP heuristic `(1 - credit/spread_width)` is skipped. The POP component gets 0 points for straddles unless `metadata["pop"]` is set. This biases straddle scores ~25 points lower than credit spreads.

### I2. `strategy_factory.py` credit_spread always enabled
**File:** `shared/strategy_factory.py` (line ~95)

Credit spread strategy is unconditionally added. IC and SS check `enabled: true`. For consistency, CS should also have an `enabled` flag (defaults to true).

### I3. Exit snapshot cache is per-ticker but only stores one ticker
**File:** `execution/position_monitor.py` (`_build_exit_snapshot`)

The cache check looks for `ticker in self._exit_snapshot_cache.prices` but only stores one ticker per snapshot. When monitoring multiple tickers, the first ticker's snapshot is cached and returned for all tickers within 60s if they happen to match. Different tickers will miss and rebuild. This is fine but slightly misleading.

### I4. `paper_exp401.yaml` — `manage_dte: 0` disables DTE exit for all strategies
The config sets `manage_dte: 0` at the top level, but the IC and SS strategy param extractors also read it. With `manage_dte: 0`, neither the PositionMonitor nor the strategy `manage_position()` will trigger DTE-based exits (both check `manage_dte > 0`). This means positions can only exit via profit target, stop loss, or expiration day. This is a valid choice but should be intentional.

### I5. Unused `typing.Any` and `typing.Dict` imports in strategies
**Files:** `strategies/credit_spread.py`, `strategies/iron_condor.py`, `strategies/straddle_strangle.py`

All three add `from typing import Any, Dict, List` but `Any` and `Dict` are unused in the strategy files themselves (only `List` is used).

### I6. `signal_to_opportunity` not reviewed (no diff shown)
The function `signal_to_opportunity` in `shared/strategy_adapter.py` is imported and used in `main.py` but the diff only showed default value changes in `trade_dict_to_position`. Ensure `signal_to_opportunity` correctly maps all signal types (CS, IC, SS) to opportunity dicts.

### I7. Event-aware long straddle exit imports `datetime` inside method
**File:** `strategies/straddle_strangle.py` (line ~229)

```python
from datetime import datetime as dt_cls
```

This import is inside the `manage_position()` hot path. While Python caches module imports, it's cleaner to import at module level.

### I8. `vix_history` field on MarketSnapshot
**File:** `shared/snapshot_builder.py`

`vix_history` is passed to `MarketSnapshot` but may not be a declared field on the dataclass. If `MarketSnapshot` uses `__slots__` or strict field checking, this could fail silently.

---

## Positive Observations

1. **Architecture is clean** — the bridge pattern (snapshot_builder → strategy → signal_scorer → signal_to_opportunity) is well-structured and easy to follow.
2. **Strategy factory** is well-designed with per-strategy param extraction.
3. **Dedup key simplification** from `(ticker, expiration, strike_type)` to `(ticker, direction, alert_type)` is the right call for multi-strategy support.
4. **Spread-width 90% safety cap** added to all three strategies' `manage_position()` — good defensive coding.
5. **Dual-leg straddle close reconciliation** in PositionMonitor is well-handled with partial fill detection.
6. **All 1121 tests pass** with no failures.

---

## Recommended Actions Before Merge

| Priority | Action |
|----------|--------|
| **CRITICAL** | Fix C1: Add `alert_type` to dedup DB schema |
| **CRITICAL** | Confirm C2: Drawdown CB removal is intentional (document where it's handled now) |
| **CRITICAL** | Fix C3: Restore IC close retry logic |
| **HIGH** | Fix W4: Reconsider NEUTRAL as regime fallback on detector failure |
| **MEDIUM** | Fix W2: Keep `manage_dte` default at 0 |
| **MEDIUM** | Fix W6: Use real market data for exit snapshots |
| **LOW** | Fix W8: Make slippage configurable in `reprice_signals_from_chain` |
| **LOW** | Clean up unused imports (I5) |
