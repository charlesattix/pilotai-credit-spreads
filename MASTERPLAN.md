# MASTERPLAN.md — Operation Crack The Code 🎯

## Mission
Achieve **200%+ annual returns** on every year from 2020-2025 through continuous, autonomous backtesting optimization of the credit spread system.

## Target Metrics
| Year | Min Return | Max Drawdown | Min Trades |
|------|-----------|-------------|------------|
| 2020 | +200% | <50% | 50+ |
| 2021 | +200% | <50% | 50+ |
| 2022 | +200% | <50% | 50+ |
| 2023 | +200% | <50% | 50+ |
| 2024 | +200% | <50% | 50+ |
| 2025 | +200% | <50% | 50+ |

## Current Best (Baseline)
| Year | Return | Trades | Sharpe | Notes |
|------|--------|--------|--------|-------|
| 2025 | +15.11% | 217 | 2.27 | Best year so far |
| 2024 | TBD | 128 | TBD | After sigma fix |

---

## THE LOOP (Run This Continuously)

### Step 1: Pick Next Experiment
- Read `output/leaderboard.json` — find the current best params
- Read `output/optimization_log.json` — see what's been tried
- Choose the next experiment based on current phase (see Phases below)
- Log your hypothesis in the optimization log BEFORE running

### Step 2: Modify & Run Backtest
- Update backtest parameters (in a config dict, NOT hardcoded)
- Run: `python3 scripts/run_optimization.py --config <config_name>`
- If no optimization script exists yet, BUILD IT FIRST (Phase 0)

### Step 3: Record Results
- Append results to `output/leaderboard.json`
- Format: `{run_id, timestamp, params, results_by_year, avg_return, max_dd, notes, validation}`
- If this run beats the current best for ANY year → flag it 🏆

### Step 3.5: MANDATORY OVERFIT CHECK (Run EVERY Time) 🛡️
**No result is real until it passes ALL of these checks. No exceptions.**

#### A. Cross-Year Consistency Test
- A valid param set must be profitable in **at least 5 of 6 years**
- If params crush 2021 (+300%) but lose money in 2022 → **OVERFIT, REJECT**
- Calculate: `consistency_score = years_profitable / 6`
- Minimum acceptable: **0.83 (5/6 years)**

#### B. Walk-Forward Validation (Split Test)
- **Train set**: Optimize params on 2020-2022
- **Test set**: Run SAME params on 2023-2025 (untouched data)
- Test set return must be **≥50% of train set return**
- If train=300% but test=40% → **OVERFIT, REJECT**
- Log both train and test results in leaderboard

#### C. Parameter Sensitivity Test (Jitter Test)
- Take winning params and **perturb each by ±10-20%**
- Run 5 jittered variations (e.g., delta 0.12 → test 0.10, 0.11, 0.13, 0.14)
- If performance drops >50% from a 10% param change → **FRAGILE/OVERFIT**
- Robust params should degrade gracefully, not cliff-edge
- Log: `sensitivity_score = avg_jittered_return / base_return`
- Minimum acceptable: **0.60 (40% degradation max)**

#### D. Minimum Trade Count Gate
- Any year with **<30 trades** is statistically meaningless → flag as low-confidence
- Params that achieve 200% on 12 trades = **LUCKY, NOT ROBUST**
- Target: 50+ trades per year minimum for valid results

#### E. Regime Diversity Check
- Winning trades must occur across **multiple market regimes**
- If all profits come from one 2-month window → **OVERFIT TO THAT EVENT**
- Check: profitable months ≥ 6 per year (don't cluster)
- Log: `monthly_distribution = [jan_pnl, feb_pnl, ..., dec_pnl]`

#### F. Drawdown Reality Check
- Max drawdown must be **<50% at all times**
- Max consecutive losing streak: log it, flag if >10 trades
- If system requires surviving a 60% drawdown to reach 200% → **NOT VIABLE FOR LIVE**
- Recovery time: max drawdown recovery should be <60 trading days

#### G. Overfit Score (Composite)
Calculate after every run:
```
overfit_score = (
    consistency_score * 0.25 +       # Cross-year (0-1)
    walkforward_ratio * 0.30 +        # Train vs test (0-1, capped)
    sensitivity_score * 0.25 +        # Param jitter (0-1)
    trade_count_score * 0.10 +        # Min trades met (0 or 1)
    regime_diversity_score * 0.10     # Monthly spread (0-1)
)
```
- **≥0.70**: ✅ ROBUST — proceed with confidence
- **0.50-0.69**: ⚠️ SUSPECT — investigate before accepting
- **<0.50**: ❌ OVERFIT — reject, try different approach

**Log the overfit_score with every leaderboard entry. Only params with ≥0.70 can become the "current best."**

### Step 4: Analyze & Decide
- Did it improve AND pass overfit check (≥0.70)? → Save params as new baseline
- Did it improve but fail overfit check? → Log it as "promising but fragile," investigate why
- Did it regress? → Revert, log why, try different approach
- Did it improve some years but hurt others? → Note the tradeoff, consider regime-specific params

### Step 5: Repeat
- Go back to Step 1
- NEVER STOP unless explicitly told to by Carlos
- When context gets full, save state to `output/optimization_state.json` and signal Charles for a fresh session

---

## PHASES (Work Through In Order)

### Phase 0: Build the Optimization Harness ⚡ (DO THIS FIRST)
- [ ] Create `scripts/run_optimization.py` — takes a param config, runs backtest for all years (2020-2025), outputs structured JSON results
- [ ] Create `scripts/validate_params.py` — runs ALL overfit checks (Step 3.5 A-G) automatically
- [ ] Create `output/leaderboard.json` — tracks all runs with params, results, AND overfit_score
- [ ] Create `output/optimization_log.json` — tracks hypotheses and outcomes
- [ ] Create `output/optimization_state.json` — saves current phase/progress for session recovery
- [ ] Ensure backtester can run 2020-2025 in a single script
- [ ] Ensure backtester outputs monthly P&L breakdown (needed for regime diversity check)
- [ ] Verify baseline results for all 6 years
- [ ] Benchmark: how long does a full 6-year backtest take?
- [ ] Benchmark: how long does full validation suite take? (walk-forward + jitter = ~7 extra runs)

### Phase 1: Parameter Sweep 🔍
Systematically test these parameters:
- **DTE Range**: [7-14], [14-21], [21-35], [25-50], [7-50]
- **Delta Target**: 0.08, 0.10, 0.12, 0.15, 0.20, 0.25
- **Spread Width**: $2, $3, $5, $7, $10
- **Entry Score Threshold**: 20, 25, 30, 35, 40
- **Profit Target**: 25%, 50%, 75%, hold-to-exp
- **Stop Loss**: 100%, 150%, 200%, 300%, none
- Run each combo → log to leaderboard → find optimal region

### Phase 2: Position Sizing & Compounding 💰
This is where 200% becomes possible:
- **Fixed fractional**: 2%, 5%, 10%, 15%, 20% of equity per trade
- **Kelly criterion**: Full Kelly, Half Kelly, Quarter Kelly
- **Compound mode**: Reinvest profits into larger positions
- **Scale-in**: Add to winners on pullbacks
- **Max concurrent positions**: 5, 10, 15, 20, unlimited
- Test each sizing strategy with the best params from Phase 1

### Phase 3: Regime-Specific Optimization 🌊
Different params for different market conditions:
- **Bull regime**: Aggressive bull puts, wider spreads, higher frequency
- **Bear regime**: Aggressive bear calls, tighter stops
- **High vol**: Wider spreads, bigger premiums, more conservative sizing
- **Low vol**: Iron condors, tighter strikes, higher frequency
- **Mean-reverting**: Both directions, quick profit-taking
- Build a regime-param mapping and backtest the dynamic switching

### Phase 4: Multi-Strategy 🔀
If credit spreads alone can't hit 200%:
- Add iron condors (simultaneous bull put + bear call)
- Add naked puts on strong support (higher premium)
- Add calendar spreads in low vol
- Portfolio-level optimization across strategy mix
- Correlation analysis between strategies

### Phase 5: Validation & Stress Testing ✅
- Walk-forward: Train on 2020-2023, validate on 2024-2025
- Monte Carlo: 10,000 random path simulations
- Sensitivity analysis: How fragile are the params?
- Slippage modeling: Add realistic fill assumptions
- If results hold → DECLARE VICTORY 🏆

---

## RULES FOR CLAUDE CODE

1. **Never stop the loop** — when you finish one experiment, immediately start the next
2. **Always log before running** — write your hypothesis to the optimization log
3. **Always log after running** — write results to the leaderboard
4. **ALWAYS run overfit checks** — Step 3.5 is MANDATORY, never skip it, no exceptions
5. **Only accept robust results** — overfit_score ≥ 0.70 to become "current best"
6. **Save state frequently** — update optimization_state.json so sessions can recover
7. **Think before brute-forcing** — analyze what's working and WHY before trying random combos
8. **If it looks too good, it probably is** — 500% returns with 15 trades = overfit, not alpha
9. **Compound interest is king** — Phase 2 is where the magic happens, get there fast
10. **Report breakthroughs** — if you beat 100%+ on any year WITH overfit_score ≥0.70, output a clear summary

## FILE STRUCTURE
```
pilotai-credit-spreads/
├── MASTERPLAN.md            ← This file (sacred blueprint)
├── CLAUDE.md                ← Coding guidelines
├── scripts/
│   ├── run_optimization.py  ← Optimization harness
│   └── validate_params.py   ← Overfit detection suite
├── output/
│   ├── leaderboard.json     ← All run results + overfit_scores
│   ├── optimization_log.json ← Hypotheses & outcomes
│   └── optimization_state.json ← Session recovery state
├── tasks/
│   ├── todo.md              ← Current task tracking
│   └── lessons.md           ← Learnings from mistakes
└── backtest/
    └── backtester.py        ← Core backtester (already exists)
```

---

*The machine doesn't sleep. The machine doesn't get bored. The machine tries every combination until it finds the answer. Let it run.* 🤖
