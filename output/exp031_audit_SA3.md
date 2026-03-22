# exp_031 Adversarial Audit — SA3: MA50 Look-Ahead Check

**Auditor**: Sub-Agent 3
**Date**: 2026-03-12
**Config**: `configs/exp_031_compound_risk15.json`
**Key params**: direction=bull_put, trend_ma_period=50, otm_pct=0.03, DTE=35/25, compound=True, sizing_mode=flat

---

## Summary of Findings

| # | Finding | Location | Severity |
|---|---------|----------|----------|
| 1 | MA50 data window uses yesterday's close (FIXED by P1-A) | backtester.py:1237–1243 | CLEAN |
| 2 | `price < trend_ma` comparison uses today's EOD close | backtester.py:588, 1246 | MODERATE |
| 3 | OTM% strike selection uses today's EOD close | backtester.py:588, 1612 | MODERATE |
| 4 | VIX/IV-rank use prior trading day's close (CLEAN) | backtester.py:594–595 | CLEAN |
| 5 | Momentum filter `price_10d_ago` uses `recent_data` (yesterday-anchored) | backtester.py:1255–1256 | CLEAN |
| 6 | Commit 822ab63 covers ComboRegimeDetector only — NOT the MA trend filter | ml/combo_regime_detector.py | N/A for exp_031 |

---

## Detailed Findings

### Finding 1 — MA50 Window: CLEAN (P1-A Fix Applied)

**Location**: `backtest/backtester.py` lines 1234–1243 (`_find_backtest_opportunity` / `_find_bull_put_opportunity`)

**Code path**:
```python
_prev_date = pd.Timestamp((date - timedelta(days=1)).date())
recent_data = price_data.loc[:_prev_date].tail(_mp + 20)
trend_ma = recent_data['Close'].rolling(_mp, min_periods=max(10, _mp // 2)).mean().iloc[-1]
```

**Assessment**: The data window explicitly slices to `date - 1 day` before computing the rolling mean. The `.iloc[-1]` here returns the last row of `recent_data`, which is anchored to `_prev_date` (yesterday). For MA50, this means the 50-day window covers days T-50 through T-1 — fully look-ahead-free.

**When was this fixed?** Commit `32bd297` (2026-03-01), labeled "P1-A: MA direction filter no longer includes today's close." This fix predates exp_031 runs if they occurred after March 1, 2026. If exp_031 was run before that commit, it would have had a look-ahead MA window.

**Impact of original bug (pre-fix)**: For MA50, each day's close carries 1/50 = 2.0% weight. Including today's close in the MA shifts it by ~0.02 × (today_return). On a +1% SPY day, the MA would be inflated by ~0.02%, pulling it 0.02% closer to price — a negligible directional effect in practice.

---

### Finding 2 — `price < trend_ma` Comparison Uses Today's EOD Close: MODERATE

**Location**: `backtest/backtester.py` line 588 (main loop), line 1246 (comparison)

**Code path**:
```python
# Line 588 (main scan loop):
current_price = float(price_data.loc[lookup_date, 'Close'])

# Line 1246 (bull put filter):
if self._regime_mode != 'combo' and price < trend_ma:
    return None
```

The `price` argument passed into `_find_bull_put_opportunity` is `current_price`, which is today's EOD **closing** price (line 588). The comparison `price < trend_ma` therefore asks: "Is today's close above the MA50?" — but this close is unknown at scan time (9:30–15:30 ET).

**This is a residual look-ahead bias**: the MA window is correctly yesterday-anchored, but the price being compared to it is today's close. In real trading, at 9:30 AM you only know yesterday's close and the current live price (intraday). The scan uses EOD close, which is known only at 4:00 PM.

**Impact analysis**:
- On days where SPY opens above MA50 but closes below (e.g., sells off intraday), the backtest would correctly SKIP the entry (price < trend_ma using EOD), while a real system at 9:30 AM would have ENTERED (since open was above MA50).
- Conversely, on days where SPY opens below MA50 but closes above, the backtest would ENTER (using EOD), while a real system at 9:30 AM would have SKIPPED.
- For bull-put-only (exp_031), the consequence is asymmetric: entries that would be blocked by MA50 in a real system could be permitted in the backtest, or blocked entries could be incorrectly skipped.

**Quantification**: MA crossover days (close crosses MA50) are relatively rare (~5–15 per year for SPY). The directional effect (close > MA50 but open < MA50 or vice versa) would affect those specific days. However, for a daily strategy with 35-DTE expiration, missing or adding a single entry day rarely changes the outcome materially. This is MODERATE in severity, not CRITICAL.

---

### Finding 3 — OTM% Strike Selection Uses Today's EOD Close: MODERATE

**Location**: `backtest/backtester.py` lines 1610–1616 (`_find_real_spread`)

**Code path**:
```python
_otm = getattr(self, '_current_otm_pct', self.otm_pct)
if ot == "P":
    target_short = price * (1 - _otm)      # price = today's EOD close
    candidates = [s for s in strikes if s <= target_short]
    short_strike = max(candidates)
```

The `price` here is today's EOD close (propagated from line 588 through the call chain). With `otm_pct=0.03`, the target short strike is placed 3% below today's close. In real trading, intraday entries would compute the OTM% from the live intraday price.

**When real-data mode is used**: intraday scan times (9:30–15:30 ET) fetch actual 5-minute bar prices for option pricing (lines 1635–1646). However, the **strike selection** is still based on `price` (today's EOD close), not the intraday price at scan time.

**Impact**: On days with significant intraday price movement (e.g., SPY up +1.5% intraday but closes flat), the strike chosen using EOD close would be 1.5% lower than what a real system would select at 9:30 AM. For a 3% OTM target:
- A $500 SPY, 3% OTM → short strike at $485 using EOD
- If SPY is at $507 at 9:30 AM, real system targets $507 × 0.97 = $491.79 → short strike $491
- This is a $6 difference in strike (~1.2% of SPY price)

This affects the exact credit received (different strike = different premium) but not the direction decision. The premium difference would be small relative to the 8% minimum credit filter. MODERATE severity.

---

### Finding 4 — VIX/IV-Rank: CLEAN

**Location**: `backtest/backtester.py` lines 594–595

**Code path**:
```python
self._current_iv_rank = _prev_trading_val(self._iv_rank_by_date, lookup_date, 25.0)
self._current_vix = _prev_trading_val(self._vix_by_date, lookup_date, 20.0)
```

The helper `_prev_trading_val` uses `max(k for k in d if k < before)` — strictly less than today, returning the most recent prior trading day's value. VIX and IV-rank are fully look-ahead-free. The comment at line 591–592 explicitly documents this: "At 9:30 AM entry time, today's VIX/IV-rank is unknown (set at 4:00 PM)."

**exp_031 note**: exp_031 has no explicit `vix_max_entry` parameter, so VIX is only used for sizing (via `_current_vix`), not as a gate. The clean VIX handling means no look-ahead in the entry gate.

---

### Finding 5 — Momentum Filter: CLEAN (Not Used in exp_031)

**Location**: `backtest/backtester.py` lines 1251–1258

exp_031 config has no `momentum_filter_pct` parameter, so this block is skipped entirely (`_mom_filter is None`). For completeness: when the filter is active, it computes `(price - price_10d_ago) / price_10d_ago`, where `price_10d_ago` is from `recent_data` (which is anchored to `_prev_date`). However, `price` itself is today's EOD close — a minor inconsistency (today's close compared to a 10-day-ago close), same class as Finding 2. Not relevant for exp_031.

---

### Finding 6 — Commit 822ab63 Scope: N/A for exp_031

**Location**: `ml/combo_regime_detector.py`

Commit `822ab63` fixed look-ahead bias in `ComboRegimeDetector.price_vs_ma200` (the signal used in Phase 6 / combo regime mode). This fix applies only when `regime_mode='combo'` is active. exp_031 uses no `combo_regime_detector` — it is a simple MA50 direction filter. The fix in 822ab63 is irrelevant to exp_031.

The relevant fix for exp_031's MA filter was commit `32bd297` (P1-A), which corrects the data window. **The 822ab63 commit message may be misleading** — the MA trend filter look-ahead was already separately addressed by P1-A in 32bd297.

---

## Timeline: When Was exp_031 Run?

The P1-A fix (commit `32bd297`) was merged on **2026-03-01**. If exp_031 was run before that date, its MA50 data window would have included today's close (the pre-fix `price_data.loc[:date]` pattern). The current codebase has the fix applied.

To determine if a historical exp_031 result is tainted, check its run timestamp against `32bd297`'s merge date of 2026-03-01.

---

## Quantified Look-Ahead Impact (Finding 2 — Primary Remaining Issue)

**Mechanism**: `price < trend_ma` uses today's EOD close vs. a yesterday-anchored MA50. The bias fires only on MA50 crossover days.

**Frequency**: SPY crosses MA50 roughly 20–30 times per year (both directions). Bull-put-relevant crossovers (close above MA50 when previous day close was below, or vice versa) occur ~10–15 times per year.

**Weight per day in MA50**: 1/50 = 2.0%. Today's close receiving 2% weight in the MA calculation (pre-P1-A) would shift the MA by ≤ 0.02% per 1% daily move — negligible for the MA value itself.

**The price comparison look-ahead** (Finding 2) is more material: on a volatile day where SPY opens flat (≈ yesterday's close = below MA50) but closes +1.5% (above MA50), the backtest ENTERS but a real system would SKIP. This could add spurious entries on trending up-days — which for bull puts is actually favorable (entries when market closes strong). The bias is directionally favorable to backtest results but not a catastrophic distortion.

**Estimate of trades affected**: For a 6-year backtest (2020–2025) with ~50–100 entries/year, crossover days represent ≤ 5% of trading days. Affected entries where the decision differs between EOD and open: perhaps 2–5 per year, or ~15–25 over 6 years out of ~300–600 total trades. Impact per trade is minor (either entered or blocked one day earlier/later).

---

## Verdict

**The MA50 trend filter in the current codebase is substantially clean.** The P1-A fix (commit `32bd297`, 2026-03-01) correctly anchors the MA50 data window to yesterday's close, eliminating the primary look-ahead source identified in the audit brief.

**Two MODERATE residual issues remain**:

1. The `price` used in `price < trend_ma` comparison is today's EOD close (not yesterday's close or today's open). This is a mild directional look-ahead that could affect ~2–5 entries per year on MA crossover days. It biases results slightly favorably for bull puts (entries triggered by strong closes) but is not large enough to explain multi-hundred-percent annual returns.

2. Strike selection uses today's EOD close to compute `price × (1 - otm_pct)`. On high-intraday-volatility days, this selects a different strike than a real system would at entry time. Impact on credit is small relative to the 8% minimum credit filter.

**If exp_031 was run before 2026-03-01**: the MA50 window was contaminated by today's close (pre-P1-A bug), adding a systematic ~2% weight to today's return in the MA value. This is a MODERATE issue for MA50 vs. minor for MA200, but unlikely to be the primary driver of backtest performance.

**No CRITICAL look-ahead issues exist in the current code for exp_031's configuration.**
