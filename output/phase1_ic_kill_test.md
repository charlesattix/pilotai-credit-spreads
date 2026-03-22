# Phase 1: IC Kill Test — IC=OFF vs IC=ON (3.5x Stop)

Run IDs:
- IC=OFF: `run_20260311_090726_524e0b`
- IC=ON 3.5x: `run_20260311_090848_aa2212`

Both runs: combo regime, stop_loss_multiplier=2.5, 10% risk, no compound.

---

## Year-by-Year Comparison

| Year | IC=OFF Return | IC=ON Return | IC=OFF Trades | IC=ON Trades | IC Count | IC Win Rate | IC=OFF MaxDD | IC=ON MaxDD |
|------|---------------|--------------|---------------|--------------|----------|-------------|--------------|-------------|
| 2020 | +10.9%        | +172.8%      | 169           | 222          | 53       | 75.5%       | -43.4%       | -41.2%      |
| 2021 | +46.2%        | +461.2%      | 102           | 203          | 101      | 84.2%       | -1.9%        | -10.7%      |
| 2022 | +17.1%        | +108.3%      | 182           | 249          | 67       | 59.7%       | -20.7%       | -16.6%      |
| 2023 | +11.1%        | +49.6%       | 62            | 107          | 45       | 66.7%       | -12.6%       | -22.4%      |
| 2024 | +21.0%        | +8.0%        | 109           | 155          | 58       | 55.2%       | -11.3%       | -61.2%      |
| 2025 | +54.7%        | +62.9%       | 158           | 166          | 8        | 87.5%       | -44.2%       | -36.7%      |

## Summary Comparison

| Metric          | IC=OFF   | IC=ON 3.5x |
|-----------------|----------|------------|
| Avg Return      | +26.9%   | +143.8%    |
| Worst DD        | -44.2%   | -61.2%     |
| Avg Trades/Year | 130      | 184        |
| Consistency     | 6/6 100% | 6/6 100%   |
| Total ICs fired | 0        | 332        |

## CRITICAL FINDING: With Combo Regime, ICs Fire Heavily

This is the most important finding of Phase 1. With combo regime enabled:

- **2020**: 53 ICs — COVID crash period produced many NEUTRAL regime days
- **2021**: 101 ICs — nearly 1:1 with bull puts; NEUTRAL was common in bull year
- **2022**: 67 ICs — bear market still had neutral windows
- **2023**: 45 ICs — recovery year produced lots of neutral regime days
- **2024**: 58 ICs — strong year but many regime-flip days
- **2025**: only 8 ICs — combo regime was decisive most of 2025

**Total: 332 ICs fired across 6 years.** The prior assumption that "ICs are rare with combo regime" was WRONG. Combo regime creates substantial NEUTRAL windows where ICs are the only available trade.

## Per-Year Bull Put / Bear Call Breakdown (IC=OFF)

| Year | Bull Put | Bull Put WR | Bear Call | Bear Call WR |
|------|----------|-------------|-----------|--------------|
| 2020 | 123      | 94.3%       | 46        | 58.7%        |
| 2021 | 102      | 99.0%       | 0         | N/A          |
| 2022 | 182      | 89.0%       | 0         | N/A          |
| 2023 | 62       | 93.6%       | 0         | N/A          |
| 2024 | 109      | 89.0%       | 0         | N/A          |
| 2025 | 148      | 87.2%       | 10        | 90.0%        |

Note: Bear calls only fire in 2020 (46 trades) and 2025 (10 trades). The unanimous bear requirement in combo regime nearly eliminates bear calls in all other years.

## Verdict: Did Removing ICs Help or Hurt?

**REMOVING ICs HURT BADLY.** IC=OFF lost 80% of returns:
- IC=OFF avg: +26.9%/yr vs IC=ON avg: +143.8%/yr
- IC=ON is 5.4x more profitable on average
- The extra return comes from capturing NEUTRAL-regime days that IC=OFF completely skips

**However**, IC=ON introduced a 2024 disaster: -61.2% MaxDD (vs -11.3% IC=OFF). IC win rates varied dramatically:
- 2020: 75.5% — good
- 2021: 84.2% — very good
- 2022: 59.7% — marginal
- 2023: 66.7% — acceptable
- **2024: 55.2%** — near coin-flip; combined with high IC count drove -61% DD

The 2024 failure needs investigation in Phase 2 (stop loss sensitivity).

**Bottom line**: ICs must stay ON. The opportunity cost of disabling ICs with combo regime is enormous.
