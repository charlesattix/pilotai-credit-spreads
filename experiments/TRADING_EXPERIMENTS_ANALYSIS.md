# Trading Experiments Analysis

**Generated:** 2026-03-06
**Project:** PilotAI Credit Spreads
**Total Experiments Analyzed:** 3,800+ optimization runs, 7 annual backtests, 60+ robustness tests, 12+ walk-forward folds
**Data Sources:** All files in `output/`, `configs/`, `tasks/`, `scripts/`, log files, and git history

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Victory Conditions & Progress](#2-victory-conditions--progress)
3. [Strategy Evolution Timeline](#3-strategy-evolution-timeline)
4. [Production Backtest Results (Real Polygon Data)](#4-production-backtest-results-real-polygon-data)
5. [Optimization Campaigns](#5-optimization-campaigns)
6. [Robustness Testing (Jitter Analysis)](#6-robustness-testing-jitter-analysis)
7. [Walk-Forward Validation](#7-walk-forward-validation)
8. [Champion vs Secondary Configuration](#8-champion-vs-secondary-configuration)
9. [Strategy-Level Analysis](#9-strategy-level-analysis)
10. [Paper Trading Results](#10-paper-trading-results)
11. [What Worked vs What Failed](#11-what-worked-vs-what-failed)
12. [Key Insights & Patterns](#12-key-insights--patterns)
13. [Critical Gaps & Risks](#13-critical-gaps--risks)
14. [File Reference](#14-file-reference)

---

## 1. Executive Summary

This project has executed **3,800+ optimization runs** across 7 strategy types on SPY/QQQ/IWM using real Polygon options data from 2020-2025. The optimization pipeline has 4 stages: (1) parameter search, (2) jitter robustness testing, (3) walk-forward out-of-sample validation, and (4) paper trading.

**Current Status:** Stage 4 (Paper Trading) started 2026-03-05 with the champion configuration.

**Key Finding:** There is a significant **reality gap** between simulated and real-data performance:
- Best simulated config: **26.87%/yr** average return
- Best real-data config: **4.62%/yr** average return
- Champion (walk-forward validated): **12.6%/yr** in-sample, **9.48%/yr** out-of-sample

The victory condition of 40-80% annual returns has **not been met** in walk-forward validated testing. The best validated OOS result is 9.48%/yr with -10.4% max drawdown.

---

## 2. Victory Conditions & Progress

### MASTERPLAN Targets

| Metric | Target | Min Acceptable | Champion Result | Status |
|--------|--------|----------------|-----------------|--------|
| Annual Return | 40-80% | 25% | 9.48% OOS | MISS |
| Max Drawdown | ≤15% | ≤20% | -10.4% | PASS |
| Win Rate | 65-80% | 60% | 71.4% | PASS |
| Sharpe Ratio | 1.5-2.5 | 1.0 | 0.76 | MISS |
| Profit Factor | 1.5-2.5 | 1.3 | 1.50 | PASS |
| Trades/Year | 100-300 | 50 | 93 | PASS |
| WF Decay | ≤30% | ≤50% | 36.9% | PARTIAL |
| Multi-Ticker | SPY+QQQ+IWM | ≥2 of 3 | All 3 | PASS |
| Paper Trade | 8+ weeks | 4 weeks | 1 day | IN PROGRESS |

**Scorecard: 5 PASS / 2 MISS / 1 PARTIAL / 1 IN PROGRESS**

The system meets drawdown, win rate, profit factor, trade count, and multi-ticker requirements. It falls short on annual return and Sharpe ratio targets. Walk-forward decay is borderline at 36.9% (target ≤30%, acceptable ≤50%).

---

## 3. Strategy Evolution Timeline

### Key Milestones (from git history and task logs)

| Date | Event | Impact |
|------|-------|--------|
| 2026-02-15 | PnL capped at theoretical bounds, max 10 contracts | Fixed runaway position sizing |
| 2026-02-21 | Stop-loss multiplier cap fixed | Stop losses now actually fire |
| 2026-02-26 | BS heuristic fallbacks eliminated | All pricing from real Polygon data |
| 2026-02-27 | Data audit completed | Confirmed OHLCV complete, options cache blocked without API key |
| 2026-02-28 | 100-run real-data optimizer | 7/100 met victory conditions |
| 2026-03-01 | Multi-strategy optimizer launched | Validated 535-trade config at 72.22% return |
| 2026-03-02 | "Unlock returns" breakthrough | 5 structural fixes claimed 155%/yr (unvalidated) |
| 2026-03-05 | 500-run optimizer completed | 34/500 met victory conditions |
| 2026-03-05 | Champion selected, paper trading launched | Stage 4 begins |
| 2026-03-06 | Test suite overhaul | 773 tests, 0 failures |

### The "155% Breakthrough" (2026-03-02)

Commit `7863d90` made 5 structural changes:

1. **Gap threshold**: 0.5% -> 2% (reduced gap-stop hemorrhaging)
2. **Concurrent positions**: Allowed 3 per ticker+strategy (laddering)
3. **Risk caps relaxed**: Removed hard contract caps, max_positions -> 20, max_portfolio_risk_pct -> 60%
4. **Daily scanning**: Enabled for credit_spread, iron_condor, calendar_spread
5. **Optimizer scoring**: Fixed divisor 200 -> 50 for meaningful gradient

**Result:** 38 ROBUST configs found in optimizer, best at 155%/yr.

**WARNING:** This result is **in-sample only** and has NOT been walk-forward validated. The actual champion config (12.6%/yr) was selected AFTER walk-forward testing showed the 155%/yr configs failed OOS.

---

## 4. Production Backtest Results (Real Polygon Data)

### Per-Year Results (Champion Config: OTM=3%, Width=$5, SL=2.5x, 2% risk, max 5 contracts)

| Year | Trades | Win Rate | Total PnL | Return | Max DD | Sharpe | Weekly Win % |
|------|--------|----------|-----------|--------|--------|--------|--------------|
| 2020 | 140 | 77.9% | +$27,715 | +27.5% | -26.3% | 0.69 | 75.0% |
| 2021 | 104 | 71.2% | -$5,290 | -5.4% | -20.2% | 0.04 | 62.5% |
| 2022 | 297 | 89.6% | +$54,058 | +53.7% | -12.2% | 1.15 | 87.2% |
| 2023 | 35 | 68.6% | -$8,001 | -8.1% | -11.9% | -0.69 | 50.0% |
| 2024 | 128 | 86.7% | +$4,557 | +4.4% | -13.0% | 0.30 | 82.4% |
| 2025 | 217 | 94.9% | +$15,395 | +15.1% | -2.3% | 2.27 | 91.9% |
| 2026 YTD | 45 | 95.6% | +$2,310 | +2.3% | -1.6% | 1.15 | 87.5% |

### Key Observations

- **Best year:** 2022 (+53.7%) — bear market with elevated VIX, 297 trades, 89.6% win rate
- **Worst year:** 2023 (-8.1%) — only 35 trades, low activity killed returns
- **2021 also negative:** -5.4% with only 104 trades, all bear call direction
- **2025 breakthrough:** 94.9% win rate, -2.3% max DD, Sharpe 2.27 (best risk-adjusted year)
- **Avg win/loss ratio:** ~0.3-0.5x (offset by 75-95% win rates)
- **Direction bias:** 2020-2023 heavily bear call; 2024+ more balanced or bull put dominant

### Alternative Production Backtest (PERFORMANCE_REPORT.md Config)

A separate backtest with slightly different parameters showed higher returns:

| Year | Return | Max DD | Sharpe | Trades |
|------|--------|--------|--------|--------|
| 2020 | +66.3% | -24.5% | 1.17 | 216 |
| 2021 | +29.4% | -25.9% | 0.64 | 89 |
| 2022 | +111.3% | -25.5% | 1.27 | 263 |
| 2023 | +33.5% | -20.5% | 0.78 | 118 |
| 2024 | +23.9% | -29.1% | 0.62 | 154 |
| 2025 | +54.6% | -18.4% | 1.07 | 243 |
| 2026 YTD | +6.6% | -5.7% | 0.04 | 33 |

**Cumulative:** +$326,501 (+326.5%) over 6 years on $100K. However, drawdowns of 24-29% exceed the 20% target, and this config was not walk-forward validated.

---

## 5. Optimization Campaigns

### 5.1 Campaign Summary

| Campaign | Runs | Victory Configs | Best Return | Best DD | Output File |
|----------|------|-----------------|-------------|---------|-------------|
| Real Data (100-run) | 100 | 7 (7.0%) | 9.34%/yr | -40.4% | leaderboard_realdata.json |
| Conservative (500-run) | 500 | 34 (6.8%) | 26.87%/yr | -16.3% | leaderboard.json |
| Aggressive (500-run) | 500 | 38 (7.6%) | 28.51%/yr | -23.2% | leaderboard_aggressive.json |
| Real Data (700-run) | 700 | ~35 (5.0%) | 4.62%/yr | -15.3% | real_data_leaderboard.json |
| Total | 2,100+ | — | — | — | optimization_log.json |

### 5.2 Conservative Top 10 (from top10_configs.json)

| Rank | Run ID | Strategies | Avg Return | Worst DD | Trades/yr | Years Prof | Consistency |
|------|--------|-----------|------------|----------|-----------|------------|-------------|
| 1 | 8264 | straddle, gamma, credit, iron | 26.87% | -16.25% | 107 | 5/6 | 0.833 |
| 2 | faa0 | (multi-strategy) | 22.10% | -12.06% | 48 | 5/6 | 0.833 |
| 3 | 3246 | momentum, calendar, iron, gamma, credit, debit | 21.83% | -8.93% | 101 | **6/6** | **1.000** |
| 4 | 019f | credit, gamma, debit, straddle, momentum, iron | 18.20% | -16.31% | 80 | **6/6** | **1.000** |
| 5 | 2ffa | iron, momentum, gamma, credit, calendar | 17.87% | -17.33% | 60 | 5/6 | 0.833 |
| 6 | d3ba | credit, iron, momentum, calendar, straddle, gamma, debit | 16.48% | -16.86% | 103 | 5/6 | 0.833 |
| 7 | ae02 | debit, gamma, credit, iron | 14.37% | -10.72% | 79 | 4/6 | 0.667 |
| 8 | b956 | iron, debit, credit, straddle | 13.87% | -19.01% | 101 | **6/6** | **1.000** |
| 9 | 5a2b | calendar, credit, iron, debit | 12.94% | -13.75% | 90 | 5/6 | 0.833 |
| 10 | ae5c | credit, iron, momentum, debit | 12.60% | -10.40% | 93 | **6/6** | **1.000** |

**Key Pattern:** The highest-return configs (26.87%) are NOT the most consistent. The most reliable configs (6/6 years profitable) return 12-22%/yr. Config #3 is the best risk-adjusted with 21.83%/yr and only -8.93% DD.

### 5.3 Aggressive Top 10 (from aggressive_top10_configs.json)

| Rank | Run ID | Avg Return | Worst DD | Trades/yr | Years Prof | Consistency |
|------|--------|------------|----------|-----------|------------|-------------|
| 1 | 86b7 | 28.51% | -23.24% | 122 | **6/6** | **1.000** |
| 2 | 5ee6 | 21.15% | -21.51% | 236 | 4/6 | 0.667 |
| 3 | 1dab | 21.13% | -15.78% | 106 | 4/6 | 0.667 |
| 4 | 906c | 21.06% | -7.17% | 70 | 5/6 | 0.833 |
| 5 | 3938 | 20.53% | -10.08% | 72 | **6/6** | **1.000** |
| 6-10 | ... | 18.5-20.1% | -7 to -17% | 70-130 | 4-6/6 | 0.67-1.0 |

### 5.4 Scoring Formulas

**Conservative Optimizer:**
```
score = (avg_return/50) * (15/max_dd) * consistency
```
Targets: 50%/yr return (aspirational), -15% max DD, 100% year profitability.

**Aggressive Optimizer:**
```
score = (avg_return/40) * (25/max_dd) * consistency
```
Allows: -25% max DD (vs -15%), targets 40%/yr (vs 50%).

### 5.5 Real Data vs Simulated Performance Gap

| Metric | Simulated Best | Real Data Best | Gap |
|--------|---------------|----------------|-----|
| Avg Return | 26.87%/yr | 4.62%/yr | **-83%** |
| Worst DD | -16.25% | -15.31% | Similar |
| Consistency | 0.833 | 1.000 | Real data more consistent |
| Trades/yr | 107 | 88 | Similar |

The **83% performance gap** between simulated and real data is the project's biggest challenge. This suggests the optimizer is partially fitting to artifacts in the simulated backtester that don't exist with real Polygon pricing.

---

## 6. Robustness Testing (Jitter Analysis)

### 6.1 Methodology

- **Variants per config:** 25
- **Noise level:** ±15% on all numeric parameters
- **Bool flip probability:** 15%
- **Tickers tested:** SPY, QQQ, IWM
- **Scoring:** `robustness = (stability*0.5) + (profitable_pct*0.3) + ((1-cliffs/N)*0.2)`

### 6.2 Conservative Jitter Results (jitter_top10_results.json)

| Rank | Run ID | Base Return | Jitter Mean | Stability | Profitable % | Cliffs | Robustness | Verdict |
|------|--------|-------------|-------------|-----------|--------------|--------|------------|---------|
| 1 | 8264 | 26.87% | 17.37% | 0.647 | 84% | 2 | 0.755 | FRAGILE |
| 2 | faa0 | 22.10% | 14.22% | 0.643 | 80% | 3 | 0.739 | FRAGILE |
| 3 | 3246 | 21.83% | 13.81% | 0.633 | 80% | 2 | 0.729 | FRAGILE |
| 7 | ae02 | 14.37% | 11.22% | 0.781 | 88% | 1 | 0.809 | FRAGILE |
| 10 | ae5c | 12.60% | 8.97% | 0.712 | 84% | 1 | 0.772 | FRAGILE |

**Key Finding:** ALL top 10 configs received "FRAGILE" verdicts from jitter testing, meaning none achieve the 0.70 stability threshold robustly. However, the configs with lower base returns (12-14%) tend to have HIGHER stability ratios (0.71-0.78), confirming the principle that **robust > optimal**.

### 6.3 Aggressive Jitter Results (aggressive_jitter_results.json)

| Jitter Rank | Run ID | Base Return | Jitter Mean | Stability | Robustness |
|-------------|--------|-------------|-------------|-----------|------------|
| 1 | 2356 | 18.47% | 15.29% | 0.828 | **0.886** |
| 2 | 906c | 21.06% | 16.71% | 0.793 | **0.838** |
| 3 | 3938 | 20.53% | 12.99% | 0.633 | 0.769 |
| 4 | ed08 | 18.71% | 11.85% | 0.633 | 0.728 |

The aggressive configs actually show BETTER jitter stability than conservative ones. Config `2356` (18.47% base, 0.886 robustness) is the most parameter-stable config found across all tracks.

---

## 7. Walk-Forward Validation

### 7.1 Methodology

**Expanding Window (3 folds):**
- Fold 1: Train 2020-2022, Test 2023
- Fold 2: Train 2020-2023, Test 2024
- Fold 3: Train 2020-2024, Test 2025

**Per fold:** 20 optimizer experiments on training data only. Best params evaluated on test year.

**Victory:** WF ratio ≥ 0.70 AND avg OOS return ≥ 6.67%.

### 7.2 Conservative Walk-Forward Results (wf_top4_results.json)

| Jitter Rank | Run ID | Base Return | WF Ratio | Avg OOS Return | Folds Profitable | Verdict |
|-------------|--------|-------------|----------|----------------|------------------|---------|
| **1** | **ae02** | **14.37%** | **0.631** | **+9.48%** | **3/3** | **CHAMPION** |
| **2** | **ae5c** | **12.60%** | **0.631** | **+9.48%** | **3/3** | **SELECTED** |
| 3 | 8264 | 26.87% | 0.329 | +13.42% | 2/3 | 2024 failed (-19%) |
| 5 | faa0 | 22.10% | -0.169 | -5.92% | 1/3 | FAILED |

**Champion Fold Details (ae5c):**

| Fold | Train Period | Test Year | Train Return | OOS Return | OOS DD |
|------|-------------|-----------|-------------|------------|--------|
| 1 | 2020-2022 | 2023 | ~15% | +4.6% | -7.3% |
| 2 | 2020-2023 | 2024 | ~15% | +4.5% | -7.0% |
| 3 | 2020-2024 | 2025 | ~15% | +19.3% | -6.7% |

**Critical Insight:** The high-return configs (26.87%, 22.10%) FAILED walk-forward. Config #1 (26.87%) had a catastrophic -19% in the 2024 fold. Config #5 (22.10%) went negative overall. The moderate-return configs (12.60%, 14.37%) survived all 3 folds, validating the "robust > optimal" principle.

### 7.3 Aggressive Walk-Forward Results (aggressive_wf_results.json)

| Jitter Rank | Run ID | Base Return | WF Ratio | Avg OOS Return | Folds Profitable |
|-------------|--------|-------------|----------|----------------|------------------|
| 1 | 2356 | 18.47% | 0.221 | +6.26% | 1/3 |
| 2 | 906c | 21.06% | 0.025 | +0.78% | 1/3 |
| 3 | 3938 | 20.53% | 0.196 | +5.43% | 2/3 |
| 4 | ed08 | 18.71% | 0.002 | +0.05% | 2/3 |

**All aggressive configs failed walk-forward validation.** The best (2356) only achieved a 0.221 WF ratio (target: ≥0.70) and was profitable in only 1 of 3 folds. This confirms that the aggressive parameter space is more prone to overfitting.

---

## 8. Champion vs Secondary Configuration

### 8.1 Side-by-Side Comparison

| Metric | Champion (ae5c) | Secondary (8264) |
|--------|-----------------|------------------|
| **Strategies** | credit, iron, momentum, debit | straddle, gamma, credit, iron |
| **Base Return** | 12.60%/yr | 26.87%/yr |
| **Worst DD** | -10.40% | -16.25% |
| **Consistency** | 6/6 years (1.000) | 5/6 years (0.833) |
| **Jitter Stability** | 0.712 | 0.647 |
| **Robustness Score** | 0.772 | 0.755 |
| **WF Ratio** | 0.631 | 0.329 |
| **WF OOS Return** | +9.48%/yr | +13.42%/yr |
| **WF Folds OK** | **3/3** | 2/3 |

### 8.2 Champion Strategy Parameters

```json
{
  "credit_spread": {
    "direction": "bull_put",
    "trend_ma_period": 80,
    "target_dte": 15,
    "min_dte": 15,
    "otm_pct": 0.02,
    "spread_width": 12.0,
    "profit_target_pct": 0.55,
    "stop_loss_multiplier": 1.25,
    "momentum_filter_pct": 2.0,
    "scan_weekday": "any",
    "max_risk_pct": 0.085
  },
  "iron_condor": {
    "rsi_min": 35,
    "rsi_max": 60,
    "min_iv_rank": 45.0,
    "target_dte": 30,
    "min_dte": 20,
    "spread_width": 12.0,
    "profit_target_pct": 0.3,
    "stop_loss_multiplier": 2.5,
    "max_risk_pct": 0.035
  },
  "momentum_swing": {
    "mode": "itm_debit_spread",
    "ema_fast": 9,
    "ema_slow": 34,
    "min_adx": 28.0,
    "profit_target_pct": 0.13,
    "max_risk_pct": 0.07
  },
  "debit_spread": {
    "direction": "trend_following",
    "trend_ma_period": 34,
    "target_dte": 12,
    "spread_width": 3.0,
    "profit_target_pct": 1.2,
    "stop_loss_pct": 0.35,
    "max_risk_pct": 0.04
  }
}
```

### 8.3 Secondary Strategy Parameters

```json
{
  "straddle_strangle": {
    "mode": "short_post_event",
    "days_before_event": 2,
    "target_dte": 2,
    "iv_crush_pct": 0.5,
    "profit_target_pct": 0.25,
    "stop_loss_pct": 0.7,
    "max_risk_pct": 0.045
  },
  "gamma_lotto": {
    "days_before_event": 3,
    "price_range": "$0.10-$0.30",
    "otm_range": "3-10%",
    "max_risk_pct": 0.001,
    "profit_target_multiple": 3.5,
    "event_types": "fomc_only"
  },
  "credit_spread": {
    "direction": "bull_put",
    "trend_ma_period": 100,
    "target_dte": 25,
    "otm_pct": 0.06,
    "spread_width": 19.0,
    "stop_loss_multiplier": 1.75,
    "max_risk_pct": 0.09
  },
  "iron_condor": {
    "rsi_min": 25,
    "rsi_max": 65,
    "min_iv_rank": 35.0,
    "target_dte": 25,
    "spread_width": 9.0,
    "stop_loss_multiplier": 2.0,
    "max_risk_pct": 0.045
  }
}
```

### 8.4 Why Champion Was Selected Over Secondary

1. **Walk-forward:** 3/3 folds profitable vs 2/3 (2024 fold failed at -19%)
2. **Consistency:** 6/6 years profitable vs 5/6
3. **Jitter stability:** 0.712 vs 0.647
4. **Drawdown:** -10.4% vs -16.25%
5. **Strategy risk:** Champion uses proven strategies (credit spreads + iron condors). Secondary relies on event-driven straddle/gamma plays with higher tail risk.

---

## 9. Strategy-Level Analysis

### 9.1 Performance by Strategy (from validation_report.md, 535 trades)

| Strategy | Trades | Win Rate | Total PnL | Avg PnL | Best Trade | Worst Trade |
|----------|--------|----------|-----------|---------|------------|-------------|
| CreditSpreadStrategy | 302 | **86.8%** | +$44,154 | +$146 | +$1,807 | -$3,543 |
| IronCondorStrategy | 28 | **92.9%** | +$27,327 | **+$976** | +$2,384 | -$3,854 |
| StraddleStrangleStrategy | 44 | 65.9% | +$9,015 | +$205 | +$1,287 | -$2,189 |
| MomentumSwingStrategy | 161 | 40.4% | -$1,853 | -$12 | +$5,652 | -$4,409 |

### 9.2 Strategy Observations

**Credit Spreads (Core - 56% of trades):**
- The backbone of the system with 86.8% win rate
- Consistent but modest per-trade returns ($146 avg)
- Best in elevated IV environments (2022: 53.7% return)
- Direction matters: bull_put outperforms in 2024-2025, bear_call dominated 2020-2022

**Iron Condors (Premium - 5% of trades):**
- Highest win rate (92.9%) and highest avg PnL ($976)
- Only 28 trades — very selective entry criteria (neutral RSI + elevated IV)
- Contributed $27,327 from just 28 trades — best return per trade
- Risk: large max loss ($3,854) when they go wrong

**Straddle/Strangle (Event-Driven - 8% of trades):**
- Moderate win rate (65.9%), decent PnL contribution
- Event-driven (earnings, FOMC) with IV crush targeting
- 44 trades over 6 years = very selective

**Momentum Swing (Directional - 30% of trades):**
- **Net negative** (-$1,853 over 161 trades)
- Only 40.4% win rate — below breakeven for the loss ratios
- Had both the biggest winner ($5,652) and biggest loser ($4,409)
- Functions as a diversifier but detracts from total returns
- **Candidate for removal or significant parameter tightening**

### 9.3 Strategy Parameter Ranges Explored

| Parameter | Credit Spread | Iron Condor | Straddle | Gamma Lotto |
|-----------|--------------|-------------|----------|-------------|
| Direction | both/bull/bear | N/A | short_post_event | both |
| Target DTE | 14-60 | 21-35 | 2-5 | 1-3 |
| OTM % | 0.02-0.08 | 0.03-0.08 | 0.01-0.05 | 0.03-0.10 |
| Spread Width | $2-$20 | $6-$14 | N/A | N/A |
| Profit Target | 0.25-0.80 | 0.25-0.55 | 0.15-0.40 | 2.5-5.0x |
| Stop Loss | 1.0-3.0x | 1.75-3.5x | 0.35-0.70 | N/A |
| Max Risk | 0.5-10% | 2.5-5% | 2-5% | 0.05-0.1% |

### 9.4 Phase 1 Individual Strategy Scores

From optimizer Phase 1 (single-strategy exploration):

| Strategy | Best Score | Best Return | Note |
|----------|-----------|-------------|------|
| Debit Spread | 0.893 | 110.4% | SUSPECT — likely overfit |
| Credit Spread | 0.163 | 4.9% | Most robust individually |
| Straddle/Strangle | 0.121 | 12.9% | Decent standalone |
| Iron Condor | 0.075 | 8.2% | Moderate standalone |
| Momentum Swing | 0.001 | Variable | Mostly overfit |
| Gamma Lotto | 0.000 | Negative | Cannot stand alone |
| Calendar Spread | 0.000 | Negative | Cannot stand alone |

**Key Insight:** Strategies that fail individually (gamma lotto, calendar) still contribute when blended, because they fire in different market regimes.

---

## 10. Paper Trading Results

### 10.1 Setup (Completed 2026-03-05)

- **Broker:** Alpaca paper account ($9,429 cash)
- **Config:** Champion parameters (credit_spread, iron_condor, momentum_swing, debit_spread)
- **Data:** Live Polygon feed for signal generation
- **Schedule:** 14 scans/day on market hours (PID 69663)
- **Reports:** Daily P&L at 4:15 PM ET

### 10.2 Results (2 Trading Days)

| Metric | Value |
|--------|-------|
| Positions Opened | 42 |
| Closed (Stop-Loss) | 2 |
| Realized PnL | -$2,793.60 |
| Still Open | 6 positions |
| Stale Orders | 34 ($0 PnL — system artifact) |

**Closed Trades:**
1. QQQ bear call (Feb 24): -$1,407.20 (stop-loss)
2. QQQ bear call (Feb 24): -$1,386.40 (stop-loss)

**Open Positions:** 6 bull put spreads on SPY/QQQ, March 31 expiry, $0.87-$1.20 credits, 4 contracts each.

**Assessment:** Too early for conclusions — need 30+ closed trades for statistical significance. The 34 stale orders indicate a system issue that needs debugging.

### 10.3 Paper Trading Success Criteria

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Duration | 8+ weeks | 1 day | IN PROGRESS |
| Win Rate | ≥55% | 0% (2 losses) | TOO EARLY |
| Max DD | ≤25% of account | -29.6% | CONCERNING |
| Avg Fill Deviation | ≤30% of backtest | Unknown | NOT MEASURED |
| Consecutive Losing Weeks | ≤3 | N/A | TOO EARLY |

---

## 11. What Worked vs What Failed

### What Worked

1. **Credit spreads in elevated IV (2022, 2025):** 53.7% and 15.1% returns with 89-95% win rates. High IV = rich premiums, and the trend filter kept direction correct.

2. **Iron condors in range-bound markets:** 92.9% win rate, $976 avg PnL. The RSI range filter (35-60) effectively identifies neutral environments.

3. **Walk-forward validation as overfitting detector:** The highest in-sample return (26.87%) failed OOS with a -19% fold. Only moderate-return configs (12-15%) survived.

4. **Jitter testing for parameter stability:** Clearly separated fragile vs robust configs. Higher-return configs consistently had lower stability ratios.

5. **Multi-strategy blending:** All top configs use 3-6 strategies. No single strategy consistently exceeds 10%/yr alone, but combinations reach 12-27%.

6. **Tight stop-losses (1.25x):** The champion uses 1.25x credit for credit spreads, much tighter than the traditional 2.0-2.5x. This caps losses early.

7. **Daily scanning (vs weekly):** After the March 2 unlock, daily scanning significantly increased trade count and returns.

### What Failed

1. **High-return configs (>20%/yr):** Every config with >20% in-sample return either failed walk-forward or had poor jitter stability. The "155%/yr breakthrough" remains unvalidated.

2. **Momentum swing as standalone:** 40.4% win rate, net negative PnL. Adds noise rather than alpha when not paired with high-conviction strategies.

3. **Calendar spreads:** Consistently negative in single-strategy testing. Only marginally useful in blends.

4. **Gamma lotto standalone:** Zero score in Phase 1 testing. Only works as a tiny allocation within a diversified blend.

5. **Aggressive optimizer targets:** All 4 walk-forward validated aggressive configs failed the 0.70 WF ratio threshold. Aggressive parameter spaces overfit more.

6. **2021 and 2023 performance:** Low-IV, trending markets produced negative returns (-5.4% and -8.1%). The system struggles when VIX is compressed and trends are strong.

7. **Real data vs simulated gap (83%):** The optimizer finds configs that score well on simulated data but drastically underperform with real Polygon pricing. This is the single biggest challenge.

---

## 12. Key Insights & Patterns

### 12.1 The Robust-vs-Optimal Tradeoff

```
In-sample performance and out-of-sample performance are inversely correlated
above a threshold.

    In-Sample Return    OOS Return    WF Ratio    Verdict
    26.87%              13.42%        0.329       FAILED (1 fold crashed)
    22.10%              -5.92%        -0.169      FAILED
    14.37%              9.48%         0.631       CHAMPION
    12.60%              9.48%         0.631       CHAMPION (selected)
```

Configs that score 12-15% in-sample survive OOS testing. Configs above 20% overfit to training data artifacts.

### 12.2 Market Regime Sensitivity

| VIX Environment | Best Strategy | Typical Return | Risk |
|-----------------|---------------|----------------|------|
| High (>30) | Credit spreads | 50-110%/yr | Gap risk |
| Moderate (20-30) | Iron condors + Credit | 15-30%/yr | Balanced |
| Low (<20) | Momentum swing | -5 to +5%/yr | Trend whipsaws |
| Crash (>40) | Credit spreads (short-term) | Extreme gains | Extreme DD |

### 12.3 Trade Frequency Sweet Spot

| Trades/Year | Avg Return | Observation |
|-------------|------------|-------------|
| <50 | 2-5% | Too few opportunities captured |
| 50-100 | 10-20% | Sweet spot for risk-adjusted returns |
| 100-150 | 15-25% | Good with proper diversification |
| >200 | 4-15% | Diminishing returns, higher churn |

### 12.4 Spread Width Impact

| Spread Width | Effect |
|-------------|--------|
| $3-5 | Low credit, high win rate, many trades needed |
| $10-12 | Balanced credit/risk, champion's preferred range |
| $15-19 | High credit per trade, fewer trades needed, larger losses |

### 12.5 Stop-Loss Multiplier Effect

| Multiplier | Win Rate | Avg Loss | Net Effect |
|-----------|----------|----------|------------|
| 1.25x | 75-85% | Small | Best for credit spreads (tight) |
| 2.0x | 80-90% | Medium | Standard for iron condors |
| 2.5x | 85-95% | Large | Traditional but too loose |

Tighter stops (1.25x) produce lower win rates but much better total PnL because they cap the tail risk that destroys accounts.

### 12.6 Key Optimization Patterns

1. **Phase 1 best scores don't predict Phase 2 best combos.** The best individual strategy (debit_spread at 110%) was flagged SUSPECT for overfitting.

2. **Phase 3 (regime-conditional) showed diminishing returns.** The last 10 optimization runs were mostly OVERFIT (8/10), suggesting the search space is exhausted.

3. **The optimizer's scoring formula matters enormously.** Changing the return divisor from 200 to 50 increased the number of "ROBUST" configs from ~5 to 38 in a 500-run campaign.

4. **Consistency > raw return.** Configs with 6/6 years profitable consistently outperform in OOS testing, even when their in-sample returns are lower.

---

## 13. Critical Gaps & Risks

### 13.1 The Reality Gap

The **83% performance gap** between simulated (26.87%) and real-data (4.62%) results suggests:
- The backtester's friction model (slippage, fills) may be too optimistic
- Simulated option chains may not accurately reflect real bid-ask spreads
- The optimizer may be fitting to backtester artifacts rather than real market patterns

### 13.2 Unvalidated "155%/yr" Claim

The March 2 breakthrough relaxed risk caps and enabled daily scanning. While in-sample results improved dramatically, this has NOT been walk-forward tested. Previous experience shows high in-sample results (26.87%) collapse to 13% or less OOS.

### 13.3 Paper Trading Concerns

- Only 2 closed trades after 1 day — both losses (-$2,793.60)
- 34 stale orders suggest a system bug
- Account drawdown already -29.6% of starting capital
- Need 8+ weeks of data before any conclusions

### 13.4 Strategy Concentration Risk

- Credit spreads represent 56% of all trades
- In low-IV environments (2021, 2023), the system generates negative returns
- No regime-detection mechanism to switch strategies based on market conditions

### 13.5 Missing Validation

- No live vs backtest fill comparison analysis
- No tail risk / max loss scenario testing beyond historical data
- No Monte Carlo simulation of equity curves
- Calendar spread and gamma lotto strategies lack individual test coverage

---

## 14. File Reference

### Result Files

| File | Size | Description |
|------|------|-------------|
| `output/leaderboard.json` | 12 MB | 500+ conservative optimization runs |
| `output/leaderboard_aggressive.json` | 12 MB | 500+ aggressive optimization runs |
| `output/leaderboard_realdata.json` | 2.3 MB | 100 real-data optimization runs |
| `output/real_data_leaderboard.json` | ~8 MB | 700 comprehensive real-data runs |
| `output/top10_configs.json` | ~20 KB | Best 10 conservative configs |
| `output/aggressive_top10_configs.json` | 17 KB | Best 10 aggressive configs |
| `output/jitter_top10_results.json` | 23 KB | Jitter robustness (conservative) |
| `output/aggressive_jitter_results.json` | 19 KB | Jitter robustness (aggressive) |
| `output/wf_top4_results.json` | ~30 KB | Walk-forward validation (conservative) |
| `output/aggressive_wf_results.json` | 29 KB | Walk-forward validation (aggressive) |
| `output/optimization_log.json` | 826 KB | 2,100 optimization run logs |
| `output/optimization_state.json` | 375 KB | Optimizer state (resumable) |

### Backtest Results (Per Year, Real Polygon Data)

| File | Year | Return |
|------|------|--------|
| `output/backtest_results_polygon_REAL_2020.json` | 2020 | +27.5% |
| `output/backtest_results_polygon_REAL_2021.json` | 2021 | -5.4% |
| `output/backtest_results_polygon_REAL_2022.json` | 2022 | +53.7% |
| `output/backtest_results_polygon_REAL_2023.json` | 2023 | -8.1% |
| `output/backtest_results_polygon_REAL_2024.json` | 2024 | +4.4% |
| `output/backtest_results_polygon_REAL_2025.json` | 2025 | +15.1% |
| `output/backtest_results_polygon_REAL_2026_ytd.json` | 2026 YTD | +2.3% |

### Reports & Documentation

| File | Description |
|------|-------------|
| `output/PERFORMANCE_REPORT.md` | 26 KB — Multi-year production backtest analysis |
| `output/BACKTEST_METHODOLOGY_REPORT.md` | 28 KB — Technical methodology documentation |
| `output/validation_report.md` | 11 KB — 6-check validation of top config |
| `output/champion_report.html` | 65 KB — Comprehensive champion validation |
| `output/optimizer_500_report.html` | 353 KB — Full 500-run optimizer report |
| `configs/champion.json` | Champion configuration (selected winner) |
| `configs/secondary.json` | Runner-up configuration |
| `tasks/todo.md` | Stage-by-stage project tracker |
| `tasks/lessons.md` | 13 lessons learned |
| `MASTERPLAN.md` | Strategic vision and victory conditions |

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/endless_optimizer.py` | 3-phase autonomous optimization daemon |
| `scripts/run_aggressive_optimizer.py` | 500-run aggressive optimizer |
| `scripts/jitter_top10.py` | Conservative jitter robustness testing |
| `scripts/jitter_aggressive.py` | Aggressive jitter robustness testing |
| `scripts/wf_top4.py` | Conservative walk-forward validation |
| `scripts/wf_aggressive.py` | Aggressive walk-forward validation |
| `scripts/aggressive_top10_extract.py` | Extract top 10 from aggressive leaderboard |
| `scripts/generate_champion_report.py` | HTML champion report generator |

### Log Files

| File | Size | Description |
|------|------|-------------|
| `output/endless_optimizer.log` | 699 KB | Primary optimizer run log |
| `output/optimizer_500run.log` | 661 KB | 500-run campaign log |
| `output/real_data_optimizer.log` | 928 KB | Real-data optimizer log |
| `output/jitter_top10.log` | 68 KB | Jitter test execution log |
| `output/wf_top4.log` | 32 KB | Walk-forward execution log |

---

*Report generated by exhaustive analysis of 3,800+ optimization runs, 7 annual backtests, 60+ robustness tests, and 12+ walk-forward folds across the entire PilotAI Credit Spreads codebase.*
