# MASTERPLAN.md — Operation Crack The Code 🎯

## Mission
Achieve **200%+ annual returns with ≤15% max drawdown** on every year from 2020-2025 through continuous, autonomous optimization — **by any means necessary**.

This is NOT limited to credit spreads. Every options strategy, every combination, every regime-switching approach is on the table. The system runs 24/7 until the goal is achieved or the mathematical ceiling is proven.

## Victory Condition
**200%+ annual return AND ≤15% max drawdown, validated across all 6 years (2020-2025).**

## Target Metrics (Tiered)
| Tier | Return | Max Drawdown | Status |
|------|--------|-------------|--------|
| 🏆 Elite | 200%+ | ≤15% | **THE GOAL** |
| ✅ Strong | 200%+ | ≤25% | Very tradeable, keep optimizing drawdown |
| ⚠️ Acceptable | 150%+ | ≤25% | Progress, not victory |
| ❌ Reject | Any | >35% | Not viable for live trading |

**Drawdown is not a ceiling to tolerate — it's a metric to MINIMIZE.**
A 180% return with 12% drawdown beats 250% with 40% drawdown. Always.

## Composite Scoring Function
```
score = (annual_return / 200) × (15 / max_drawdown) × consistency_bonus
```
- 200% return, 15% drawdown → score = 1.0 (GOAL MET)
- 300% return, 10% drawdown → score = 2.25 (exceeds goal)
- 200% return, 40% drawdown → score = 0.375 (rejected)
- Higher is better. Chase the score relentlessly.

## Current Best (Baseline)
| Year | Return | Trades | Sharpe | Max DD | Score | Notes |
|------|--------|--------|--------|--------|-------|-------|
| 2025 | +15.11% | 217 | 2.27 | TBD | TBD | Credit spreads only |
| 2024 | TBD | 128 | TBD | TBD | TBD | After sigma fix |

---

## STRATEGY ARSENAL (All Available Weapons)

### Income Strategies (Theta/Premium)
- **Credit spreads** (bull put / bear call) — current base
- **Iron condors** (simultaneous put + call spreads) — range-bound
- **Iron butterflies** — max premium at a strike
- **Calendar spreads** — theta harvesting across expirations
- **Naked puts** on strong support — higher premium, higher risk
- **Cash-secured puts** — accumulation plays
- **Covered calls** — if holding underlying

### Directional Strategies (Delta)
- **Debit spreads** — defined-risk directional bets
- **Naked calls/puts** — high conviction directional
- **Swing trades on underlying** — momentum/mean-reversion on SPY/QQQ/IWM

### Volatility Strategies (Vega)
- **Straddles/strangles** — pre-event vol explosion plays
- **Gamma lotto** — cheap 0-1 DTE OTM before catalysts (FOMC, CPI, NFP)
- **VIX plays** — trade the volatility index directly
- **Volatility crush** — sell premium into events, buy it back after

### Portfolio Strategies (Meta-Level)
- **Multi-strategy blending** — optimal mix of above strategies
- **Regime switching** — different strategy allocation per market regime
- **Dynamic sizing** — scale exposure based on conviction/vol
- **Hedging overlays** — portfolio-level tail risk protection

**Every combination is valid. The optimizer decides what works.**

---

## THE ENGINE (Autonomous Optimization Loop)

### Architecture
```
┌──────────────────────────────────────────┐
│        STRATEGY DISCOVERY ENGINE          │
│                                           │
│  ┌─────────────────────────────────────┐  │
│  │ Layer 1: Single Strategy Optimizer  │  │
│  │ - Optimize each strategy in isolation│  │
│  │ - Bayesian/genetic search           │  │
│  │ - Find best params per strategy     │  │
│  └────────────────┬────────────────────┘  │
│                   ▼                       │
│  ┌─────────────────────────────────────┐  │
│  │ Layer 2: Portfolio Blender          │  │
│  │ - Combine top strategies            │  │
│  │ - Optimize allocation weights       │  │
│  │ - Uncorrelated strategies = low DD  │  │
│  └────────────────┬────────────────────┘  │
│                   ▼                       │
│  ┌─────────────────────────────────────┐  │
│  │ Layer 3: Regime Switcher            │  │
│  │ - Detect market regime (bull/bear/  │  │
│  │   high-vol/low-vol/sideways)        │  │
│  │ - Dynamic allocation per regime     │  │
│  │ - This is where drawdown dies       │  │
│  └────────────────┬────────────────────┘  │
│                   ▼                       │
│  ┌─────────────────────────────────────┐  │
│  │ Validation Gate (MANDATORY)         │  │
│  │ - Cross-year consistency            │  │
│  │ - Walk-forward validation           │  │
│  │ - Parameter sensitivity (jitter)    │  │
│  │ - Regime diversity                  │  │
│  │ - Overfit score ≥ 0.70 to pass     │  │
│  └─────────────────────────────────────┘  │
│                                           │
│  🎯 STOP WHEN: score ≥ 1.0 all years     │
│  📊 REPORT: Every 100 runs → Telegram     │
│  🔄 NEVER STOP until goal or ceiling      │
└──────────────────────────────────────────┘
```

### The Loop (Runs Forever)

#### Step 1: Pick Next Experiment
- Read `output/leaderboard.json` — current best params & score
- Read `output/optimization_log.json` — what's been tried
- Use intelligent search (Bayesian optimization / genetic algorithms)
- Log hypothesis BEFORE running

#### Step 2: Run Backtest
- Execute across all 6 years (2020-2025)
- Output: annual return, max drawdown, monthly P&L, trade log, Sharpe
- Calculate composite score

#### Step 3: Validate (MANDATORY — No Exceptions)

**A. Cross-Year Consistency**
- Must be profitable in ≥5 of 6 years
- `consistency_score = years_profitable / 6` (min: 0.83)

**B. Walk-Forward Validation**
- Train: 2020-2022 → Test: 2023-2025
- Test return must be ≥50% of train return

**C. Parameter Sensitivity (Jitter Test)**
- Perturb each param ±10-20%, run 5 variations
- `sensitivity_score = avg_jittered / base` (min: 0.60)
- If 10% param change = 50%+ performance drop → FRAGILE/OVERFIT

**D. Minimum Trade Count**
- <30 trades/year = statistically meaningless → reject
- Target: 50+ trades/year

**E. Regime Diversity**
- Profits must span ≥6 months per year (no clustering)
- Log monthly P&L distribution

**F. Drawdown Reality Check**
- Max drawdown ≤15% (goal) / absolute reject >35%
- Max consecutive losers: flag if >10
- Recovery time: <30 trading days

**G. Composite Overfit Score**
```
overfit_score = (
    consistency    * 0.25 +   # Cross-year (0-1)
    walkforward    * 0.30 +   # Train vs test (0-1)
    sensitivity    * 0.25 +   # Jitter (0-1)
    trade_count    * 0.10 +   # Min trades (0 or 1)
    regime_diverse * 0.10     # Monthly spread (0-1)
)
```
- ≥0.70: ✅ ROBUST — accept
- 0.50-0.69: ⚠️ SUSPECT — investigate
- <0.50: ❌ OVERFIT — reject

#### Step 4: Log & Decide
- Beat current best AND overfit ≥0.70? → New baseline 🏆
- Beat but failed overfit? → "Promising but fragile" — investigate
- Regressed? → Revert, log why, try different direction

#### Step 5: Repeat Forever
- Never stop unless Carlos says stop
- Every 100 runs → Telegram summary to Carlos
- When context fills → save state to `output/optimization_state.json`

---

## PHASES

### Phase 0: Build the Strategy Discovery Engine ⚡ (CURRENT)
**This is no longer just a backtester wrapper. This is the full engine.**

#### 0.1 — Data Inventory & Preparation
- [ ] Audit all historical data from Polygon (date ranges per ticker)
- [ ] Verify SPY/QQQ/IWM daily OHLCV: 2020-01-01 through 2025-12-31
- [ ] Verify VIX data availability
- [ ] Verify options chain data (strikes, premiums, greeks) for delta estimation
- [ ] Check intraday vs daily granularity
- [ ] Document gaps in `output/data_audit.json`
- [ ] Backfill script if gaps exist
- [ ] Economic calendar data (FOMC, CPI, NFP, GDP dates 2020-2025) for gamma plays

#### 0.2 — Strategy Module Architecture
- [ ] Design pluggable strategy interface — every strategy implements same API:
  - `generate_signals(market_data, params) → List[Signal]`
  - `size_position(signal, portfolio, params) → Position`
  - `manage_position(position, market_data, params) → Action`
- [ ] Implement strategy modules:
  - [ ] `strategies/credit_spread.py` (port existing backtester)
  - [ ] `strategies/iron_condor.py`
  - [ ] `strategies/gamma_lotto.py`
  - [ ] `strategies/straddle_strangle.py`
  - [ ] `strategies/debit_spread.py`
  - [ ] `strategies/calendar_spread.py`
  - [ ] `strategies/momentum_swing.py`
- [ ] Each strategy defines its own parameter space for optimization
- [ ] All strategies share common position/portfolio tracking

#### 0.3 — Portfolio Backtester (Multi-Strategy)
- [ ] Build portfolio-level backtester that runs multiple strategies simultaneously
- [ ] Shared equity tracking — all strategies draw from same account
- [ ] Position limits (max concurrent, max per strategy, max total risk)
- [ ] Portfolio-level P&L, drawdown, Sharpe calculation
- [ ] Monthly P&L breakdown per strategy AND combined
- [ ] Trade log with entry/exit/strategy/pnl per trade
- [ ] Benchmark: full 6-year multi-strategy backtest timing

#### 0.4 — Optimization Engine
- [ ] Implement Bayesian optimization (or genetic algorithm) for param search
- [ ] Support optimizing across:
  - Individual strategy params
  - Strategy allocation weights
  - Regime-switching thresholds
- [ ] `scripts/run_optimization.py` — takes config, runs backtest, outputs JSON
- [ ] `scripts/validate_params.py` — runs ALL overfit checks automatically
- [ ] `output/leaderboard.json` — all runs with params, results, score, overfit_score
- [ ] `output/optimization_log.json` — hypotheses and outcomes
- [ ] `output/optimization_state.json` — session recovery state

#### 0.5 — Regime Detection
- [ ] Build regime classifier using VIX levels + price trends:
  - Bull (SPY trending up, VIX < 20)
  - Bear (SPY trending down, VIX > 25)
  - High Vol (VIX > 30, any direction)
  - Low Vol Sideways (VIX < 15, no trend)
  - Crash (VIX > 40, sharp decline)
- [ ] Tag each trading day 2020-2025 with its regime
- [ ] Enable regime-conditional strategy allocation

#### 0.6 — Autonomous Runner
- [ ] Build `scripts/endless_optimizer.py` — the daemon
- [ ] Reads current state, picks next experiment, runs it, logs, repeats
- [ ] Intelligent experiment selection (not random)
- [ ] Auto-escalation: if single strategies plateau, move to blending
- [ ] If blending plateaus, move to regime switching
- [ ] Progress reporting every 100 runs
- [ ] Graceful state saving for session recovery

### Phase 1: Single Strategy Optimization 🔍
- Optimize each strategy individually across full param space
- Find the ceiling of each strategy alone
- Rank strategies by score
- Identify which strategies excel in which regimes

### Phase 2: Position Sizing & Compounding 💰
- Fixed fractional: 2%, 5%, 10%, 15%, 20% per trade
- Kelly criterion variants (full, half, quarter)
- Compound mode (reinvest profits)
- Max concurrent positions optimization
- This is where 200% becomes possible

### Phase 3: Portfolio Blending 🔀
- Combine top strategies from Phase 1
- Optimize allocation weights
- Uncorrelated strategies reduce drawdown dramatically
- Find the blend that maximizes score (return/drawdown ratio)

### Phase 4: Regime Switching 🌊
- Dynamic allocation based on detected regime
- Different strategy mix for bull/bear/high-vol/low-vol/crash
- This is where drawdown drops to ≤15%
- Train regime model on 2020-2022, validate on 2023-2025

### Phase 5: Validation & Stress Testing ✅
- Full walk-forward validation
- Monte Carlo: 10,000 random path simulations
- Slippage & fill modeling (realistic execution)
- Tail risk scenarios (flash crash, circuit breakers)
- If results hold → **DECLARE VICTORY** 🏆

---

## RULES FOR CLAUDE CODE

1. **Never stop the loop** — finish one experiment, immediately start the next
2. **Always log before running** — write hypothesis to optimization log
3. **Always log after running** — write results to leaderboard with score
4. **ALWAYS validate** — Step 3 overfit checks are MANDATORY, never skip
5. **Only accept robust results** — overfit_score ≥ 0.70 to become "current best"
6. **Save state frequently** — optimization_state.json for session recovery
7. **Think before brute-forcing** — analyze what's working and WHY
8. **If it looks too good, it is** — 500% with 15 trades = overfit, not alpha
9. **Minimize drawdown obsessively** — 15% max DD is the goal, not 50%
10. **Report breakthroughs** — score ≥ 0.5 on any year = output clear summary
11. **Use ALL strategies** — credit spreads are just one weapon. Deploy the full arsenal.
12. **Blend for drawdown** — single strategies have high DD. Blending uncorrelated strategies is the key to low DD + high returns.

## FILE STRUCTURE
```
pilotai-credit-spreads/
├── MASTERPLAN.md               ← This file (sacred blueprint)
├── CLAUDE.md / CLAUDE-LOCAL.md ← Coding guidelines
├── strategies/
│   ├── base.py                 ← Strategy interface
│   ├── credit_spread.py        ← Bull put / bear call spreads
│   ├── iron_condor.py          ← Simultaneous put + call spreads
│   ├── gamma_lotto.py          ← Cheap OTM pre-catalyst
│   ├── straddle_strangle.py    ← Vol explosion plays
│   ├── debit_spread.py         ← Directional defined-risk
│   ├── calendar_spread.py      ← Theta across expirations
│   └── momentum_swing.py       ← Trend/mean-reversion on underlying
├── engine/
│   ├── portfolio_backtester.py ← Multi-strategy portfolio sim
│   ├── regime_detector.py      ← Market regime classification
│   ├── optimizer.py            ← Bayesian/genetic param search
│   └── validator.py            ← Overfit detection suite
├── scripts/
│   ├── run_optimization.py     ← Single experiment runner
│   ├── validate_params.py      ← Validation suite
│   └── endless_optimizer.py    ← THE DAEMON (runs forever)
├── output/
│   ├── leaderboard.json        ← All runs + scores + overfit
│   ├── optimization_log.json   ← Hypotheses & outcomes
│   ├── optimization_state.json ← Session recovery
│   └── data_audit.json         ← Data availability audit
├── tasks/
│   ├── todo.md                 ← Current task tracking
│   └── lessons.md              ← Learnings
└── backtest/
    └── backtester.py           ← Original backtester (to be ported)
```

---

*By any means necessary. Every strategy. Every combination. Every regime. The engine runs until it cracks the code or proves the ceiling. 200% returns. 15% max drawdown. No excuses.* 🎯
