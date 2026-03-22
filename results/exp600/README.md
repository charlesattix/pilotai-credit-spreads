# EXP-600: Real Data Credit Spread Optimization

## Mission
Fresh parameter optimization using ONLY real Iron Vault data. Old champion.json was tuned
on synthetic data — INVALID. Start from scratch with credit spreads on SPY.

## Data Source
- **Iron Vault**: `IronVault.instance()` → `data/options_cache.db`
- **729,057 contracts** (SPY 316K, QQQ 276K, IWM 136K)
- **10,735,115 daily bars** with 250+ trading days/year for 2020-2025
- **NO synthetic data**, NO Black-Scholes pricing. Cache miss = skip trade.

## Carlos Reference Results (Real Data)
| Year | Return |
|------|--------|
| 2020 | +86.9% |
| 2021 | +216.7% |
| 2022 | +28.3% |
| 2023 | +12.9% |
| 2024 | -5.1% |
| 2025 | -0.8% |

## Phase 0: DB Diagnostic

**Script**: `scripts/exp600_diagnostic.py`
**Output**: `results/exp600/diagnostic.json`

### Key Findings
1. **Data coverage is excellent**: 35K-67K SPY contracts per year, 840K-940K daily bars/year
2. **$1 strike spacing** throughout 2020-2025 — any spread width works
3. **All tested parameter configs find trades** across all sample dates
4. **Contracts exist for DTE 15-45** across all years
5. **Daily bar coverage varies by expiration** — some expirations have sparse bars

### Spread Width Feasibility
| Config | Hit Rate (7 sample dates) |
|--------|--------------------------|
| DTE=15, $12w, 2% OTM (champion) | 7/7 |
| DTE=30, $5w, 3% OTM (conservative) | 7/7 |
| DTE=35, $5w, 5% OTM (standard) | 7/7 |
| DTE=45, $5w, 5% OTM (wide DTE) | 5/7 |

## Phase 1: Quick Sweep (8 combos)

**Script**: `scripts/exp600_sweep.py --quick`
**Output**: `results/exp600/sweep_results.json`

### Grid
- DTE: 30, 45 | Width: $5, $10 | OTM: 3%, 5% | PT: 50% | SL: 2.0x | Risk: 2% | Dir: both

### Results
- **Best**: DTE=45, W=$10, OTM=5%, PT=50%, SL=2.0x → **+4.0% avg**, 5/6 years profitable
- Trades flow well: 124-468 trades/config across 6 years
- 2020 is the killer: -3% to -38% depending on config (COVID crash)
- Returns low with 2% risk — need higher leverage to match Charles's results

## Phase 2: Targeted Sweep (144 combos) — KILLED

**Script**: `scripts/exp600_sweep_v2.py`
**Bug**: max_contracts=10 capped both 5% and 8.5% risk to identical position sizes.

## Phase 3: Uncapped Sweep — KILLED

**Script**: `scripts/exp600_sweep_v3.py`
**Bug**: max_contracts=999 → RUIN events in 2020 (capital goes -$400K).

## Phase 4: Independent-Year Sweep (216 combos) — COMPLETE

**Script**: `scripts/exp600_sweep_v4.py`
**Output**: `results/exp600/sweep_v4_results.json`
**Runtime**: 5.3 hours (1,296 backtests)

### Design Fixes
- Independent years: reset to $100K each year (no cascade of losses)
- max_contracts=25 (differentiates 2%/5%/8.5% risk levels)
- drawdown_cb_pct=25 (circuit breaker)
- compound=False, sizing_mode=flat
- Removed direction="bull_put" — IDENTICAL to "both" under regime_mode=combo

### Grid
- DTE: 30, 45 | Width: $5, $10 | OTM: 3%, 5%
- PT: 50%, 65%, 80% | SL: 1.5x, 2.0x, 2.5x | Risk: 2%, 5%, 8.5%
- Direction: both (regime_mode=combo overrides direction)

### Results Summary
- **29/216 combos positive** (13.4%), 187/216 negative
- **0 GOOD results** (none hit >10% avg AND 4+ profitable years)
- DTE=45 dominates: 28/29 positive configs are DTE=45 (only 1 DTE=30 positive)
- OTM=5% wins: 26/29 positive configs

### Top 5 Leaderboard

| Rk | ID | Avg | Trades | Yrs+ | WR | DD | Comp$ | Config |
|---|---|---|---|---|---|---|---|---|
| 1 | P0195 | +9.4% | 187 | 5/6 | 89% | -27.1% | $159K | DTE=45 W=$10 OTM=5% PT=50% SL=2.5x risk=2% |
| 2 | P0192 | +9.4% | 187 | 5/6 | 88% | -27.1% | $159K | DTE=45 W=$10 OTM=5% PT=50% SL=2.0x risk=2% |
| 3 | P0196 | +9.2% | 187 | 5/6 | 89% | -53.3% | $154K | DTE=45 W=$10 OTM=5% PT=50% SL=2.5x risk=5% |
| 4 | P0193 | +9.1% | 187 | 5/6 | 88% | -53.3% | $154K | DTE=45 W=$10 OTM=5% PT=50% SL=2.0x risk=5% |
| 5 | P0189 | +8.7% | 187 | 5/6 | 86% | -28.9% | $152K | DTE=45 W=$10 OTM=5% PT=50% SL=1.5x risk=2% |

### Best Consistent Config (6/6 years profitable)

**P0141**: DTE=45, W=$5, OTM=5%, PT=50%, SL=2.5x, risk=2%
- Avg: +3.7%, 240 trades, DD -13.8%, Comp $124K
- 2020: +14.6% | 2021: +0.7% | 2022: +4.2% | 2023: +0.9% | 2024: +1.1% | 2025: +0.9%

### Key Pattern Analysis

| Parameter | Winner | Evidence |
|-----------|--------|----------|
| DTE | 45 | 26% positive vs 1% for DTE=30 |
| OTM | 5% | 24% positive vs 3% for OTM=3% |
| Width | $10 | Higher avg returns but 2-trade years |
| PT | 50% | 21% positive vs 11% (65%) vs 8% (80%) |
| SL | 2.5x | 19% positive vs 12% (2.0x) vs 8% (1.5x) |
| Risk | 2% | 24% positive vs 8% (5%) vs 8% (8.5%) |

### Critical Issues Found

1. **2025 distortion**: Top W=$10 configs get +50-60% in 2025, driving avg returns.
   Only 2 trades in 2021, 2 in 2023, 8 in 2024 — sparse data.
2. **2020 regime failure**: ComboRegimeDetector biases toward BULL (2/3 votes needed
   for BULL vs ALL 3/3 for BEAR). During COVID crash, keeps routing to bull puts.
   DTE=45 + OTM=5% configs survive 2020 (+14.6% with SL=2.5x, risk=2%).
3. **Returns vs Charles**: Best is +9.4% avg vs Charles +86.9% in 2020 alone.
   The 6/6-consistent config returns only +3.7% avg — barely beats cash.
4. **Trade sparsity at W=$10**: Only 187 trades across 6 years (avg 31/yr).
   Too few trades for statistical significance.

## Phase 5: Trade Flow Debug — ROOT CAUSE FOUND

**Script**: `scripts/exp600_trade_flow_debug.py`
**Output**: `results/exp600/trade_flow_debug.md`

### The Mystery
Why 2 trades in 2021/2023 but 68 in 2022 and 58 in 2025?

### Root Cause: Minimum Credit Threshold (THE SMOKING GUN)

The W=$10 spread requires a minimum credit of $1.00 (10% × $10 width). The backtester
rejects trades where the net credit is below this threshold. This is the **dominant
differentiator** between high-trade and low-trade years:

| Year | Regime | Below-Min-Credit/Qtr | Trades | Explanation |
|------|--------|---------------------|--------|-------------|
| 2021 | Bull | 462-672 (HIGH) | 2 | Calm market, puts dirt cheap |
| 2022 | Bear | 252-392 (LOW) | 68 | Volatile, puts expensive |
| 2023 | Recovery | 434-658 (HIGH) | 2 | Vol drops, puts cheap again |
| 2025 | Volatile | 140-448 (LOW) | 58 | Elevated IV, fat credits |

In calm markets (2021 bull, 2023 recovery), 5% OTM put spreads generate only $0.50-$0.65
credit — well below the $1.00 minimum. In volatile markets (2022 bear, 2025), IV is
elevated and credits easily exceed $1.00.

### Secondary Issue: Daily Bar Sparsity

Deep OTM option bars only appear ~20-35 DTE before expiration (median). At target DTE=45,
most contracts don't have bars yet. But this affects ALL years roughly equally — it's NOT
the differentiator between 2-trade and 68-trade years. The backtester mitigates this with
±1/±2 strike adjustments and Friday expiration fallback.

### Key Insight

**The "winning" W=$10 configs don't win because they're better strategies.** They win because
the minimum credit threshold acts as an implicit volatility filter — the strategy ONLY
opens trades when IV is elevated. This is survivorship bias, not edge.

### Conclusions

- **DTE=45, OTM=5% is the clear winner** — survives 2020, consistent across years
- **W=$5 is more reliable** (40+ trades/year, lower credit threshold = more consistent flow)
- **W=$10 returns are inflated by 2025** and implicit vol-filter effect
- **Best reliable config: DTE=45, W=$5, OTM=5%, PT=50%, SL=2.5x, risk=2%**
  (+3.7% avg, 6/6 profitable, -13.8% max DD, 240 trades)
- Gap to Charles is enormous — likely a different backtesting approach or data source
- **Next: test lower min_credit_pct (5%) to increase trade flow in calm years**

## Phase 6: Consistency Sweep — DTE=30 FAILS

**Script**: `scripts/exp600_sweep_v5.py`
**Output**: `results/exp600/sweep_v5_results.json`
**Runtime**: 102 min (72 combos × 6 years = 432 backtests)

### Design
Based on trade-flow-debug findings:
- W=$5, DTE=30, min_credit_pct=5% (lowered from 10%)
- OTM: 2%, 3%, 4%, 5%
- Risk: 3%, 4%, 5%  |  PT: 40%, 50%, 65%  |  SL: 2.5x
- regime_mode: 'combo' vs 'none' (72 combos)
- Target: 6/6 profitable, >30 trades/yr, >5% avg

### Results: 0 TARGET, 0 GOOD (6/6 profitable)

| Regime Mode | Positive | Avg Return | Best Config | 6/6 Profitable |
|-------------|----------|------------|-------------|----------------|
| combo | 1/36 (3%) | -11.2% | +0.3% avg (OTM=2% PT=50%) | 0 |
| none | 32/36 (89%) | +17.8% | +42.4% avg (OTM=3% PT=40%) | 0 |

### Why DTE=30 Fails

**combo regime**: BULL-biased regime detector → only opens bull puts → gets destroyed
in 2022 bear market (-22% to -34%) and 2024 (-12% to -18%).

**no regime (both directions)**: Opens bull puts AND bear calls → bear calls print
+228-312% in 2022 bear market, but bear calls lose -20 to -38% in 2021 bull market
and -27 to -44% in 2024. Wild swings, no consistency.

### The Directional Dilemma

| Year | Market | Bull Puts | Bear Calls | Both |
|------|--------|-----------|------------|------|
| 2020 | COVID crash+recovery | Volatile | Moderate | Mixed |
| 2021 | Strong bull | OK (+1%) | TERRIBLE (-28%) | Bad |
| 2022 | Bear market | TERRIBLE (-23%) | EXCELLENT (+248%) | Net OK |
| 2023 | Recovery | Thin (+0.4%) | Moderate (+16%) | Mixed |
| 2024 | Bull | Moderate (-14%) | TERRIBLE (-44%) | Bad |
| 2025 | Volatile | Good (+21%) | Good (+16%) | Good |

No single direction works across all years. The combo regime detector fails because
it can't identify bear markets quickly enough (2/3 vote for BULL vs 3/3 for BEAR).

### Phase 4 Winner Still Stands

**P0141 (DTE=45, W=$5, OTM=5%, PT=50%, SL=2.5x, risk=2%) remains the best consistent
config**: +3.7% avg, 6/6 profitable, -13.8% DD, 240 trades. DTE=45's sparse data
acts as a natural throttle — fewer trades means less exposure to wrong-direction trades.

## Phase 7: Direction-Aware Sweep — MA50 FILTER INSUFFICIENT

**Script**: `scripts/exp600_sweep_v6.py`
**Output**: `results/exp600/sweep_v6_results.json`
**Runtime**: 87 min (72 combos × 6 years = 432 backtests)

### Design
Phase 6 showed regime_mode='none' with direction='both' gets high avg returns but 0/36
configs are 6/6 profitable. This phase tests each direction SEPARATELY with MA50 trend filter:
- bull_put: only enters when price >= MA50 (bullish)
- bear_call: only enters when price <= MA50 (bearish)
- both (trend-MA): applies BOTH filters — puts above MA, calls below MA

### Grid
- 3 directions × 2 DTEs (30, 45) × 2 OTMs (3%, 5%) × 3 PTs (40%, 50%, 60%) × 2 risks (3%, 4%)
- Fixed: W=$5, SL=2.5x, min_credit_pct=5%, regime_mode='none'

### Results: 0 TARGET, 0 GOOD (5/6+ profitable)

| Direction | Positive Avg | Avg Return | 5/6+ Profitable | 6/6 Profitable |
|-----------|-------------|------------|-----------------|----------------|
| puts-only | 0/24 (0%) | -2.9% | 0 | 0 |
| calls-only | 24/24 (100%) | +19.1% | 0 | 0 |
| trend-MA | 23/24 (96%) | +17.5% | 0 | 0 |

### Top 5 by Consistency Score (all score 83, all 4/6 profitable)

| Rk | ID | Avg | Trades | Yrs+ | WR | DD | Config |
|---|---|---|---|---|---|---|---|
| 1 | D0048 | +42.4% | 864 | 4/6 | 77% | -47.4% | DTE=30 OTM=3% PT=40% risk=3% trend-MA |
| 2 | D0060 | +30.7% | 733 | 4/6 | 78% | -35.1% | DTE=45 OTM=3% PT=40% risk=3% trend-MA |
| 3 | D0062 | +31.5% | 728 | 4/6 | 80% | -34.3% | DTE=45 OTM=3% PT=50% risk=3% trend-MA |
| 4 | D0064 | +30.8% | 727 | 4/6 | 82% | -31.1% | DTE=45 OTM=3% PT=60% risk=3% trend-MA |
| 5 | D0065 | +38.0% | 689 | 4/6 | 82% | -56.4% | DTE=45 OTM=3% PT=60% risk=4% trend-MA |

### Why No Direction Achieves 5/6+ Profitable Years

| Year | Market | Puts-Only | Calls-Only | Trend-MA |
|------|--------|-----------|------------|----------|
| 2020 | COVID crash+recovery | -3% to -21% | +10% to +52% | +8% to +32% |
| 2021 | Strong bull | +1% to +5% | -13% to -48% | -15% to -47% |
| 2022 | Bear market | -15% to -43% | +120% to +305% | +99% to +248% |
| 2023 | Recovery | +0.5% to +5% | +11% to +51% | +12% to +49% |
| 2024 | Bull | +2% to +7% | -23% to -56% | -27% to -56% |
| 2025 | Volatile | +1% to +5% | +9% to +34% | +12% to +38% |

**2021 and 2024 (bull years)** always negative for calls-only and trend-MA configs.
Bear calls during bull runs get stopped out before MA50 catches up. The MA50 filter
lags too much to prevent wrong-direction entries in trending markets.

**Puts-only** never positive on average — stop losses exceed credits across all configs.

### Conclusions

- **MA50 trend filter is insufficient** — too slow to prevent wrong-direction trades
- **No single direction or combination achieves 5/6+ profitable years** at DTE=30 or DTE=45
- **Puts-only is dead** at these parameters (0/24 positive avg return)
- **Calls-only and trend-MA produce high averages** (+19%, +17.5%) but driven by
  massive 2022 bear gains that mask devastating 2021/2024 losses
- **Phase 4 P0141 STILL the best consistent config** — DTE=45 sparse data acts as
  natural throttle, regime_mode=combo at least partially filters direction

### Phase 4 Winner Still Stands (All Phases)

**P0141**: DTE=45, W=$5, OTM=5%, PT=50%, SL=2.5x, risk=2%, regime_mode=combo
→ +3.7% avg, **6/6 profitable**, -13.8% DD, 240 trades

This is the ONLY config across 7 phases (500+ combos tested) that achieves 6/6
profitable years with meaningful trade flow.

## Phase 8: Beat P0141 — Faster Trend Filters — FAILED

**Script**: `scripts/exp600_sweep_v7.py`
**Output**: `results/exp600/sweep_v7_results.json`
**Runtime**: 69 min (49 combos × 6 years = 294 backtests)

### Design
Phase 7 showed MA50 is too slow. Test faster MAs (EMA9, EMA20, SMA20) to react
more quickly to trend changes. Added EMA support to backtester (`trend_ma_type` param).
- P0141 exact config as control (regime_mode=combo)
- 48 experimental configs with regime_mode='none' (MA filter active)

### Grid
- MA: SMA50, SMA20, EMA20, EMA9 (4 types)
- Direction: bull_put, both (trend-following)
- Risk: 2%, 3%, 4%
- DTE: 30, 45
- Fixed: W=$5, OTM=5%, PT=50%, SL=2.5x, min_credit_pct=5%

### Results: 0 Configs Beat P0141 (5/6+ profitable)

**Maximum profitability: 3/6 years.** No config achieved even 4/6 profitable years.

| MA Type | Positive Avg | Avg Return | Best Score | 5/6+ Profitable |
|---------|-------------|------------|------------|-----------------|
| SMA50 | 6/12 | +2.9% | 75 | 0 |
| SMA20 | 6/12 | +6.5% | 75 | 0 |
| EMA20 | 6/12 | +7.3% | 75 | 0 |
| EMA9 | 6/12 | +3.5% | 75 | 0 |

| Direction | Positive | Avg Return |
|-----------|----------|------------|
| bull_put | 0/24 | -1.6% |
| both | 24/24 | +11.8% |

### Key Findings

1. **EMA20 is marginally best** (+7.3% avg) — responds faster than SMA50 (+2.9%)
   but still can't avoid 2021/2024 bear call losses
2. **EMA9 is too fast** (+3.5%) — whipsaw signals generate worse entries, especially
   in 2020 where EMA9+both DTE=30 gets -16.7% vs EMA20's +44.7%
3. **bull_put is universally dead** — even with fast EMA9 filter, 0/24 positive avg
4. **No MA speed fixes the directional problem** — 2021 (-25% to -42%) and 2024
   (-25% to -59%) always destroy bear call legs regardless of MA type

### Control Discrepancy Note

P0141 control showed -0.1% avg (vs original +3.7%) because `min_credit_pct=5`
was used instead of the original Phase 4's `min_credit_pct=10`. Lower credit
threshold → 597 trades (vs 240) → more marginal trades accepted → worse returns.
**Original P0141 with min_credit_pct=10 still stands as the true champion.**

### Conclusion: MA-Based Direction Filtering Is Fundamentally Broken

Across Phases 6-8, we tested:
- regime_mode='combo' (Phase 4) — broken BULL bias, but constrains trade flow
- regime_mode='none' with MA50 (Phase 7) — too slow
- regime_mode='none' with SMA20/EMA20/EMA9 (Phase 8) — faster but still can't
  prevent wrong-direction trades

The problem isn't MA speed. **The problem is that credit spreads inherently
lose more per losing trade than they gain per winning trade.** When direction
is wrong for even 1-2 months, the stop losses wipe out months of credit collected.

**P0141 works not because of good direction filtering, but because:**
- DTE=45 naturally reduces trade frequency (fewer entries = less exposure)
- min_credit_pct=10 acts as implicit vol filter (only trades when IV is elevated)
- OTM=5% keeps strikes far enough from current price

**600+ combos tested across 8 phases. P0141 remains the only 6/6 profitable config.**

## Files
| File | Purpose |
|------|---------|
| `scripts/exp600_diagnostic.py` | DB probe and coverage analysis |
| `scripts/exp600_sweep.py` | Phase 1 quick sweep |
| `scripts/exp600_sweep_v2.py` | Phase 2 targeted sweep (killed) |
| `scripts/exp600_sweep_v3.py` | Phase 3 uncapped sweep (killed) |
| `scripts/exp600_sweep_v4.py` | Phase 4 independent-year sweep |
| `results/exp600/diagnostic.json` | DB diagnostic data |
| `results/exp600/sweep_results.json` | Phase 1 results |
| `results/exp600/sweep_v4_results.json` | Phase 4 results (216 combos) |
| `scripts/exp600_trade_flow_debug.py` | Trade flow debug (root cause analysis) |
| `results/exp600/trade_flow_debug.md` | Trade flow debug findings |
| `scripts/exp600_sweep_v5.py` | Phase 6 consistency sweep (DTE=30) |
| `results/exp600/sweep_v5_results.json` | Phase 6 results (72 combos) |
| `scripts/exp600_sweep_v6.py` | Phase 7 direction-aware sweep |
| `results/exp600/sweep_v6_results.json` | Phase 7 results (72 combos) |
| `scripts/exp600_sweep_v7.py` | Phase 8 faster trend filters (EMA/SMA) |
| `results/exp600/sweep_v7_results.json` | Phase 8 results (49 combos) |
