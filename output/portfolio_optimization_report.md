# Portfolio ML Optimization Report

**Generated:** 2026-03-24  
**Strategies:** 5 champions analyzed  
**Period:** 2020–2025 (6 years)  
**Base capital:** $100,000

## Executive Summary

The **max-Sharpe allocation** recommends concentrating in the highest risk-adjusted strategies while maintaining minimum 5% exposure to all.  Expected blended annual return: **52.0%**, Sharpe: **1.94**.

| Strategy | Weight | Annual Return | Profile |
|----------|--------|---------------|---------|
| EXP-305 | 33.8% | +70.6% | Multi-underlying — COMPASS universe (XLE, XLK, SOXX, XL |
| EXP-400 | 24.5% | +32.7% | Balanced — regime-adaptive CS+IC, very low DD |
| EXP-154 | 24.2% | +31.4% | Conservative — 5% nominal risk, IC overlay in neutral r |
| EXP-520 | 12.5% | +38.0% | VIX-gated — vix_max_entry=35 cuts 2020 crash losses, co |
| EXP-126 | 5.0% | +32.8% | High-return — strong 2022/2025, weaker 2023/2024 |

### Blended Portfolio Performance (Best Allocation)

| Year | SPY S&P | EXP-400 | EXP-126 | EXP-154 | EXP-520 | EXP-305 | **Blended** |
|------|---------|---------|---------|---------|---------|---------|-------------|
| 2020 | +18.4% | +8.9% | +39.0% | +45.5% | +70.9% | +96.5% | **+56.6%** |
| 2021 | +28.7% | +101.4% | +28.8% | +27.6% | +36.1% | +69.7% | **+61.1%** |
| 2022 | -19.6% | -1.9% | +3.4% | +23.0% | +24.1% | +74.0% | **+33.3%** |
| 2023 | +26.3% | +37.5% | +11.0% | +8.4% | +15.3% | +42.9% | **+28.2%** |
| 2024 | +23.1% | +23.8% | +20.8% | +13.4% | +30.5% | +49.9% | **+30.8%** |
| 2025 | +24.9% | +26.5% | +94.0% | +70.5% | +51.0% | +90.6% | **+65.3%** |
| **Avg** | +17.0% | +32.7% | +32.8% | +31.4% | +38.0% | +70.6% | **+45.9%** |

## Strategy Profiles

### EXP-400 Champion (DTE=15, Regime-Adaptive)

- **Source:** Deterministic backtest (leaderboard)
- **Profile:** Balanced — regime-adaptive CS+IC, very low DD
- **6-year avg return:** +32.7% | Std dev: +33.2% | Best: +101.4% (2021) | Worst: -1.9% (2022)
- **Max drawdown (worst year):** -12.1%

| Year | Return | Max DD | Sharpe |
|------|--------|--------|--------|
| 2020 | +8.9% | -10.4% | 0.72 |
| 2021 | +101.4% | -2.9% | 6.62 |
| 2022 | -1.9% | -12.1% | -0.34 |
| 2023 | +37.5% | -3.3% | 3.62 |
| 2024 | +23.8% | -5.5% | 2.74 |
| 2025 | +26.5% | -8.1% | 2.19 |

### EXP-126 8% Flat Risk (DTE=35, IC-Neutral)

- **Source:** MC P50 (30 seeds, DTE U[33,37])
- **Profile:** High-return — strong 2022/2025, weaker 2023/2024
- **6-year avg return:** +32.8% | Std dev: +29.7% | Best: +94.0% (2025) | Worst: +3.4% (2022)
- **Max drawdown (worst year):** -30.9%

| Year | Return | Max DD | Sharpe |
|------|--------|--------|--------|
| 2020 | +39.0% | -30.9% | 1.08 |
| 2021 | +28.8% | -6.2% | 2.67 |
| 2022 | +3.4% | -14.6% | 2.40 |
| 2023 | +11.0% | -10.8% | 0.59 |
| 2024 | +20.8% | -7.9% | 1.01 |
| 2025 | +94.0% | -16.7% | 2.00 |

### EXP-154 5% Dir + 12% IC (IC-Neutral)

- **Source:** MC P50 (200 seeds, DTE U[33,37])
- **Profile:** Conservative — 5% nominal risk, IC overlay in neutral regime
- **6-year avg return:** +31.4% | Std dev: +21.1% | Best: +70.5% (2025) | Worst: +8.4% (2023)
- **Max drawdown (worst year):** -28.1%

| Year | Return | Max DD | Sharpe |
|------|--------|--------|--------|
| 2020 | +45.5% | -28.1% | 1.08 |
| 2021 | +27.6% | -6.2% | 2.00 |
| 2022 | +23.0% | -14.6% | 1.80 |
| 2023 | +8.4% | -10.8% | 0.50 |
| 2024 | +13.4% | -7.9% | 0.90 |
| 2025 | +70.5% | -16.7% | 1.80 |

### EXP-520 Real-Data Champion (VIX Gate, DTE=35/28)

- **Source:** Deterministic backtest (Phase 9, March 2026)
- **Profile:** VIX-gated — vix_max_entry=35 cuts 2020 crash losses, consistent returns
- **6-year avg return:** +38.0% | Std dev: +18.3% | Best: +70.9% (2020) | Worst: +15.3% (2023)
- **Max drawdown (worst year):** -39.4%

| Year | Return | Max DD | Sharpe |
|------|--------|--------|--------|
| 2020 | +70.9% | -14.4% | 2.00 |
| 2021 | +36.1% | -18.0% | 2.00 |
| 2022 | +24.1% | -20.0% | 2.00 |
| 2023 | +15.3% | -15.0% | 1.50 |
| 2024 | +30.5% | -16.0% | 2.00 |
| 2025 | +51.0% | -39.4% | 2.00 |

### EXP-305 COMPASS Multi-Underlying (Top-2, 65%)

- **Source:** Deterministic portfolio backtest (SPY + sector ETFs)
- **Profile:** Multi-underlying — COMPASS universe (XLE, XLK, SOXX, XLF) + SPY
- **6-year avg return:** +70.6% | Std dev: +19.5% | Best: +96.5% (2020) | Worst: +42.9% (2023)
- **Max drawdown (worst year):** -16.7%

| Year | Return | Max DD | Sharpe |
|------|--------|--------|--------|
| 2020 | +96.5% | -16.7% | 2.50 |
| 2021 | +69.7% | -12.0% | 2.20 |
| 2022 | +74.0% | -10.0% | 2.50 |
| 2023 | +42.9% | -12.0% | 2.00 |
| 2024 | +49.9% | -13.0% | 2.00 |
| 2025 | +90.6% | -16.7% | 2.20 |

## Portfolio Optimization: Allocation Weights

Four optimization methods are applied to find the optimal capital allocation.
All methods enforce: long-only, minimum 5% per strategy, weights sum to 100%.

### Method Comparison

| Method | EXP-126 | EXP-154 | EXP-305 | EXP-400 | EXP-520 | Ann. Return | Ann. Vol | Sharpe |
|--------|--------|--------|--------|--------|--------|-------------|----------|--------|
| Max Sharpe | 5.0% | 24.2% | 33.8% | 24.5% | 12.5% | +52.0% | +24.5% | 1.94 |
| Risk Parity | 5.0% | 29.7% | 23.9% | 27.0% | 14.5% | +49.6% | +23.7% | 1.90 |
| Equal Risk Contrib. | 5.0% | 19.5% | 13.5% | 36.3% | 25.7% | +48.8% | +24.6% | 1.80 |
| Min Variance | 5.0% | 33.1% | 24.9% | 25.7% | 11.4% | +49.5% | +23.6% | 1.91 |

### Recommended Allocation: Max Sharpe

**Regime:** NEUTRAL_MACRO  
**Event scaling factor:** 1.00 (1.0 = no events pending)  
**Next rebalance:** 2026-03-31

#### Base weights (pre-event scaling):

- **33.8%** → EXP-305 COMPASS Multi-Underlying (Top-2, 65%)
- **24.5%** → EXP-400 Champion (DTE=15, Regime-Adaptive)
- **24.2%** → EXP-154 5% Dir + 12% IC (IC-Neutral)
- **12.5%** → EXP-520 Real-Data Champion (VIX Gate, DTE=35/28)
- **5.0%** → EXP-126 8% Flat Risk (DTE=35, IC-Neutral)

#### Scaled weights (after event gate):

Total capital deployed: **100.0%**

- **33.8%** → EXP-305
- **24.5%** → EXP-400
- **24.2%** → EXP-154
- **12.5%** → EXP-520
- **5.0%** → EXP-126

## Regime-Adaptive Allocations

COMPASS macro regime (BULL/NEUTRAL/BEAR) shifts weights toward momentum or defensive strategies.

| Regime | EXP-126 | EXP-154 | EXP-305 | EXP-400 | EXP-520 | Expected Return | Sharpe |
|--------|--------|--------|--------|--------|--------|-----------------|--------|
| BULL | 9.3% | 22.7% | 29.5% | 24.1% | 14.5% | +60.0% | 1.32 |
| NEUTRAL | 5.0% | 24.2% | 33.8% | 24.5% | 12.5% | +52.0% | 1.94 |
| BEAR | 9.8% | 23.2% | 29.9% | 22.1% | 15.0% | +61.0% | 1.28 |

> **BULL regime** upweights EXP-305 (COMPASS sectors) and EXP-400 (momentum-affinity=0.6).  
> **BEAR regime** upweights EXP-154 and EXP-154 (defensive, lower risk).  
> **Regime blend parameter:** 30% (30% tilt toward regime affinity, 70% optimizer-driven).

## Cross-Strategy Correlation Matrix

Pearson correlation of simulated monthly returns (72 periods, 2020–2025).  
Note: EXP-400 uses actual monthly PnL data where available; others use simulated monthly returns.

| | EXP-126 | EXP-154 | EXP-305 | EXP-400 | EXP-520 |
|---|---|---|---|---|---|
| EXP-126 | **1.00** | -0.29 | 0.23 | 0.05 | -0.03 |
| EXP-154 | -0.29 | **1.00** | -0.07 | -0.01 | 0.05 |
| EXP-305 | 0.23 | -0.07 | **1.00** | 0.05 | -0.25 |
| EXP-400 | 0.05 | -0.01 | 0.05 | **1.00** | -0.07 |
| EXP-520 | -0.03 | 0.05 | -0.25 | -0.07 | **1.00** |

**Average pairwise correlation:** -0.04

> ✅ LOW correlation — strong diversification benefit across strategies.

### Notable Correlation Pairs

- **EXP-126 ↔ EXP-154:** -0.29 (LOW)
- **EXP-305 ↔ EXP-520:** -0.25 (LOW)
- **EXP-126 ↔ EXP-305:** 0.23 (LOW)
- **EXP-154 ↔ EXP-305:** -0.07 (LOW)
- **EXP-400 ↔ EXP-520:** -0.07 (LOW)
- **EXP-126 ↔ EXP-400:** 0.05 (LOW)
- **EXP-154 ↔ EXP-520:** 0.05 (LOW)
- **EXP-305 ↔ EXP-400:** 0.05 (LOW)
- **EXP-126 ↔ EXP-520:** -0.03 (LOW)
- **EXP-154 ↔ EXP-400:** -0.01 (LOW)

## Realized Crisis Performance (Actual Backtested Returns)

These are the *actual* per-year returns from backtests (or MC P50), not synthetic scenarios.

### COVID Year (2020) — Actual Realized Returns

| Strategy | 2020 Return | 2020 Max DD | Notes |
|----------|-------------|-------------|-------|
| EXP-400 | +8.9% | -10.4% | DTE=15 tactical; light 2020 trading, avoided COVID peak |
| EXP-126 | +39.0% | -30.9% | MC P50 — deterministic was +53%; VIX spikes fire IC circuit breaker |
| EXP-154 | +45.5% | -28.1% | MC P50 — 5% risk cap limits crash exposure; CB protects |
| EXP-520 | +70.9% | -14.4% | VIX gate (vix_max_entry=35) cut DD from -61.6% to -14.4%; still +70.9%! |
| EXP-305 | +96.5% | -16.7% | COMPASS 2020: SOXX+XLK sectors led; tech recovered fastest |
| **COMBINED** | **+56.6%** | **-18.3%** | Blended per best-allocation weights |

### 2022 Bear Market — Actual Realized Returns

| Strategy | 2022 Return | 2022 Max DD | Notes |
|----------|-------------|-------------|-------|
| EXP-400 | -1.9% | -12.1% | ONLY loser in 2022 (-1.9%); DTE=15 caught mid-put assignments |
| EXP-126 | +3.4% | -14.6% | MC P50 +3.4%; deterministic was +79%! Bear calls vs falling SPY |
| EXP-154 | +23.0% | -14.6% | MC P50 +23%; IC-NEUTRAL outperforms — bear year IC misses, prevents big losses |
| EXP-520 | +24.1% | -20.0% | +24.1% despite bear year — VIX gate prevents new entries when VIX>35 |
| EXP-305 | +74.0% | -10.0% | COMPASS correctly allocated to XLE (energy +71.2%); +74% in down market! |
| **COMBINED** | **+33.3%** | **-13.1%** | Blended per best-allocation weights |

> **Key insight:** ALL strategies except EXP-400 were profitable in 2022. The combined portfolio returned +33.3% while SPY fell -19.6%. This is the core value proposition: short-vol credit spreads + sector rotation = crisis alpha.

## Stress Test Results (Synthetic Crisis Scenarios)

Monte Carlo (1,000 paths, block-bootstrap) + 4 synthetic crisis scenarios.  
Note: Crisis scenarios apply a uniform shock path to all strategies (credit spread beta=1.5×).  
For *actual* crisis performance, see 'Realized Crisis Performance' section above.

### Monte Carlo: Terminal Wealth Distribution ($100,000 starting capital)

| Strategy | P5 | P25 | P50 | P75 | P95 | Prob Profit | Prob Ruin | Risk Rating |
|----------|----|-----|-----|-----|-----|-------------|-----------|-------------|
| EXP-400 | $386,805 | $446,154 | $492,350 | $544,621 | $625,000 | 100.0% | 0.0% | MODERATE |
| EXP-126 | $418,403 | $493,128 | $554,165 | $628,474 | $758,755 | 100.0% | 0.0% | MODERATE |
| EXP-154 | $452,621 | $525,360 | $590,583 | $668,182 | $788,825 | 100.0% | 0.0% | MODERATE |
| EXP-520 | $599,739 | $747,607 | $868,283 | $998,017 | $1,247,616 | 100.0% | 0.0% | MODERATE |
| EXP-305 | $2,104,033 | $2,413,940 | $2,664,124 | $2,966,832 | $3,410,648 | 100.0% | 0.0% | MODERATE |
| **COMBINED** | $870,709 | $943,905 | $998,374 | $1,048,354 | $1,136,422 | 100.0% | 0.0% | MODERATE |

### Monte Carlo: Sharpe & Drawdown Distributions

| Strategy | Median Sharpe | P5 Sharpe | Median Max DD | P5 Max DD (worst) |
|----------|---------------|-----------|---------------|-------------------|
| EXP-400 | 5.24 | 4.43 | -3.3% | -5.0% |
| EXP-126 | 4.05 | 3.37 | -4.8% | -7.6% |
| EXP-154 | 4.39 | 3.70 | -4.4% | -6.7% |
| EXP-520 | 4.14 | 3.43 | -5.8% | -8.5% |
| EXP-305 | 9.88 | 9.13 | -1.6% | -2.2% |
| **COMBINED** | 12.87 | 12.11 | -0.6% | -0.9% |

### Historical Crisis Scenario Analysis

Credit spread beta = 1.5× applied (short gamma suffers more than underlying during VIX spikes).

| Scenario | Underlying DD | Portfolio DD (1.5× beta) | Trough Value | Est. Recovery |
|----------|---------------|--------------------------|--------------|---------------|
| COVID Crash (Feb-Mar 2020) | -34.5% | **-51.8%** | $48,216 | 479 days |
| 2022 Bear Market | -29.1% | **-43.7%** | $56,319 | 377 days |
| Flash Crash (Single Day) | -10.0% | **-15.0%** | $85,000 | 107 days |
| VIX Spike (15 → 65) | -15.0% | **-22.5%** | $77,500 | 168 days |

### COVID Crash (Feb-Mar 2020) — Per-Strategy Impact

| Strategy | Est. Portfolio DD | Trough Value | Recovery Days |
|----------|-------------------|--------------|---------------|
| EXP-400 | -51.8% | $48,216 | 689 |
| EXP-126 | -51.8% | $48,216 | 632 |
| EXP-154 | -51.8% | $48,216 | 613 |
| EXP-520 | -51.8% | $48,216 | 506 |
| EXP-305 | -51.8% | $48,216 | 335 |
| **COMBINED** | -51.8% | $48,216 | 479 |

### 2022 Bear Market — Per-Strategy Impact

| Strategy | Est. Portfolio DD | Trough Value |
|----------|-------------------|--------------|
| EXP-400 | -43.7% | $56,319 |
| EXP-126 | -43.7% | $56,319 |
| EXP-154 | -43.7% | $56,319 |
| EXP-520 | -43.7% | $56,319 |
| EXP-305 | -43.7% | $56,319 |
| **COMBINED** | -43.7% | $56,319 |

## Parameter Sensitivity Analysis (Combined Portfolio)

Heuristic model: approximates the effect of parameter changes on combined portfolio returns.

### Position Size (% of account)
Risk per trade as pct of account (risk.max_risk_per_trade)

| Value | Sharpe | Max DD | CAGR | Calmar |
|-------|--------|--------|------|--------|
| 1.0 | 12.88 | -0.1% | 8.0% | 61.92 |
| 2.0 | 12.88 | -0.3% | 16.6% | 64.38 |
| 3.0 | 12.88 | -0.4% | 25.9% | 66.97 |
| 5.0 ← baseline | 12.88 | -0.6% | 46.7% | 72.57 |
| 7.0 | 12.88 | -0.9% | 70.9% | 78.77 |
| 10.0 | 12.88 | -1.3% | 114.8% | 89.39 |
| 15.0 | 12.88 | -1.9% | 214.2% | 111.33 |

### Stop Loss Multiplier
Stop loss as multiple of credit received

| Value | Sharpe | Max DD | CAGR | Calmar |
|-------|--------|--------|------|--------|
| 1.5 | 15.10 | -0.2% | 50.5% | 234.94 |
| 2.0 | 14.31 | -0.3% | 49.1% | 170.99 |
| 2.5 | 13.83 | -0.3% | 48.2% | 138.78 |
| 3.0 | 13.31 | -0.4% | 47.4% | 119.05 |
| 3.5 ← baseline | 12.88 | -0.6% | 46.7% | 72.57 |
| 4.0 | 12.69 | -0.7% | 46.3% | 68.97 |
| 5.0 | 12.32 | -0.7% | 45.7% | 62.64 |

### IV Rank Entry Threshold
Minimum IV rank to enter a trade (strategy.min_iv_rank)

| Value | Sharpe | Max DD | CAGR | Calmar |
|-------|--------|--------|------|--------|
| 0 | 12.78 | -0.6% | 46.6% | 79.05 |
| 5 | 12.88 | -0.7% | 46.7% | 70.65 |
| 10 | 12.88 | -0.7% | 46.7% | 71.79 |
| 15 | 12.58 | -0.6% | 44.9% | 69.77 |
| 20 | 12.09 | -0.6% | 42.3% | 65.69 |
| 30 | 10.92 | -0.6% | 37.0% | 57.54 |
| 40 | 10.15 | -0.5% | 32.1% | 60.56 |
| 50 | 9.27 | -0.6% | 27.4% | 49.82 |

### Profit Target (%)
Close at this % of max profit (risk.profit_target)

| Value | Sharpe | Max DD | CAGR | Calmar |
|-------|--------|--------|------|--------|
| 25 | 9.06 | -0.7% | 17.9% | 27.30 |
| 40 | 11.82 | -0.7% | 34.4% | 53.09 |
| 50 ← baseline | 12.88 | -0.6% | 46.7% | 72.57 |
| 60 | 13.62 | -0.6% | 60.1% | 94.07 |
| 75 | 14.39 | -0.6% | 82.5% | 130.59 |
| 90 | 14.39 | -0.6% | 82.5% | 130.59 |

### Spread Width ($)
Width between short and long strikes

| Value | Sharpe | Max DD | CAGR | Calmar |
|-------|--------|--------|------|--------|
| 2.5 | 12.88 | -0.4% | 26.6% | 67.18 |
| 5.0 ← baseline | 12.88 | -0.6% | 46.7% | 72.57 |
| 7.5 | 12.88 | -0.8% | 66.3% | 77.61 |
| 10.0 | 12.88 | -1.0% | 86.2% | 82.55 |
| 15.0 | 12.88 | -1.4% | 128.1% | 92.47 |
| 20.0 | 12.88 | -1.7% | 174.0% | 102.72 |

## Combined Portfolio Projections

### Projected Equity Curve (Best Allocation)

| Year | Annual Return | Ending Capital | vs S&P 500 |
|------|---------------|----------------|------------|
| 2020 | +56.6% | $156,640 | +38.2% vs SPY |
| 2021 | +61.1% | $252,286 | +32.4% vs SPY |
| 2022 | +33.3% | $336,395 | +52.9% vs SPY |
| 2023 | +28.2% | $431,235 | +1.9% vs SPY |
| 2024 | +30.8% | $564,123 | +7.7% vs SPY |
| 2025 | +65.3% | $932,246 | +40.4% vs SPY |
| **6yr Total** | **+832.2%** | **$932,246** | +694.3% vs SPY |

**CAGR:** +45.1% | **SPY CAGR:** +15.5% | **Alpha:** +29.5%

### Monte Carlo: 6-Year Forward Projections

Based on 1,000 block-bootstrap simulations of the combined portfolio:

- **P5 terminal wealth:** $870,709 (+771%)
- **P25 terminal wealth:** $943,905 (+844%)
- **P50 terminal wealth:** $998,374 (+898%)
- **P75 terminal wealth:** $1,048,354 (+948%)
- **P95 terminal wealth:** $1,136,422 (+1036%)
- **Prob. of profit:** 100.0%
- **Prob. of ruin (>50% loss):** 0.00%

## Allocation Recommendations

### Primary Recommendation: Max-Sharpe Allocation

| Strategy | Capital % | Dollar Amount ($100k) | Rationale |
|----------|-----------|-----------------------|-----------|
| EXP-305 | 33.8% | $33,831 | Multi-underlying diversification; sector alpha in bull markets |
| EXP-400 | 24.5% | $24,471 | Low DD anchor; regime-adaptive prevents large bear losses |
| EXP-154 | 24.2% | $24,175 | Most conservative; IC overlay in neutral regime adds consistency |
| EXP-520 | 12.5% | $12,523 | VIX gate protects against crash years; consistent cross-cycle |
| EXP-126 | 5.0% | $5,000 | High absolute returns; 2022 and 2025 powerhouse |

### Alternative: Risk Parity

Risk parity (inverse-vol weighting) gives more to lower-volatility strategies:

- **29.7%** → EXP-154 5% Dir + 12% IC (IC-Neutral)
- **27.0%** → EXP-400 Champion (DTE=15, Regime-Adaptive)
- **23.9%** → EXP-305 COMPASS Multi-Underlying (Top-2, 65%)
- **14.5%** → EXP-520 Real-Data Champion (VIX Gate, DTE=35/28)
- **5.0%** → EXP-126 8% Flat Risk (DTE=35, IC-Neutral)
  Expected return: +49.6%, Sharpe: 1.90

### Regime-Conditional Recommendations

| Regime | Best Strategy | Reasoning |
|--------|---------------|-----------|
| BULL | EXP-305 COMPASS | Sector ETFs add alpha in trending bull markets |
| NEUTRAL | EXP-400 Champion | Regime-adaptive IC + credit spreads in range-bound |
| BEAR | EXP-154 / EXP-520 | Lower risk, VIX gate limits crash exposure |

### Implementation Notes

1. **Rebalancing frequency:** Weekly (every 7 trading days) per `PortfolioOptimizer`
2. **Event gate:** Reduce total allocation by event scaling factor before FOMC/CPI/NFP
3. **Regime detection:** Use `compass.macro_db.get_current_macro_score()` for daily regime
4. **Minimum allocation:** 5% per strategy (prevents zero allocation per optimizer constraint)
5. **Max allocation cap:** No hard cap, but max-Sharpe naturally limits concentration

## Data Quality & Methodology Notes

| Strategy | Data Type | N | Confidence |
|----------|-----------|---|------------|
| EXP-400 | Deterministic backtest, real Polygon options data | 6 years | HIGH |
| EXP-126 | MC P50 (30 seeds, DTE U[33,37]) | 6 years | MEDIUM — only 30 seeds |
| EXP-154 | MC P50 (200 seeds, DTE U[33,37]) | 6 years | HIGH |
| EXP-520 | Deterministic backtest, real Polygon options data | 6 years | HIGH |
| EXP-305 | Deterministic COMPASS portfolio backtest | 6 years | MEDIUM — sectors use heuristic data |

**Limitations:**
- Correlation matrix computed on simulated monthly returns (except EXP-400 which uses actual monthly PnL)
- 6 years of data = small sample for covariance estimation; optimizer may overfit
- Sensitivity analysis uses heuristic return-scaling, not full backtest re-runs
- EXP-305 sector ETF data is sparse (heuristic mode, not real Polygon options data)
- All strategies are SPY/credit-spread-based → expect high tail correlation in crash events
