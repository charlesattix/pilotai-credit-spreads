# EXP-602: Compounding + Aggressive IC Push

## Mission
Combine EXP-601's breakthrough findings (IC-enhanced configs hitting +18.2% avg) with
compounding, higher risk allocation, tighter stops, and multi-ticker blending to close
the 3x gap to Carlos's reference (+56.6% avg).

## Baseline (from EXP-601)
| Config | Avg Return | Years+ | DD | IC% | Key Feature |
|--------|-----------|--------|-----|-----|-------------|
| A017 (SPY DTE=35 W=$5 OTM=3% risk=3%) | +18.2% | 4/6 | -28.6% | 35.5% | Highest avg return |
| A016 (SPY DTE=35 W=$5 OTM=3% risk=2%) | +14.6% | 4/6 | -23.2% | 35.5% | Best risk-adjusted |
| A003 (SPY DTE=15 W=$5 OTM=5% risk=3%) | +15.5% | 4/6 | -38.2% | 71.4% | Highest IC rate |
| C001 (QQQ DTE=35 W=$5 OTM=3% risk=2%) | +8.1% | 5/6 | -28.6% | 33.3% | Most consistent |

Carlos reference: 2020:+86.9%, 2021:+216.7%, 2022:+28.3%, 2023:+12.9%, 2024:-5.1%, 2025:-0.8% → avg ~+56.6%

## Stages

### Stage A: Compounding ON (16 combos)
**Hypothesis**: compound=True amplifies big years (2020 +42%, 2022 +45%) exponentially.
EXP-601 compound_return was already +127% for A017 — but that was computed after the fact.
Running with compound=True lets the backtester SIZE positions based on growing equity.

**Fixed**: A017 base (DTE=35, W=$5, OTM=3%, IC enabled, neutral_regime_only)
**Vary**:
- risk_per_trade: [2%, 3%, 4%, 5%] — higher risk on growing equity
- stop_loss_multiplier: [1.5, 2.0, 2.5, 3.0] — tighter stops protect compounded gains
- compound: True (always)
→ 4×4 = **16 combos × 6 years = 96 backtests**

### Stage B: Higher Risk + Tighter Stops (24 combos)
**Hypothesis**: Risk 5-8% with tighter stops (1.5-2.0x) captures more premium while
limiting damage. The asymmetry problem (1 loss = 2-3 wins) is mitigated by tighter stops.

**Fixed**: DTE=35, W=$5, OTM=3%, IC enabled, compound=False (isolate risk effect)
**Vary**:
- risk_per_trade: [4%, 5%, 6%, 8%]
- stop_loss_multiplier: [1.5, 2.0, 2.5]
- profit_target: [40%, 50%]
→ 4×3×2 = **24 combos × 6 years = 144 backtests**

### Stage C: DTE=15 Compound Push (16 combos)
**Hypothesis**: DTE=15 has 71% IC rate (densest IC trading), fastest theta decay,
and most pricing data. Compounding amplifies the +15.5% avg from A003.

**Fixed**: A003 base (DTE=15, W=$5, OTM=5%, IC enabled), compound=True
**Vary**:
- risk_per_trade: [2%, 3%, 4%, 5%]
- stop_loss_multiplier: [1.5, 2.0, 2.5, 3.0]
→ 4×4 = **16 combos × 6 years = 96 backtests**

### Stage D: Multi-Ticker Blend (8 combos)
**Hypothesis**: SPY has highest return, QQQ has best consistency (5/6 yrs).
Running both simultaneously with split capital should improve both metrics.
Also test compounding on the blend.

**Fixed**: Best configs from Stages A/B/C
**Combos**:
- SPY-only (best compound config)
- QQQ-only (best compound config)
- SPY+QQQ 50/50 split (no compound)
- SPY+QQQ 50/50 split (compound)
- SPY+QQQ 70/30 split (no compound)
- SPY+QQQ 70/30 split (compound)
- SPY+QQQ+IWM 50/30/20 (no compound)
- SPY+QQQ+IWM 50/30/20 (compound)
→ **8 combos × 6 years = 48 backtests**

### Stage E: VIX-Dynamic DTE (8 combos)
**Hypothesis**: DTE=15 is IC-heavy (71%) → best in high-vol. DTE=35 is directional-heavy → best in low-vol.
Use VIX threshold to switch: DTE=15 when VIX≥25, DTE=35 when VIX<25.

The backtester already supports `vix_dte_threshold` + `dte_low_vix`.

**Fixed**: W=$5, OTM=3%, IC enabled, compound=True
**Vary**:
- vix_dte_threshold: [20, 25]
- dte_low_vix: [35, 45] (low-vol DTE)
- target_dte: 15 (high-vol DTE)
- risk_per_trade: [3%, 5%]
→ 2×2×2 = **8 combos × 6 years = 48 backtests**

## Total: 72 combos × 6 years = 432 backtests

## Success Criteria
- **TARGET**: ≥+30% avg return, 5/6 years profitable, DD ≤ -30%
- **STRETCH**: ≥+40% avg (closes to 70% of Carlos reference)
- **MOONSHOT**: ≥+50% avg (within striking distance of Carlos)

## Key Risks
1. Compounding amplifies BOTH gains AND losses — 2023/2024 losses could crater equity
2. Higher risk without tighter stops → ruin risk (EXP-600 Phase 3 showed -$400K at risk=15%)
3. Multi-ticker dilution (SPY+QQQ was +10.7% vs SPY-solo +14.6% in EXP-601)
4. Max_contracts=25 cap may throttle compounding benefit at high equity levels

## Mitigation
- Circuit breaker at 25% drawdown (drawdown_cb_pct=25)
- Max 50 positions, 25 contracts per trade
- Stage B tests tighter stops (1.5x) to limit downside before adding compound
- Stage D uses proven best configs from earlier stages (not speculative)
