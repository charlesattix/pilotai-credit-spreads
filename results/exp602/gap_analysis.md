# EXP-602 Results: Compounding + Aggressive IC Push

## Summary

72 combos tested across 5 stages in 194 minutes (432 backtests).

| Metric | Carlos Ref | EXP-601 Best | EXP-602 Best (C015) | EXP-602 Best Balanced (A007) |
|--------|-----------|-------------|--------------------|-----------------------------|
| Avg Annual | +56.6% | +18.2% | **+36.2%** | +22.3% |
| Total 6yr | ~+340% | +127% | **+248%** | +148% |
| Final $100K | ~$440K | $227K | **$348K** | $248K |
| Years Profitable | 4/6 | 4/6 | 3/6 | 4/6 |
| Max Drawdown | ? | -28.6% | -52.4% | -44.5% |
| IC Rate | ? | 35.5% | 75.9% | 35.5% |

**Gap closed from 15x (EXP-600) → 3x (EXP-601) → 1.6x (EXP-602).**

## Stage Results

### Stage A: Compounding ON (DTE=35) — 16 combos
- **Winner by return**: A015 (risk=5%, SL=3.0x) → **$289K (+190%)**, 3/6 yrs, DD=-61%
- **Winner by balance**: A003 (risk=2%, SL=3.0x) → **$238K (+138%)**, 4/6 yrs, DD=-30%
- SL=3.0x consistently beats 1.5x and 2.0x (wider stops = more room to recover)
- 2022 dominance: A015 earned +247.6% in 2022 alone (151 IC trades)

### Stage B: Higher Risk (no compound) — 24 combos
- **Winner**: B010 (risk=5%, SL=2.5x, PT=40%) → **+29.2% avg**, 4/6 yrs, DD=-40%
- PT=40% outperforms PT=50% (faster profit capture)
- SL=2.5x > SL=2.0x > SL=1.5x (tighter stops HURT — hypothesis disproved)
- risk=4-5% sweet spot; risk=8% gets +33% avg but only 2-3/6 yrs profitable with -60% DD

### Stage C: DTE=15 Compound Push — 16 combos ★ BEST STAGE
- **Winner**: C015 (risk=5%, SL=3.0x) → **$348K (+248%)**, 76% IC rate
  - 2020: -9.2% (crash + low IC rate)
  - 2021: **+133.8%** (mostly ICs in calm market)
  - 2022: **+119.2%** (IC heaven — 178 of 179 trades are ICs)
  - 2023: -17.8% (whipsaw, low trade count)
  - 2024: -11.9% (only 12 trades)
  - 2025: +3.3% (modest recovery)
- DTE=15 compound beats DTE=35 compound (+248% vs +190%)
- IC rate 76% means this is effectively an IC strategy with directional overlay

### Stage D: Multi-Ticker Blend — 8 combos
- SPY solo (D000) = +190% (same as A015, the base config)
- SPY+QQQ 70/30 no-compound (D004) = +30.1% avg, 4/6 yrs (best consistency)
- Multi-ticker dilutes returns without improving consistency
- **QQQ solo underperformed**: +10.8% avg (4/6 yrs) vs SPY +39.9%
- Adding IWM hurts across all combos

### Stage E: VIX-Dynamic DTE — 8 combos ✗ BUST
- Best: E005 → only +74.8% total, 2/6 yrs
- VIX switching adds noise and hurts timing
- Static DTE (15 or 35) beats dynamic DTE in all configs
- **Hypothesis disproved**: VIX-based DTE switching does not improve results

## Key Findings

### What Works
1. **Compounding is the multiplier**: C015 compound (+248%) vs non-compound equiv (+93%)
2. **DTE=15 with ICs**: 76% IC rate → most trades are non-directional
3. **Wider stops (2.5-3.0x)**: Give trades room to recover from intraday noise
4. **PT=40%**: Faster profit capture beats PT=50%
5. **Risk=3-5%**: Sweet spot for return/risk tradeoff

### What Doesn't Work
1. **Tighter stops (1.5x)**: WORST performer — triggers on noise
2. **VIX-dynamic DTE**: Adds complexity without benefit
3. **Multi-ticker**: Dilutes alpha without improving consistency
4. **Risk>5%**: Diminishing returns, much worse drawdowns
5. **IWM**: Net negative in all combos

### The Consistency Problem
No config achieves both >+20% avg AND 5/6 years profitable. The pattern:
- 2020: Negative for aggressive configs (crash exposure)
- 2021: Strong (ICs in calm market)
- 2022: MONSTER year (high vol → IC heaven)
- 2023-2024: Negative for most (whipsaw, low trade count)
- 2025: Modest positive

## Gap Analysis: Why Not +56.6%?

### Remaining 1.6x Gap Drivers

1. **2020 Crash Loss**: C015 loses -9.2% in 2020 vs Carlos +86.9%.
   Carlos likely has aggressive directional trades during the crash recovery (Mar-Dec 2020).
   Our IC strategy sits out during high-vol crash.

2. **2023-2024 Bleed**: -17.8% and -11.9% are dead-weight years.
   Carlos: +12.9% and -5.1% — he's finding edge even in flat markets.
   Possible: more aggressive position sizing or different strategy mix.

3. **Max Contracts Cap**: At $348K equity, the 25-contract cap throttles compounding.
   With $348K and risk=5%, max position = $17.4K → only $5 width × 25 contracts = $12.5K max.
   The cap is binding for ~3 years of the backtest.

4. **Signal Density**: Only 12 trades in 2024 for DTE=15. Carlos may scan more
   frequently or use different entry criteria to generate more signals.

## Recommended Next Steps

### EXP-603: Attack the Weak Years
1. **Raise max_contracts to 50**: Unthrottle compounding at high equity
2. **2020 crash recovery**: Add special regime handling for post-crash rebound
3. **2023-2024 fix**: Test different OTM% or min_credit_pct for these specific market conditions
4. **Hybrid DTE**: DTE=15 for ICs, DTE=35 for directional (per-trade, not VIX-based)
5. **Combined PT=40% + compound**: Stage B showed PT=40% beats PT=50%, but Stage A/C used PT=50%

### Quick Wins to Test
- C015 config but with PT=40% (not 50%)
- C015 config but with max_contracts=50
- A003 config (best balanced) with PT=40%
- Best Stage B config (B010) with compound=True
