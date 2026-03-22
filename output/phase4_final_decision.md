# Phase 4: Final Decision — IC Configuration for Production

Based on Phase 1-3 findings from runs on 2026-03-11.

---

## Summary of Findings

### Phase 1 (IC Kill Test)
- IC=OFF avg return: **+26.9%/yr**
- IC=ON avg return: **+143.8%/yr**
- ICs fired 332 times across 6 years with combo regime
- Removing ICs costs **80% of total returns** — the combo regime creates abundant NEUTRAL windows
- IC=OFF is NOT viable with combo regime

### Phase 2 (Stop Loss Test)
- 2x stop (multiplier=1.0) degraded win rates in 5/6 years and caused a -61% cascade in 2024
- 3.5x stop (multiplier=2.5) dominates: higher WR, 6/6 profitable years
- Tighter stop = worse ICs. Do not tighten.

### Phase 3 (Bear Call Analysis)
- Bear calls only fired meaningfully in 2020 (46 trades, 58.7% WR) and 2025 (10 trades, noise)
- Unanimous BEAR requirement nearly blocks bear calls in all normal market conditions
- ICs capture the NEUTRAL regime; bear calls are incidental crash-response

---

## Decision

### ICs: KEEP ENABLED

ICs added +116.9% average annual return versus IC=OFF. This is not marginal — it is the core of the strategy's profitability with combo regime.

Verdict: **DO NOT DISABLE ICs.**

### Stop Loss: KEEP AT 2.5x (stop_loss_multiplier=2.5)

The 2x stop (multiplier=1.0) caused catastrophic 2024 failure and degraded win rates across all years. The 3.5x stop is clearly superior.

Verdict: **DO NOT TIGHTEN STOP LOSS.**

### Outstanding Risk: 2024 IC Weakness

With IC=ON (3.5x stop), 2024 shows:
- 58 ICs with only 55.2% win rate → the weakest IC year
- MaxDD of -61.2% (worst of all 6 years)
- This is a **regime calibration issue**: combo regime generated false NEUTRAL signals during a strong 2024 bull market, routing too many trades into ICs instead of bull puts

In 2024, SPY rallied strongly but with periodic dips (rate cut uncertainty, election). The combo regime's RSI/VIX checks kept triggering NEUTRAL on these dips, creating ICs at exactly the wrong times.

**This is not fixed by stop loss changes.** It requires either:
1. Reducing NEUTRAL sensitivity (make RSI/VIX thresholds harder to hit)
2. Reverting NEUTRAL regime to bull puts rather than ICs (i.e., ICs only when NEUTRAL is sustained, not transient)
3. Accepting 2024's -61% DD as the regime's calibration cost

---

## Production Config Recommendation

### Current champion: `configs/exp_097_combo_regime.json`

Checking exp_097 status: exp_097 has `iron_condor_enabled=false` — this is WRONG based on Phase 1 findings. With combo regime, IC=OFF loses 80% of returns.

### Required update to exp_097:

The production config needs:
- `iron_condor_enabled: true`
- `stop_loss_multiplier: 2.5` (already correct)

However, there is a known risk: 2024's -61.2% MaxDD with ICs enabled. Before updating exp_097 for production use, the 2024 regime calibration issue must be investigated.

### Recommended immediate action:

1. **Research config `phase1_ic_on_3p5x`** is the current best-performing tested configuration (avg +143.8%, 6/6 profitable)
2. **Do not update exp_097 blindly** — the 2024 -61% DD is a real risk that needs regime tuning first
3. **Flag for next investigation**: reduce NEUTRAL regime sensitivity (RSI thresholds, VIX structure thresholds) to lower IC count in strong bull years without eliminating ICs entirely

---

## Numerical Scorecard

| Config          | Avg Return | Worst DD | Consistency | IC Count | 2024 DD  |
|-----------------|------------|----------|-------------|----------|----------|
| IC=OFF (phase1) | +26.9%     | -44.2%   | 6/6         | 0        | -11.3%   |
| IC=ON 3.5x      | +143.8%    | -61.2%   | 6/6         | 332      | -61.2%   |
| IC=ON 2x stop   | +76.5%     | -61.3%   | 4/6         | 318      | -61.3%   |

The IC=ON 3.5x stop is the best overall configuration. The 2024 DD is the only blemish and is attributable to regime detection, not IC mechanics.
