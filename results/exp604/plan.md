# EXP-604: 6/6 Year Consistency — Carlos Directive

## Non-Negotiable Constraint
**EVERY SINGLE YEAR (2020-2025) must be profitable.** No exceptions. Consistency > raw return.

## Root Cause Analysis

### Why 2023-2024 Lose Money

**The math problem**: Credit spreads with PT=40-50% and SL=2.5-3.0x need 75%+ win rate
to be profitable. 2023-2024 achieve only 60-67% WR → guaranteed negative EV.

| Year | Market | SPY Return | Regime | IC Trades | IC Win Rate | Issue |
|------|--------|-----------|--------|-----------|-------------|-------|
| 2021 | Calm bull | +27% | Mostly BULL | 42 | 92.9% | Works great |
| 2022 | Bear + high vol | -18% | NEUTRAL+BEAR | 179 | 82.1% | IC heaven |
| 2023 | Recovery + pullbacks | +24% | Mostly BULL | 35 | 65.7% | IC WR drops |
| 2024 | Strong trend | +23% | Mostly BULL | 8-52 | 12-60% | IC disaster |

**Root Cause #1**: Combo regime detector classifies trending bull markets as BULL.
ICs only enter on rare NEUTRAL days. Those few ICs get breached on directional moves.

**Root Cause #2**: DTE=15 produces only 12 trades in 2024 (data sparsity).
Not enough trades to recover from any single loss.

**Root Cause #3**: Even directional bull puts at DTE=35 only get 66% WR in 2024.
With SL=3.0x, one loss erases 5+ wins.

### What P0141 Does Differently (the ONLY 6/6 config)
- **NO iron condors** — avoids the IC trap entirely
- **DTE=45** — more time for theta to work, higher WR
- **OTM=5%** — farther from money = harder to breach
- **risk=2%** — small positions = limited damage per loss
- **min_credit_pct=10%** — implicit vol filter, only trades in elevated IV

P0141 achieves +3.7% avg (6/6 yrs, -13.8% DD) by being ultra-conservative.

## Strategy: Find the Sweet Spot Between P0141 (+3.7%, 6/6) and Q1 (+33%, 4/6)

### Stage A: Conservative IC Sweep (24 combos)
**Hypothesis**: Wider OTM, lower risk, and optional IC enable can preserve 6/6 consistency
while beating P0141's +3.7% avg.

**Fixed**: compound=True, DTE=35, W=$5, min_credit_pct=5, regime_mode=combo
**Vary**:
- ic_enabled: [True, False] — test if ICs help or hurt 6/6
- otm_pct: [0.05, 0.07] — wider OTM for higher WR
- risk_per_trade: [1.0%, 1.5%, 2.0%] — conservative sizing
- profit_target: [40%, 50%]
→ 2×2×3×2 = **24 combos × 6 years = 144 backtests**

### Stage B: DTE=45 + P0141 Variants with Compound (12 combos)
**Hypothesis**: P0141 is already 6/6. Add compounding and slightly aggressive parameters.

**Fixed**: DTE=45, W=$5, OTM=5%, compound=True, regime_mode=combo
**Vary**:
- ic_enabled: [True, False]
- risk_per_trade: [2.0%, 3.0%]
- stop_loss_multiplier: [2.0, 2.5, 3.0]
→ 2×2×3 = **12 combos × 6 years = 72 backtests**

### Stage C: Drawdown-Adaptive (8 combos)
**Hypothesis**: Run month-by-month. When year-to-date drawdown exceeds a threshold,
cut risk for remaining months. This protects 2023-2024 from spiraling losses.

**Mechanism**: Run Jan, then Feb (carry capital), then Mar... If cumulative return
drops below threshold, reduce risk_per_trade by factor for remaining months.

**Fixed**: Best config from Stage A/B (whatever gets 6/6 or closest)
**Vary**:
- dd_threshold: [-3%, -5%] — when to trigger risk reduction
- risk_reduction: [0.5, 0.25] — multiply risk by this after trigger
→ 2×2 = 4 combos
Plus 4 more with the second-best config
→ **8 combos total**

### Stage D: Monthly Circuit Breaker (8 combos)
**Hypothesis**: After a losing month, reduce next month's risk. After 2 consecutive
losing months, reduce further. This prevents compounding of losses.

**Mechanism**: Track monthly P&L. After 1 losing month → risk × reduction_factor.
After 2 consecutive → risk × reduction_factor². After 3 → skip month.

**Fixed**: Best config from Stages A/B
**Vary**:
- reduction_factor: [0.5, 0.33]
- skip_after_n_consecutive_losses: [3, 4]
→ 2×2 = 4 combos per base config, 2 base configs
→ **8 combos total**

### Stage E: P0141 + Aggressive Blend (6 combos)
**Hypothesis**: Allocate majority capital to P0141-like config (guaranteed 6/6)
and minority to aggressive IC config. Floor return = P0141 contribution.

**Mechanism**: Split capital. Run both configs independently. Compound each leg.
P0141 leg provides floor; aggressive leg provides upside.

**Combos**:
- 80% P0141 + 20% Q1-config (compound)
- 70% P0141 + 30% Q1-config (compound)
- 60% P0141 + 40% Q1-config (compound)
- 80% P0141 + 20% A003-config
- 70% best-stageAB + 30% Q1-config
- Best-stageAB solo (baseline for comparison)
→ **6 combos**

## Total: ~58 combos, targeting 6/6 years profitable

## Success Criteria
- **HARD GATE**: 6/6 years profitable (non-negotiable)
- **PRIMARY**: Highest avg return among 6/6 configs
- **SECONDARY**: Lowest max drawdown among 6/6 configs
- **STRETCH**: ≥+15% avg while maintaining 6/6

## Reference Points
| Config | Avg Return | Total Return | 6/6? | DD |
|--------|-----------|-------------|------|-----|
| P0141 (no compound) | +3.7% | +22% | YES | -14% |
| Q3 (A003+PT40, compound) | +22.0% | +181% | 4/6 | -27% |
| Q1 (C015+PT40, compound) | +33.2% | +264% | 4/6 | -38% |
| Carlos reference | +56.6% | ~+340% | 4/6 | ? |
