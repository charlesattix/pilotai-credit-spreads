# Merge Analysis: `maximus/unified-front` → `main`

**Date:** 2026-03-15  
**Merge base:** `d1cc8d3` (fix: preserve exact strike prices through execution pipeline)

## Summary

❌ **NOT a clean merge.** 5 files have conflicts.

## Branch Divergence

- **Commits on `main` not in `unified-front`:** 44 commits (CI fixes, champion-config merges, alignment patches FIX 1-16, INF-2 through INF-5, BT-1/BT-2/BT-3, ML-1)
- **Commits on `unified-front` not in `main`:** 22 commits (Operation Unified Front — straddle/strangle support, unified entry/exit, strategy dispatch, Phase 1-5)

## Conflicting Files (5)

### 1. `alerts/alert_router.py` — 5 conflict regions
**Root cause:** Dedup key strategy diverged. Main uses `(ticker, expiration, strike_type)` tuples; unified-front uses `(ticker, direction, alert_type)` tuples.
- `_mark_dedup()` signature differs
- `_load_dedup_from_db()` key construction differs
- Batch dedup key construction differs (3 locations)

### 2. `execution/position_monitor.py` — 2 conflict regions
**Root cause:** 
- **Imports:** Main added `notify_api_failure`; unified-front added `trade_dict_to_position`, `MarketSnapshot`, `PositionAction`
- **Profit target / stop loss logic:** Main has backtester-aligned fixed thresholds; unified-front adds per-trade profit_target/stop_loss with global fallback (BUG-A fix)

### 3. `main.py` — 2 conflict regions
**Root cause:**
- **Imports:** Unified-front adds `load_config`, `setup_logging`, `validate_config`, strategy imports, `signal_to_opportunity`
- **`_analyze_ticker()` core logic:** Main keeps rules-based scoring + ML feature logging; unified-front replaces with unified strategy signal generation loop

### 4. `tests/test_bug_fixes.py` — 1 conflict region
**Root cause:** Dedup ledger key assertion differs (`("XLE", "2026-04-17", "C")` vs `("XLE", "bearish", "credit_spread")`) — follows from alert_router.py dedup key change.

### 5. `tests/test_execution_fixes.py` — 1 conflict region
**Root cause:** Test for combo regime fallback behavior. Main expects `'BULL'` fallback (matches backtester starting state); unified-front expects `'NEUTRAL'` and adds `build_live_market_snapshot` mock.

## Resolution Complexity

| File | Difficulty | Notes |
|------|-----------|-------|
| `alerts/alert_router.py` | **High** | Fundamental dedup strategy difference — needs design decision on which key scheme to use |
| `execution/position_monitor.py` | **Medium** | Both import sets needed; per-trade thresholds (unified-front) need to coexist with backtester alignment notes (main) |
| `main.py` | **High** | Core analysis logic diverged — unified strategy loop vs rules-based scoring |
| `tests/test_bug_fixes.py` | **Low** | Follows dedup key decision |
| `tests/test_execution_fixes.py` | **Low** | Need to decide fallback regime (BULL vs NEUTRAL) |

## Test Count (unified-front branch)

**1,124 tests collected** (pytest `--co` on `tests/`)

## Recommendation

This merge requires manual conflict resolution with careful design decisions, particularly around:
1. **Dedup key strategy** — unified-front's `(ticker, direction, alert_type)` is more extensible for multi-strategy support
2. **Entry analysis pipeline** — main's `_analyze_ticker()` and unified-front's strategy loop need reconciliation
3. **Per-trade vs global exit thresholds** — unified-front's approach is more flexible but needs backtester alignment notes preserved
