# EXP-601 Gap Analysis: Why Credit Spreads Alone Can't Match Carlos's Results

## The Gap

| Metric | Carlos Reference | EXP-600 Best (P0141) | Gap |
|--------|-----------------|---------------------|-----|
| 2020 | +86.9% | +0.2% | 430x |
| 2021 | +216.7% | +4.8% | 45x |
| 2022 | +28.3% | +0.9% | 31x |
| 2023 | +12.9% | +3.7% avg across 6yr | 3.5x |
| Avg | ~56.6% | +3.7% | 15x |

## Root Cause #1: Directional Asymmetry (The Fundamental Problem)

Credit spreads have asymmetric payoffs:
- **Win**: collect small credit (1-3% of width)
- **Lose**: stop loss at 2-2.5x credit (250%+ of win)
- **Result**: 1 losing trade wipes out 2-3 winners

Across 600+ combos tested in 8 EXP-600 phases:
- Bull puts lose in bear markets (2022)
- Bear calls lose in bull markets (2021, 2024)
- "Both" direction via combo regime → BULL bias (2/3 vote for bull, 3/3 for bear)
- **No single direction config achieves 6/6 profitable years** except P0141

P0141 "works" only because DTE=45 + min_credit_pct=10% creates an implicit vol filter
that restricts trading to favorable conditions. It's not edge — it's avoidance.

## Root Cause #2: Min Credit Threshold = Implicit Vol Filter

The smoking gun from trade flow debug:
- W=$10 with min_credit_pct=10% needs $1.00 credit → only trades in high-vol windows
- 2021 (low vol): **2 trades** (462-672 rejections per quarter)
- 2022 (high vol): **68 trades** (credits easily exceed threshold)
- 2023 (recovery): **2 trades** (calm market → cheap puts)
- Top results are distorted by 2025 Q2 vol spike (+51% from ONE quarter)

## Root Cause #3: Data Sparsity at Long DTE

Polygon daily bars for deep OTM options at DTE=45 are sparse:
- 2023: median first-bar DTE = 11 (26% of contracts have 0 bars)
- 2024: median first-bar DTE = 13 (34% of contracts have 0 bars)
- DTE=45 targeting means many trades simply can't find pricing data

## Root Cause #4: Single-Strategy Limitation

Carlos's results likely use a multi-strategy approach:
- Champion config (EXP-400) uses CS + IC + other strategies → +32.7% avg (vs +3.7%)
- EXP-401 blend (CS + S/S regime-optimized) → +40.7% avg
- Multi-strategy eliminates single-direction dependency

## What Actually Works (Validated Results)

| Experiment | Strategies | Avg Return | Max DD | Profitable Years |
|-----------|-----------|-----------|--------|-----------------|
| EXP-400 | CS + IC (regime) | +32.7% | -12.1% | 5/6 |
| EXP-401 | CS + S/S (regime+blend) | +40.7% | -7.0% | 6/6 |
| EXP-600 P0141 | CS solo | +3.7% | -13.8% | 6/6 |
| EXP-600 v8 best | CS solo (DTE=30, OTM=3%) | -6.2% | -40.5% | 1/6 |

**Key insight**: Every validated profitable system uses multiple strategies.

## The Untested Opportunity: IC-Enhanced Credit Spreads

The single-ticker backtester (`backtest/backtester.py`) has **native iron condor support**
via `iron_condor.enabled=True` + `iron_condor.neutral_regime_only=True`:

- **BULL regime** → bull puts (directional credit spread)
- **BEAR regime** → bear calls (directional credit spread)
- **NEUTRAL regime** → iron condors (non-directional, profits from time decay)

This has NEVER been tested with real Iron Vault data in the EXP-600 series.
Iron condors in NEUTRAL regime solve the directionality problem because they profit
from range-bound markets without a directional bet.

## Additional Untested Levers

1. **IV rank entry gate** (`iv_rank_min_entry`): Only sell premium when IV is elevated
   → Quality over quantity. Avoids low-vol environments where credit is too thin.

2. **VIX max entry** (`vix_max_entry`): Block entries when VIX is extreme
   → Avoids selling premium into crashes.

3. **IV-scaled sizing** (`sizing_mode='iv_scaled'`): Scale position sizes based on IV
   → Bigger positions in rich-premium environments, smaller in thin-premium.

4. **Shorter DTE** (15-25 vs 45): Dense pricing data + faster time decay
   → Champion config uses DTE=15. More data bars = more reliable fills.

5. **VIX close-all** (`vix_close_all`): Emergency exit all positions when VIX spikes
   → Limits downside in crash scenarios.

## Proposed EXP-601: IC-Enhanced Multi-Regime Sweep

See sweep design in `scripts/exp601_sweep.py`.
