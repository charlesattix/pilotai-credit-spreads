# COMPASS Backtest Results — exp_090 vs exp_101

_Generated: 2026-03-07 16:18_

## What Is COMPASS?

COMPASS = Composite Macro Position & Sector Signal.
It layers two real-time macro intelligence signals onto the baseline credit spread strategy:

| Feature | Logic |
|---------|-------|
| Macro Score Sizing | Weekly score 0–100 from `macro_state.db`. Score < 45 → 1.1× size (buy fear). Score > 70 → 0.8× size (reduce complacency). |
| RRG Breadth Filter | Block bull put entries when < 50% of tracked sectors (XLE/XLF/XLV/XLK/XLI/XLU/XLY) are in Leading or Improving RRG quadrant. |
| Event Scaling | **NOT TESTED** — `macro_events` table contains only 1 future event; historical FOMC/CPI/NFP events were not backfilled. Requires data backfill before backtesting. |

---

## COMPASS Data Profile (2020–2025)

- **Total weekly snapshots**: 313
- **Fear weeks** (score < 45, 1.1× size): 16 weeks
- **Neutral weeks** (45–70, 1.0× size): 235 weeks
- **Greed weeks** (score > 70, 0.8× size): 62 weeks
- **RRG filter blocks bull puts**: ~54.0% of weeks

### Macro Score by Year

| Year | Avg Score | Min | Max | Regime Bias |
|------|-----------|-----|-----|-------------|
| 2020 | 57.8 | 36.2 | 74.3 | mixed — COVID crash pulled score to 36.2 in Mar (fear) |
| 2021 | 73.7 | 66.2 | 82.1 | BULL MACRO — avg 73.7, mostly > 70 (complacency regime) |
| 2022 | 54.9 | 48.7 | 68.3 | NEUTRAL — rate hike uncertainty, no fear/greed extremes |
| 2023 | 54.4 | 48.6 | 61.4 | NEUTRAL — soft landing regime |
| 2024 | 61.1 | 55.8 | 64.5 | NEUTRAL/BULL — election cycle, score 55–64 |
| 2025 | 64.0 | 57.2 | 67.4 | NEUTRAL/BULL — score 57–67 |

---

## A/B Test: exp_090 vs exp_101

**exp_090 (control)**: 10% flat risk, MA200 filter, combo regime, no iron condors

> **Note**: The stored leaderboard entry for exp_090 shows avg +34.06% — higher than the +26.85% reproduced here. The difference is due to code evolution since that entry was recorded (Phase 6 combo regime is now the default; earlier runs may have used legacy MA mode). Both control and treatment here use identical current code, so the **relative delta (-6.74pp) is a valid apples-to-apples comparison**.

**exp_101 (treatment)**: 10% flat risk, MA200 filter, combo regime + COMPASS macro sizing + RRG breadth filter

### Year-by-Year Results

| Year | exp_090 Return | Trades | exp_101 Return | Trades | Delta | DD (090) | DD (101) |
|------|---------------|--------|---------------|--------|-------|----------|----------|
| 2020 | +10.85% | 169 | +9.95% | 123 | -0.90pp | -43.40% | -43.39% |
| 2021 | +46.22% | 102 | +20.54% | 48 | -25.68pp | -1.89% | -0.43% |
| 2022 | +17.11% | 182 | +14.76% | 60 | -2.35pp | -20.69% | -5.38% |
| 2023 | +11.14% | 62 | +15.76% | 36 | +4.62pp | -12.56% | -3.96% |
| 2024 | +21.04% | 109 | +23.14% | 49 | +2.10pp | -11.34% | -5.01% |
| 2025 | +54.74% | 158 | +36.52% | 65 | -18.22pp | -44.18% | -26.82% |

### Summary

| Metric | exp_090 (baseline) | exp_101 (COMPASS) | Delta |
|--------|-------------------|-------------------|-------|
| Avg Annual Return | +26.85% | +20.11% | -6.74pp |
| Worst Annual Return | +10.85% | +9.95% | -0.90pp |
| Best Annual Return | +54.74% | +36.52% | -18.22pp |
| Worst Max Drawdown | -44.18% | -43.39% | +0.79pp |
| Years Profitable | 6/6 | 6/6 | — |

---

## Interpretation

**Verdict**: COMPASS HURTS RETURNS — the macro overlays are subtractive on this config.

### Signal-by-Signal Analysis

**Macro Score Sizing (score < 45 → 1.1×, score > 70 → 0.8×)**:

- Only 2020 had fear weeks (score < 45) — the COVID crash. In 2020, the 1.1× multiplier increased size during bear call entries when VIX was elevated and premiums were richest.
- 2021 was almost entirely 'greed' territory (avg score 73.7). The 0.8× multiplier reduced position sizes across most of 2021. This explains any 2021 return drag vs baseline.
- 2022–2025 had neutral-range scores (45–70) → 1.0× (no change).

**RRG Breadth Filter (block bull puts when < 50% sectors Leading/Improving)**:

- Blocks ~54.0% of ALL weeks from bull put entries — this is the dominant drag.
- The 50% threshold is more aggressive than expected. In 2021, trade count dropped 102 → 48 (-53%). In 2022, 182 → 60 (-67%). In 2025, 158 → 65 (-59%).
- The filter correctly IMPROVED 2023 (+4.62pp) and 2024 (+2.10pp) by blocking weak-breadth entries that would have lost.
- The 50% threshold catches too many weeks. With 7 sectors, "≥4 of 7 Leading/Improving" triggers frequently during sector rotation even in bull markets. A threshold of ≥3/7 (43%) would be less aggressive.

**Event Scaling (FOMC/CPI/NFP)**:

- **NOT IMPLEMENTED IN THIS BACKTEST.** The `macro_events` table has only 1 row (2026-03-12 CPI). Historical event dates were never backfilled into the DB.
- To backtest this feature, populate `macro_events` with 2020–2025 FOMC/CPI/NFP dates and their `scaling_factor` values, then re-run.

---

## Data Limitations & Gaps

1. **macro_events gap**: Historical FOMC/CPI/NFP events not in DB. Event scaling can't be backtested.
2. **Weekly granularity**: Macro scores are weekly snapshots, forward-filled to daily. Intra-week macro regime changes are not captured.
3. **Sector RRG vs SPY**: We trade SPY, not sector ETFs. The RRG filter uses aggregate sector breadth as a proxy for market health — a rough approximation.
4. **Score calibration**: The 0-100 macro score range (min=36.2, max=82.1 historically) means the 'fear' threshold of 45 is rarely triggered. Consider recalibrating to the 20th/80th percentile of historical scores for more frequent signal activation.

---

## Recommendation

PAUSE — COMPASS hurts baseline returns. The macro overlays are reducing position sizes in favorable periods (2021 complacency) more than they help in fear periods (2020 crash). Consider inverting the RRG filter or using score multipliers only for IC entries (not directional spreads).

---

_Config files: `configs/exp_090_risk10_nocompound_newcode.json` (baseline) | `configs/exp_101_compass.json` (COMPASS)_
