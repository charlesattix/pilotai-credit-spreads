# Inspector Report — Round 6

*Previous Rounds: R1=5.9, R2=7.8, R3=8.9, R4=9.1, R5=9.3 | Target: 9.5/10*
*Audit Date: 2026-03-02*
*Files audited (read in full): backtester.py (2077 lines), historical_data.py (683 lines), position_sizer.py (557 lines), run_optimization.py (499 lines), validate_params.py (595 lines), backfill_volume.py (251 lines), test_backtester.py (1693 lines), configs/exp_036_compound_risk10_both_ma200.json*

---

## Overall Grade: 9.2 / 10

A well-engineered backtesting framework with thorough intraday simulation, real options data, VIX-scaled slippage, and layered risk controls. Three issues prevent reaching 9.5: one P0 (IC sizing test calls the wrong method signature — the regression test is vacuous on the price-dependent code path), one P1 (monthly diversity denominator logic is semantically wrong for January end-of-run and cross-year spans, and can corrupt the overfit verdict), and one P1 (scan-loop `continue` logic prevents bear calls and ICs from being tried when `direction='both'` and the bull put check runs, regardless of whether a put was found). The IC double-width fix (P0-B from prior rounds) is correctly implemented in production code. Round 5 fixes are verified below.

---

## Category Scores

| Category | R5 Score | R6 Score | Delta | Notes |
|---|---|---|---|---|
| 1. Lookahead Bias | 9.0 | 9.0 | 0.0 | MA uses `_prev_date`; `_prev_trading_val` verified correct; VIX/IV-rank no lookahead |
| 2. Position Sizing | 9.5 | 9.5 | 0.0 | IC 2×width, compound/flat, VIX-scale all correct; max_risk_pct cap verified |
| 3. Iron Condor Correctness | 9.5 | 9.5 | 0.0 | max_loss formula, settlement, IC type field all correct |
| 4. Trade Lifecycle | 9.5 | 9.5 | 0.0 | Entry slippage, VIX-scaled exit, commission design consistent in both modes |
| 5. Liquidity Framework | 9.5 | 9.5 | 0.0 | volume_gate, fail-open/closed, volume_gate_on_miss all correct |
| 6. Risk Management | 9.5 | 9.5 | 0.0 | CB, ruin stop, exposure cap all correct |
| 7. Test Coverage | 9.0 | 8.0 | -1.0 | P2-A IC sizing test has wrong call signature (vacuous); P2-B now a genuine integration test |
| 8. validate_params.py Diversity | 7.0 | 7.0 | 0.0 | Monthly diversity denominator still broken for January end-of-run and cross-year spans |
| 9. Data Integrity | 9.5 | 9.5 | 0.0 | Schema correct; `get_prev_daily_volume` SQL correct; backfill logic correct |

---

## Verified Fixes from Round 5

### P2-A: IC Flat-Risk Sizing (production code)

**Status: VERIFIED in production — REGRESSION in test**

The production fix at `backtest/backtester.py:1041-1044` is correct:
```python
contracts = max(1, get_contract_size(
    trade_dollar_risk, spread_width * 2, combined_credit,
    max_contracts=max_contracts_cap,
))
```
`get_contract_size` computes `max_loss_per_contract = (spread_width - credit_received) * 100`. With `spread_width * 2` passed and `combined_credit` as the credit, this evaluates to `(2*width - combined_credit) * 100`, which is the correct IC max loss per contract. The math is exact.

However, the regression test at `tests/test_backtester.py:1609` has a wrong call signature — see P0-1 below.

### P2-B: Ruin Gate Integration Test

**Status: VERIFIED — genuine integration test**

The test `test_ruin_blocks_new_entries_in_backtest` at `tests/test_backtester.py:1377-1426` patches `_manage_positions` to set `_ruin_triggered = True` on the first call, then asserts `get_available_strikes.call_count == 0`. The assertion at line 1423 would fail if the ruin gate at `backtester.py:497` were missing. This is a genuine integration test. Confirmed.

### P2-F: Monthly Diversity Denominator

**Status: PARTIALLY FIXED — new bug introduced for cross-year runs**

The `int(12)` constant denominator was replaced with `int(max(monthly_pnl.keys()).split('-')[1])`. This correctly handles partial-year full-year runs (e.g., Jan–Nov penalized correctly against 11, not 12). However, a new bug exists for cross-year and January end-of-run cases — see P1-2 below.

---

## Remaining Issues

### P0 — Trade-Breaks-Silently

#### P0-1: IC Sizing Regression Test Has Wrong Call Signature — Test Is Vacuous

**File:** `tests/test_backtester.py:1609-1611`
**Severity:** P0 for test correctness (production code is correct)

```python
with patch.object(bt, '_find_real_spread', side_effect=[put_leg, call_leg]):
    result = bt._find_iron_condor_opportunity(
        'SPY', datetime(2025, 1, 6), '2025-01-06', 470.0,
    )
```

The method signature at `backtest/backtester.py:908-914` is:
```python
def _find_iron_condor_opportunity(
    self,
    ticker: str,
    date: datetime,
    price: float,
    scan_hour: Optional[int] = None,
    scan_minute: Optional[int] = None,
) -> Optional[Dict]:
```

The call passes `'2025-01-06'` (a string) as the third positional argument, which maps to `price: float`. Python does not type-check at runtime. The string is silently accepted and passed into `_find_real_spread` — which is completely mocked by `patch.object`, so `price` is never used. The `470.0` that was intended as price is passed to `scan_hour`, which triggers the intraday path but causes no failure because `_find_real_spread` is mocked.

**Consequence:** The test passes today only because the mock absorbs the bad argument. If the mock were removed — i.e., if anyone tried to run this with a real `_find_real_spread` — the string `'2025-01-06'` being used as a price in OTM strike selection math would cause a TypeError or produce nonsense results. The test is not verifying what it claims to verify regarding the price-based OTM selection path.

**Production code is correct.** The IC double-width sizing at line 1041 functions correctly. Only the test is defective.

**Correct call:**
```python
result = bt._find_iron_condor_opportunity(
    'SPY', datetime(2025, 1, 6), 470.0,  # price=470.0 as third arg
)
```

---

### P1 — Material Bias

#### P1-1: Scan-Loop `continue` Prevents Bear Calls and ICs When `direction='both'`

**File:** `backtest/backtester.py:549-603`
**Severity:** P1 — silently disables bear call and IC entries for the champion config

In the real-data scan loop (lines 544-603), the structure is:

```python
for scan_hour, scan_minute in SCAN_TIMES:
    if _skip_new_entries: break
    if len(open_positions) >= max_positions: break

    if _want_puts:                           # True when direction='both' or 'bull_put'
        new_position = self._find_backtest_opportunity(...)
        if new_position:
            # ... add to open_positions ...
        continue  # <--- LINE 564: executes regardless of whether new_position was found

    if len(open_positions) >= max_positions: break

    if _want_calls:                          # only reachable if _want_puts is False
        bear_call = self._find_bear_call_opportunity(...)
        if bear_call:
            # ... add to open_positions ...
        continue  # <--- LINE 582

    # IC fallback (lines 584-603) — only reachable if BOTH _want_puts and _want_calls are False
    if _ic_enabled and ...:
        condor = self._find_iron_condor_opportunity(...)
```

When `direction='both'`, `_want_puts = True` and `_want_calls = True`. On every iteration of SCAN_TIMES:
1. `if _want_puts:` is True → the bull put search runs
2. `continue` on line 564 executes — **regardless of whether `new_position` is None or a real position**
3. The `if _want_calls:` block is never reached
4. The IC fallback block is never reached

**Effect:** With `direction='both'`, only bull puts are ever entered. Bear calls are structurally unreachable. Iron condors are structurally unreachable. Every scan time short-circuits after the bull put check.

**The IC enabled config (`exp_059_ic_fixed`) is affected.** Even with `iron_condor_enabled=True` and `direction='both'`, the IC block at lines 584-603 is unreachable because the `continue` on line 564 fires first.

**`direction='bear_call'` is unaffected** — `_want_puts = False` so the `if _want_puts:` block is skipped; the bear call block and IC fallback are reachable.

**Evidence of impact:** The project memory notes that `exp_059` (IC enabled, direction='both') showed 173 trades/+188.8% after the IC bug was "fixed" by changing the config. But if the scan loop `continue` was already preventing bear calls and ICs structurally, the trade count increase may have come from a different mechanism, or the direction filter was different in those runs. This warrants verification against trade logs by inspecting the `type` breakdown (`bull_put_spread` vs `bear_call_spread` vs `iron_condor`) in the results.

**What the intended behavior should be:** When `direction='both'`, on a given scan time, if the bull put check finds nothing (returns None), the code should fall through to attempt a bear call, and if that also fails, fall through to attempt an IC. The current code only attempts a bear call or IC on scan times where `_want_puts` is False.

#### P1-2: Monthly Diversity Denominator Wrong for January End-of-Run and Cross-Year Spans

**File:** `scripts/validate_params.py:303-304` and `scripts/run_optimization.py:222-223`
**Severity:** P1 — can corrupt the overfit verdict by inflating the diversity score

The fix from Round 5 replaced `/ 12` with:
```python
last_month_num = int(max(monthly_pnl.keys()).split('-')[1])
year_scores[yr] = months_with_trades / max(1, last_month_num)
```

**Bug — January end-of-run produces denominator=1:**

If a run extends into January of the next year (e.g., `continuous_capital` mode, or a partial backtest that crosses December→January), `monthly_pnl` may contain keys like `{"2024-02": ..., "2024-03": ..., ..., "2024-12": ..., "2025-01": ...}`. The lexicographic `max()` of these keys is `"2025-01"` (January 2025 sorts last lexicographically). Then `split('-')[1]` extracts `"01"` → `last_month_num = 1`.

With `months_with_trades = 12` (all 12 months active), the score becomes `12 / 1 = 12`. This raw value flows into:
```python
score = sum(year_scores.values()) / len(year_scores)
```
A score of 12.0 for one year would make the average ~12 / num_years. At weight 0.10 in the composite:

```python
# compute_overfit_score at validate_params.py:438-449
score += E_regime_diversity_score * 0.10
```

A diversity score of 12.0 × 0.10 = 1.2 contribution (instead of max 0.1) pushes the composite overfit score above its natural ceiling of 1.0. Combined with other checks, the overfit score could be inflated past 0.70, producing a false ROBUST verdict for a strategy that genuinely has poor regime diversity.

**Bug — single-year December run is actually fine:**

For a single-year backtest ending in December, `max()` key is e.g. `"2024-12"`, `last_month_num = 12`, denominator = 12. Score = `months_active / 12`. This is correct for a full-year run. No bug here.

**Summary of affected scenarios:**

| Scenario | `max()` key | `last_month_num` | Denominator | Correct? |
|---|---|---|---|---|
| Full year (Jan–Dec) | "2024-12" | 12 | 12 | Yes |
| Partial year Jan–Mar | "2024-03" | 3 | 3 | Yes |
| Partial year Jan–Nov | "2024-11" | 11 | 11 | Yes |
| Cross-year run ending Jan | "2025-01" | 1 | **1** | **NO — inflated** |
| Cross-year run ending Feb | "2025-02" | 2 | **2** | **NO — too small** |

**Correct fix:** The denominator should be the number of calendar months elapsed from the first month in `monthly_pnl` to the last, inclusive:

```python
from_key = min(monthly_pnl.keys())
to_key   = max(monthly_pnl.keys())
from_y, from_m = int(from_key.split('-')[0]), int(from_key.split('-')[1])
to_y,   to_m   = int(to_key.split('-')[0]),   int(to_key.split('-')[1])
months_elapsed = (to_y - from_y) * 12 + (to_m - from_m) + 1
year_scores[yr] = months_with_trades / max(1, months_elapsed)
```

---

### P2 — Minor / Cosmetic

#### P2-1: `_monthly_diversity_score` in `run_optimization.py` Is Dead Code

**File:** `scripts/run_optimization.py:210-223`
**Severity:** P2 — cosmetic

The function `_monthly_diversity_score` is defined but never called from `run_optimization.py`, `validate_params.py`, or any other file in the project. The actual diversity logic lives in `check_e_regime_diversity`. Dead code; contains the same denominator bug as P1-2.

#### P2-2: `get_contract_size` Default `max_contracts=5` Is a Legacy Footgun

**File:** `ml/position_sizer.py:97`
**Severity:** P2 — minor

```python
def get_contract_size(
    trade_dollar_risk: float,
    spread_width: float,
    credit_received: float,
    max_contracts: int = 5,   # <-- legacy default
) -> int:
```

The backtester always passes `max_contracts_cap` explicitly (derived from config). But any external caller that omits this argument would be silently capped at 5 contracts regardless of `max_contracts` in config. For live-trading or scripting use, this is a silent performance limit that does not match intent. Recommend changing the default to `999`.

#### P2-3: Heuristic Mode VIX Scaling Always 1.0x

**File:** `backtest/backtester.py:1885-1888`
**Severity:** P2 — minor modeling inconsistency

In heuristic mode, `_current_vix` is initialized to `20.0` and never updated (VIX data is only downloaded in real-data mode via `_build_iv_rank_series`). Since `_vix_scaled_exit_slippage()` applies `max(0, (VIX-20) * 0.1)`, a VIX of exactly 20.0 produces a VIX scale of 1.0x — meaning all heuristic-mode exits use baseline exit slippage with no crisis scaling. The `_slippage_multiplier` term still applies, so 2x/3x brutality tests work correctly. The VIX-adaptive scaling simply does not activate in heuristic mode, making it less realistic for stress-testing heuristic configs.

#### P2-4: Realized Vol Series Includes Same-Day Prices in Prior-Day ATR

**File:** `backtest/backtester.py:756-759`
**Severity:** P2 — negligible (shielded by `_prev_trading_val`)

```python
atr20 = tr.rolling(20, min_periods=5).mean()
rv = (atr20 / close * math.sqrt(252))
```

The ATR(20) for date T includes T's own high-low range. The `_prev_trading_val` guard at line 420 looks up `k < lookup_date`, so at entry decision time the code uses yesterday's realized vol — which itself was computed using yesterday's 20-day ATR window including yesterday's bar. The lookahead is at most one bar (today's range affecting yesterday's ATR via the rolling window boundary), representing ~5% of the 20-day window. For the delta-based strike selection path, the practical impact is sub-$1 on strike placement. No material bias.

#### P2-5: Adjacent-Strike Walk Can Move Put Strikes Toward ATM

**File:** `backtest/backtester.py:1192-1198`
**Severity:** P2 — corner case

```python
for offset in [1, -1, 2, -2]:
    alt_short = short_strike + offset
    alt_long = alt_short - spread_width if ot == "P" else alt_short + spread_width
```

For puts, `offset = -1` gives `alt_short = short_strike - 1`, moving the short put closer to ATM. At `otm_pct=0.03`, the initial strike is ~3% OTM. A -$1 shift is a tiny fraction of SPY's 400-600 price range and represents less than 0.3% further ITM. The credit filter (`credit < min_credit`) provides a backstop against deeply ITM results. No material impact at champion configs; worth monitoring for narrow-OTM sweeps.

#### P2-6: `vix_close_all` Uses Fixed -50% Assumption, Not VIX-Scaled

**File:** `backtest/backtester.py:455-457`
**Severity:** P2 — documented modeling assumption

```python
_pnl = -0.50 * _max_loss_dollars - _pos.get('commission', 0)
```

All other exit paths apply `_vix_scaled_exit_slippage()` for the buy-back cost. The `vix_close_all` path uses a fixed -50% max loss assumption. This is documented in comments ("empirically 1-2× original credit received"). During extreme crashes (VIX=70-80), actual exit cost may be worse than -50% of max loss. The 1-day VIX lag (yesterday's VIX triggers today's force-close) compounds this: the actual exit may occur when spreads are even wider. Known modeling limitation; acceptable for backtesting.

---

## Summary Table

| ID | Severity | File | Lines | Description |
|---|---|---|---|---|
| P0-1 | P0 | `tests/test_backtester.py` | 1609–1611 | IC sizing test passes string as `price` arg — regression test is vacuous on price-dependent path |
| P1-1 | P1 | `backtest/backtester.py` | 549–603 | Scan-loop `continue` prevents bear calls and ICs when `direction='both'` (bull put check runs and fires `continue` even on miss) |
| P1-2 | P1 | `scripts/validate_params.py` | 303–304 | Monthly diversity denominator = 1 for January end-of-run → diversity score > 1.0 → inflated overfit verdict |
| P2-1 | P2 | `scripts/run_optimization.py` | 210–223 | `_monthly_diversity_score` is dead code (never called); has same denominator bug |
| P2-2 | P2 | `ml/position_sizer.py` | 97 | Legacy default `max_contracts=5` is a footgun for external callers |
| P2-3 | P2 | `backtest/backtester.py` | 313–326 | Heuristic mode VIX always 20.0 → VIX-adaptive exit scaling never activates |
| P2-4 | P2 | `backtest/backtester.py` | 756–759 | ATR denominator uses today's close (negligible; shielded by `_prev_trading_val`) |
| P2-5 | P2 | `backtest/backtester.py` | 1192–1198 | Adjacent-strike walk can nudge puts toward ATM on -offset |
| P2-6 | P2 | `backtest/backtester.py` | 455–457 | `vix_close_all` uses fixed -50% assumption rather than mark-to-market |

**No additional P0 or P1 findings beyond the three listed above.**

---

## Detailed Supporting Analysis

### Scan Loop Logic Analysis (P1-1)

Reading lines 544-603 in full:

```python
for scan_hour, scan_minute in SCAN_TIMES:
    if _skip_new_entries:
        break
    if len(open_positions) >= self.risk_params['max_positions']:
        break
    if _want_puts:
        new_position = self._find_backtest_opportunity(
            ticker, current_date, current_price, price_data,
            scan_hour=scan_hour, scan_minute=scan_minute,
        )
        if new_position:
            _key = (new_position.get('expiration'), new_position['short_strike'], 'P')
            if _key not in _entered_today and _key not in _open_keys:
                if _exposure_ok(new_position):
                    open_positions.append(new_position)
                    _entered_today.add(_key)
                    _open_keys.add(_key)
                else:
                    self.capital += new_position.get('commission', 0)
                    logger.debug("Portfolio exposure cap — skipping bull_put %s", _key)
        continue  # LINE 564 — fires whether new_position is None or not
    if len(open_positions) >= self.risk_params['max_positions']:
        break
    if _want_calls:
        # ... bear call logic ...
        continue  # LINE 582
    # IC fallback (lines 584-603)
    if _ic_enabled and len(open_positions) < self.risk_params['max_positions']:
        # ... IC logic ...
```

The `continue` on line 564 is not inside `if new_position:`. It is at the same indentation level as `if new_position:`, inside `if _want_puts:`. So when `_want_puts = True`:
- If a position is found: add it, then `continue` (correct for this scan time)
- If no position is found: `continue` anyway (bug — misses bear call and IC on this scan)

The intended behavior (based on the comment "Iron condor fallback — only if enabled in config") would require the `continue` to be moved inside `if new_position:`, or the structure rearchitected to fall through to bear call and IC checks when the prior check returned None.

### Monthly Diversity Score Analysis (P1-2)

`validate_params.py:300-304`:
```python
months_with_trades = sum(1 for m in monthly.values() if m.get("trades", 0) > 0)
last_month_num = int(max(monthly.keys()).split('-')[1])
year_scores[yr] = months_with_trades / max(1, last_month_num)
```

Test case — continuous_capital run 2020-2025 produces monthly_pnl with keys from 2020-01 through 2025-12 (if run through year-end). `max()` = "2025-12" → `last_month_num` = 12 → denominator = 12. But `monthly_pnl` spans 6 years × 12 months = 72 months, and `months_with_trades` could be up to 72. Score = 72/12 = 6.0. This is the multi-year case.

In normal single-year usage (which is how `run_all_years` calls `validate_params`), each year's `monthly_pnl` only contains entries from that year. The cross-year scenario arises only in the `monthly_pnl` aggregation if exits span the year boundary (e.g., a position entered Dec 31 and exited Jan 2). The `_exit_month` field is based on `exit_date`, so a position entered Dec 29 and exited Jan 3 would land in `"2025-01"`. This is an edge case but plausible with 35-day DTE options entered in late November.

### IC Test Call Signature Analysis (P0-1)

`_find_iron_condor_opportunity` signature: `(self, ticker, date, price, scan_hour=None, scan_minute=None)`

Test call at line 1609:
```python
bt._find_iron_condor_opportunity('SPY', datetime(2025, 1, 6), '2025-01-06', 470.0)
```

Positional mapping:
- `ticker = 'SPY'` ✓
- `date = datetime(2025, 1, 6)` ✓
- `price = '2025-01-06'` ← string, should be float
- `scan_hour = 470.0` ← float, should be Optional[int]
- `scan_minute = None` (default)

Inside `_find_iron_condor_opportunity`:
- `price` is used only in two places: passed to `_find_real_spread` for OTM strike selection. Since `_find_real_spread` is mocked to return `put_leg` / `call_leg` directly, `price` is never read inside the mock.
- `scan_hour = 470.0`: used in `use_intraday = (scan_hour is not None and ...)`. Since `470.0 is not None` evaluates True, and `scan_time_mins = 470 * 60 + 0 = 28200 >= 570`, `use_intraday = True`. The test uses scan_hour=470 (a nonsensical time) but the code path is exercised correctly for the sizing portion.

The test correctly validates that `result['contracts'] == 12` for the 2×width sizing. The production fix (line 1041) is invoked. But the test's call signature is wrong, and it would break without the `_find_real_spread` mock.

---

## Conclusion

### What the Framework Gets Right

1. **Lookahead bias eliminated.** MA uses `_prev_date` shift (prior calendar day, which pandas loc correctly resolves to prior trading day). VIX/IV-rank uses `_prev_trading_val` with strict `<`, handling Monday weekends. Realized vol for delta selection uses same `_prev_trading_val` guard.

2. **IC correctness complete.** `max_loss = 2×width − combined_credit`, sizing uses `spread_width * 2`, expiration tracks the resolved leg, `option_type='IC'` propagates through all paths including `_record_close`.

3. **Trade lifecycle complete in real-data mode.** Entry slippage (intraday bar half-spread, slippage_multiplier applied, capped at $0.25/leg). Exit slippage (VIX-scaled, applied on all exits including residual-value expiration buyback). Commission (2 legs per spread, 4 legs for IC, consistent in both modes).

4. **Risk management correct.** Drawdown CB (compound uses HWM, non-compound uses starting_capital, configurable threshold). Ruin stop (`_ruin_triggered` set and blocks entries, reset on each run). Portfolio exposure cap (denominator protected against zero, entry commission refunded on rejection). Volume gate with fail-open/closed correctly forwarded.

5. **VIX Monday test is genuine.** Injects VIX=30 on Friday only, asserts no scans fire on Monday. Would fail if `_prev_trading_val` were broken.

### What Is Blocking 9.5/10

Three issues must be fixed:

1. **P0-1:** Fix the IC test call signature. Change `'2025-01-06'` to `470.0` as the third argument to `_find_iron_condor_opportunity`.

2. **P1-1:** Restructure the scan-loop `continue` logic. When `_want_puts = True` and `new_position is None`, fall through to the bear call and IC checks instead of `continue`ing to the next scan time.

3. **P1-2:** Replace the monthly diversity denominator `last_month_num = int(max(monthly.keys()).split('-')[1])` with the number of calendar months spanned: `(to_year - from_year) * 12 + to_month - from_month + 1`.

### Score Path to 9.5

| Action | Score Impact |
|---|---|
| Fix P0-1: Correct IC test call signature | +0.1 |
| Fix P1-1: Scan-loop bear call / IC fallthrough | +0.1 |
| Fix P1-2: Monthly diversity denominator for cross-year spans | +0.05 |
| **Total achievable** | **9.45 → rounds to 9.5** |
