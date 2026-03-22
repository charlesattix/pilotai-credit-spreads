# EXP_031 Adversarial Audit Report
**Date:** 2026-03-12
**Config:** `configs/exp_031_compound_risk15.json`
**Auditors:** SA1–SA6 (parallel sub-agents)
**Verdict: DO NOT PAPER TRADE**

---

## Config Under Audit

```json
{
  "direction": "bull_put",
  "trend_ma_period": 50,
  "otm_pct": 0.03,
  "target_dte": 35,
  "min_dte": 25,
  "spread_width": 5,
  "min_credit_pct": 8,
  "stop_loss_multiplier": 2.5,
  "profit_target": 50,
  "max_risk_per_trade": 15.0,
  "max_contracts": 35,
  "compound": true,
  "sizing_mode": "flat"
}
```

**Original leaderboard entry:** +63.84% avg (Feb 26, 2026, run_id: `exp_031_compound_risk15`)

---

## Summary Scorecard

| Check | Result | Severity |
|---|---|---|
| SA1: Reproducibility | NOT REPRODUCIBLE | 🔴 CRITICAL |
| SA2: Price verification | VERIFIED CLEAN | ✅ PASS |
| SA3: Look-ahead bias | MODERATE — original run contaminated, current code partially clean | 🟡 MODERATE |
| SA4: Slippage robustness | FAILS AT 2x — strategy goes negative | 🔴 CRITICAL |
| SA5: 2022 / regime integrity | Combo regime disables bear protection in 2022 | 🔴 CRITICAL |
| SA6: DTE robustness | FRAGILE — sharp left cliff, DTE=34 breaks strategy | 🔴 CRITICAL |

**4 of 6 checks are critical failures. The published +63.84% avg is invalid on multiple grounds.**

---

## SA1 — Reproducibility

**Verdict: RED FLAG — NOT REPRODUCIBLE**

### Root Cause: Silent `regime_mode` Default Change

`exp_031_compound_risk15.json` has no `regime_mode` field. When originally run (Feb 26, 2026), the codebase default was the legacy MA50 filter. When Phase 6 ComboRegimeDetector v2 was made mandatory (Mar 8, 2026, commit `b01ac4a`), `run_optimization.py` silently switched the default to `"combo"`. Re-running the identical config today runs a completely different strategy.

### Year-by-Year Divergence

| Year | Original (Feb 26) | Rerun Today | Delta |
|---|---|---|---|
| 2020 | +81.1% (107 trades) | +28.2% (38 trades) | -52.9pp |
| 2021 | +44.8% (44 trades) | +73.8% (102 trades) | +29.0pp |
| 2022 | -20.7% (12 trades) | +9.1% (86 trades) | +29.8pp |
| 2023 | +36.2% (36 trades) | +17.1% (62 trades) | -19.1pp |
| 2024 | +69.7% (119 trades) | +31.3% (109 trades) | -38.5pp |
| 2025 | +171.9% (160 trades) | -26.5% (17 trades) | **-198.4pp** |
| **Avg** | **+63.84%** | **+22.15%** | **-41.7pp** |

Trade counts swing dramatically (12→86 in 2022, 160→17 in 2025) — these are not the same strategy.

### Systemic Impact

**All pre-Mar-8 leaderboard entries without an explicit `regime_mode` field are invalid.** Any future re-run silently uses combo regime and will produce different results. This includes other experiments that share the same pattern.

**Fix required:** Add `"regime_mode": "legacy_ma50"` to configs that were designed for the MA50 filter, or explicitly add `"regime_mode": "combo"` to new configs. Do not rely on defaults.

---

## SA2 — Trade Price Verification

**Verdict: PRICES VERIFIED CLEAN** (with two minor caveats)

12 trades verified against Polygon SQLite cache and direct API calls. All entry and exit prices match cache data exactly (delta < $0.01).

### Verified Clean
- Entry prices: backtester uses daily close for 9:15 pre-market scans, 5-min bar close for market-hours scans — both correct
- Slippage formula: `min(bar_HL/2, $0.25)` per leg implemented correctly for intraday; `$0.05/leg` flat for daily-close entries
- Exit triggers: profit-target and stop-loss exits all supported by Polygon data

### Minor Caveats

1. **2020 COVID slippage underestimated:** Daily-close entries use a flat $0.05/leg even during the crash when real bid-ask spreads were $0.50–$2.00/leg. The slippage stress tests in SA4 capture this properly.

2. **Adjacent-strike fallback bias:** 3/8 verified trades used strikes $0.77–$1.95 above the 97% OTM target (closer-to-money) when the exact target strike had no cache data or failed the credit minimum. Closer-to-money = higher credit collected but higher loss risk. Creates a minor optimistic bias in the backtest.

3. **Bear calls in 2020 despite `direction: "bull_put"`:** The combo regime override adds bear call spreads when the detector signals BEAR. exp_031 is not a pure bull-put strategy under the combo regime — it becomes mixed-direction. This is by design but was not documented in the original exp_031 description.

---

## SA3 — MA50 Look-Ahead Bias

**Verdict: MODERATE — Original run contaminated; current code partially clean**

### Current Code (post Mar 1, 2026 P1-A fix)
- **MA50 window: CLEAN** — `price_data.loc[:_prev_date]` correctly uses T-1 close. The P1-A fix (commit `32bd297`) covers both bull-put and bear-call opportunity finders.
- **VIX/IV-rank: CLEAN** — `_prev_trading_val()` strictly takes `max(k < today)`.

### Residual Issues (still present)
1. **`current_price` comparison uses today's EOD close** (`backtester.py:588, 1246`): The MA is correctly anchored to T-1, but the price compared against it is today's close — not known at 9:30 AM. Affects ~2–5 entry decisions/year on crossover days. Favorable bias for bull puts (strong days enable entry, confirming the close was above MA50).

2. **Strike selection uses today's EOD close** (`backtester.py:1612`): `target_short = price × (1 - otm_pct)` where price is today's close. On high-volatility days this selects a different strike than a real system would (±$3–6 SPY). Effect on credit is small relative to the 8% floor.

### Historical Contamination
The original exp_031 run (Feb 26) predates the P1-A fix (Mar 1). The MA50 look-ahead was active: today's close carried 2.0% weight in the 50-day window (vs 0.5% for MA200). Pre-P1-A results for any MA50 config should be treated as inflated on crossover days.

---

## SA4 — Realistic Slippage Stress Test

**Verdict: CRITICAL FAIL — Strategy collapses under realistic transaction costs**

### Results

| Scenario | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | Avg | Worst DD | Profitable Yrs |
|---|---|---|---|---|---|---|---|---|---|
| Baseline 1x | +28.2% | +73.8% | +9.1% | +17.1% | +31.3% | -26.5% | +22.2% | -46.2% | 5/6 |
| 1.5x (bid-entry proxy) | +11.2% | +44.5% | -5.3% | +3.9% | +8.3% | -29.3% | +5.5% | -51.1% | 4/6 |
| 2x slippage | -18.3% | +20.7% | -27.9% | -7.2% | -11.7% | -26.5% | **-11.8%** | **-68.5%** | 1/6 |
| 3x slippage | -20.6% | -17.3% | -20.2% | -21.4% | -19.4% | -33.9% | -22.1% | -43.5% | 0/6 |

### Comparison to Champion
The MA200 champion (exp_036) retained **+138% avg at 2x slippage**. exp_031 goes to **-11.8%** — negative in 5/6 years. The edge, if any, is entirely consumed by transaction costs at 2x.

### Structural Causes
1. **15% compound risk**: slippage friction compounds with position size
2. **High trade frequency** (~69–100 trades/year): friction accumulates on every entry and exit
3. **Thin 8% credit floor**: premiums have almost no cushion over the minimum, meaning slippage often makes entries that were marginally profitable into losers
4. **2020 COVID period**: daily-close flat $0.05/leg slippage massively underestimates reality ($0.50–$2.00/leg actual spread). The real 2020 returns are likely significantly worse than modeled.

**Bottom line:** A strategy with no edge at 2x slippage should not be paper traded. Real-world execution includes commissions, bid-ask spread, and market impact — 2x is not a stress scenario, it's closer to reality.

---

## SA5 — 2022 Deep Dive

**Verdict: LEGITIMATE filter failure, but combo regime removes 2022 protection entirely**

### Original MA50 Behavior (12 trades, -20.7%): No Bug
The MA50 filter worked correctly. The 12 trades entered during three genuine SPY bounces above MA50:

- **Jan 4-13**: 4 trades (2W/2L), -$6,523 — valid bounce that failed
- **Mar 21 – Apr 11**: 7 trades, -$340 — rally that mostly worked
- **May**: 1 position (opened during Mar-Apr bounce) stopped out at -$13,771 when SPY crashed from $425 to $370

The 20% CB fired after the May loss, halting entries for the remaining 7 months (including the Jul-Aug +20% rally that would have been profitable). The -20.7% is a genuine cost of trading bear-market bounces. Not a bug — this is what the strategy does in a bear year.

### Critical Finding: Combo Regime Disables 2022 Bear Protection

Re-run with combo regime: **86 trades, +9.1% in 2022** — but this is not safer. The combo detector labeled **0 of 251 trading days in 2022 as BEAR** because the `vix_structure` signal requires VIX/VIX3M > 1.05 and the 2022 ratio peaked at only 1.022. The bear gate never fired. The strategy "survived" 2022 only because bull puts happened to win despite no regime filter — not because the combo detector protected it.

This is a **false safety signal**: the combo regime appears to do better in 2022 (+9.1% vs -20.7%) but it did so with 7x the trade count and no bear protection at all. In a worse 2022 scenario (deeper/faster crash), the combo regime would have produced catastrophic losses.

The MA50 filter, despite losing 20.7% in 2022, was actually functioning as intended. The combo regime was not functioning at all.

---

## SA6 — DTE Cliff Investigation

**Verdict: FRAGILE — Sharp left cliff makes DTE=35 a hard constraint**

### DTE Sweep Results (all years, real data)

| DTE (target/min) | Avg Return | Trades/yr | 2022 DD |
|:-:|:-:|:-:|:-:|
| 28/18 | +0.6% | 35 | -48.4% |
| 30/20 | -0.1% | 34 | -44.1% |
| 32/22 | -3.4% | 37 | -39.2% |
| 33/23 | -1.5% | 46 | -37.8% |
| 34/24 | +6.8% | 66 | -28.3% |
| **35/25 (baseline)** | **+22.1%** | **69** | **-20.7%** |
| 36/26 | +14.3% | 63 | -22.1% |
| 38/28 | +19.9% | 72 | -18.9% |
| 40/30 | +16.3% | 78 | -17.4% |

### Root Cause
**Credit filter interaction**: at DTE=28, only 89.5% of puts pass the 8% credit minimum vs 96.4% at DTE=35. This halves trade count (35 vs 69/yr). With compound sizing, fewer trades = dramatically less compounding in winning years (2021: +20.6% at DTE=28 vs +73.8% at DTE=35).

Secondary: shorter DTE = thinner credit cushion relative to the 2.5x stop-loss. Bear-market bounces (2022) become catastrophic at DTE=28 (-48.4%) vs manageable at DTE=35 (-20.7%).

### Fragility Verdict
The left cliff (DTE < 35) is sharp enough that DTE=35 cannot be considered a robust parameter. A single day of fallback — common when the target Friday expiration is unavailable and the system steps back to the next available — drops the strategy from +22% to +6.8% avg. In live trading this fallback happens regularly.

The right shoulder (DTE 36-40) is gentler but introduces slightly higher drawdown. DTE=35 is not a parameter that can be treated as "approximately 35" — it must be exactly 35.

---

## Final Verdict

### DO NOT PAPER TRADE exp_031

**The published +63.84% average annual return is invalid.** It reflects:
1. A strategy (legacy MA50 filter) that no longer matches the current codebase default
2. A look-ahead bias in the MA50 calculation that inflated returns on crossover days
3. An unrealistically optimistic slippage model (flat $0.05/leg vs $0.50–$2.00 during high-VIX periods)

**The corrected numbers under current codebase (+combo regime, no look-ahead) are +22.2% avg** — and that number evaporates entirely at 2x slippage (-11.8%).

### What's Actually Wrong with exp_031

| Issue | Impact |
|---|---|
| Thin premium cushion (8% min_credit) | Slippage consumes most edge; no buffer for real-world friction |
| High trade frequency (69+/yr) | Every execution slip compounds; 15% risk × 69 trades = large friction surface |
| DTE=35 hard dependency | Live fallback to DTE=34 drops avg from +22% to +7% |
| MA50 creates false precision | "Bull when above MA50" sounds robust but produces only 12-86 trades depending on which regime code runs |
| Combo regime disables 2022 protection | 0 BEAR signals in a 20% down year — worse than the MA50 it replaced |

### If exp_031-class strategies are still of interest

The only potentially viable path is:
1. Lock `regime_mode: "legacy_ma50"` in the config (to get back the original behavior)
2. Fix the credit floor: raise `min_credit_pct` from 8% to 12%+ to get premium cushion that survives 2x slippage
3. Reduce `max_risk_per_trade` from 15% to 5-7% to reduce the slippage compounding surface
4. Accept DTE=35 as a hard constraint and verify the live system has robust fallback logic
5. Re-run under these constraints and verify the slippage-2x scenario remains profitable before touching paper capital

The current config is not ready.

---

*Individual section reports: `output/exp031_audit_SA{1,2,3,4,5,6}.md`*
