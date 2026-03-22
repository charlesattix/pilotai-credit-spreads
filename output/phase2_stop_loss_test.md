# Phase 2: Stop Loss Sensitivity — IC=ON 3.5x vs IC=ON 2x

Run IDs:
- IC=ON 3.5x stop (stop_loss_multiplier=2.5): `run_20260311_090848_aa2212`
- IC=ON 2x stop (stop_loss_multiplier=1.0): `run_20260311_091106_d8def1`

Both runs: combo regime, IC enabled, 10% risk, no compound.

---

## Year-by-Year Comparison

| Year | 3.5x Return | 2x Return | 3.5x Trades | 2x Trades | 3.5x IC WR | 2x IC WR | 3.5x MaxDD | 2x MaxDD |
|------|-------------|-----------|-------------|-----------|------------|----------|------------|----------|
| 2020 | +172.8%     | +47.1%    | 222         | 225       | 75.5%      | 67.9%    | -41.2%     | -55.1%   |
| 2021 | +461.2%     | +398.6%   | 203         | 204       | 84.2%      | 77.5%    | -10.7%     | -10.6%   |
| 2022 | +108.3%     | +72.1%    | 249         | 253       | 59.7%      | 56.7%    | -16.6%     | -23.5%   |
| 2023 | +49.6%      | +16.8%    | 107         | 108       | 66.7%      | 64.4%    | -22.4%     | -30.7%   |
| 2024 | +8.0%       | **-61.1%**| 155         | 27        | 55.2%      | **0.0%** | -61.2%     | -61.3%   |
| 2025 | +62.9%      | -14.4%    | 166         | 175       | 87.5%      | 87.5%    | -36.7%     | -32.1%   |

## Summary Comparison

| Metric          | IC=ON 3.5x | IC=ON 2x    |
|-----------------|------------|-------------|
| Avg Return      | +143.8%    | +76.5%      |
| Worst DD        | -61.2%     | -61.3%      |
| Avg Trades/Year | 184        | 165         |
| Consistency     | 6/6 100%   | 4/6 67%     |
| Years Negative  | 0          | 2 (2024, 2025) |

## Key Findings

### The 2x Stop Catastrophically Failed in 2024

The 2x stop (stop_loss_multiplier=1.0) triggered a catastrophic cascade in 2024:
- Only 27 trades completed (vs 155 for 3.5x stop)
- IC win rate collapsed to **0.0%** (vs 55.2%)
- Return: **-61.1%** (vs +8.0%)

The circuit breaker (drawdown_cb_pct=40%) activated mid-year due to the tighter stop triggering more losses early, cutting the trade count by 82% after the breaker fired. This is a classic stop-too-tight problem: normal IC fluctuation triggers stops before the trade can recover.

### 2x Stop Degrades Win Rates Across the Board

Comparing IC win rates:

| Year | 3.5x IC WR | 2x IC WR | Change    |
|------|------------|----------|-----------|
| 2020 | 75.5%      | 67.9%    | -7.6pp    |
| 2021 | 84.2%      | 77.5%    | -6.7pp    |
| 2022 | 59.7%      | 56.7%    | -3.0pp    |
| 2023 | 66.7%      | 64.4%    | -2.3pp    |
| 2024 | 55.2%      | 0.0%     | -55.2pp   |
| 2025 | 87.5%      | 87.5%    | 0.0pp     |

The 2x stop consistently degrades win rates because ICs (with credit on both sides) experience wider intraday swings. A tight 2x stop cuts premature exits that would have recovered.

### Overall Win Rate Degradation Also Hit Directional Trades

The 2x stop also degraded bull put win rates (2020: 94.3% → 78.4%; 2021: 99.0% → 93.1%), suggesting stop_loss_multiplier=1.0 is globally too tight for all spread types at these DTE/width settings.

## Verdict: Did Tighter Stop Improve IC Performance?

**NO. The 2x stop made everything worse.**

- IC win rate dropped in 5 of 6 years with tighter stops
- The 2024 circuit breaker cascade turned a mediocre +8% year into a -61% disaster
- The 3.5x stop (stop_loss_multiplier=2.5) is clearly superior
- The 2024 weakness (IC WR=55.2%, MaxDD=-61.2%) is a regime detection problem, not a stop loss problem

**Recommendation**: Keep stop_loss_multiplier=2.5. Do not tighten to 1.0.

## The Real 2024 Problem

2024's -61.2% MaxDD with IC=ON (3.5x stop) stems from:
- 58 ICs fired with only 55.2% win rate
- This implies combo regime was producing NEUTRAL signals during a strong bull market
- The regime detector was generating false neutrals, sending the system into ICs when it should have been in bull puts
- This is a regime calibration problem, not a stop loss problem
