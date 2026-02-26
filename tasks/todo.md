# TODO — Operation Crack The Code
# Last Updated: 2026-02-26
# Current Phase: Phase 0 — Build Optimization Harness

---

## Phase 0: Build the Optimization Harness ⚡

### 0.1 — Data Inventory & Gap Analysis
- [ ] Audit what historical data we have from Polygon (exact date ranges per ticker)
- [ ] Verify SPY daily OHLCV availability: 2020-01-01 through 2025-12-31
- [ ] Verify QQQ daily OHLCV availability: 2020-01-01 through 2025-12-31
- [ ] Verify IWM daily OHLCV availability: 2020-01-01 through 2025-12-31
- [ ] Verify VIX data availability for same range
- [ ] Verify options chain snapshots or sufficient data for delta estimation per date
- [ ] Check: do we have intraday data? Or daily only? (affects DTE precision)
- [ ] Document all data gaps in `output/data_audit.json`
- [ ] If gaps exist: write a script to backfill from Polygon API
- [ ] Estimate Polygon API rate limits & cost for any backfill needed

### 0.2 — Backtester Capability Audit
- [ ] Read through `backtest/backtester.py` end-to-end — document every parameter it currently accepts
- [ ] List which parameters are hardcoded vs configurable
- [ ] Identify what the backtester currently CANNOT do that we need:
  - [ ] Can it run multiple years in a single invocation?
  - [ ] Does it support compounding (reinvesting profits)?
  - [ ] Does it support variable position sizing (% of equity)?
  - [ ] Does it support profit-taking before expiration?
  - [ ] Does it support iron condors (simultaneous put + call spreads)?
  - [ ] Does it output monthly P&L breakdown?
  - [ ] Does it output per-trade log with entry/exit dates and prices?
  - [ ] Does it track max drawdown and drawdown duration?
  - [ ] Does it track consecutive win/loss streaks?
- [ ] Document all findings in `output/backtester_audit.md`
- [ ] Prioritize missing features by impact on optimization goal

### 0.3 — Backtester Upgrades (Based on Audit)
- [ ] Make ALL strategy parameters configurable via a single params dict/JSON
  ```python
  params = {
      "dte_min": 25, "dte_max": 50,
      "delta_target": 0.12,
      "spread_width": 5,
      "entry_score_threshold": 30,
      "profit_target_pct": 0.50,      # Take profit at 50% of credit
      "stop_loss_pct": 2.0,           # Stop at 200% of credit
      "position_size_mode": "fixed",   # fixed | pct_equity | kelly
      "position_size_value": 4,        # 4 contracts or 5% equity
      "max_concurrent": 10,
      "compound": False,
      "direction": "both",             # bull_put | bear_call | both
      "tickers": ["SPY", "QQQ", "IWM"]
  }
  ```
- [ ] Add compounding mode: track running equity, size positions as % of current equity
- [ ] Add profit-taking: close position when spread value drops to X% of entry credit
- [ ] Add monthly P&L breakdown to output
- [ ] Add per-trade detailed log: `{date, ticker, direction, strikes, credit, exit_date, exit_reason, pnl, equity_after}`
- [ ] Add drawdown tracking: running max drawdown, peak-to-trough, recovery days
- [ ] Add consecutive streak tracking: max wins in a row, max losses in a row
- [ ] Ensure backtester returns structured dict (not just prints) for programmatic use
- [ ] Write unit tests for each new feature
- [ ] Verify backtester still produces same baseline results after refactor

### 0.4 — Optimization Script (`scripts/run_optimization.py`)
- [ ] Create script that accepts a param config (JSON file or CLI args)
- [ ] Runs backtester for each year independently: 2020, 2021, 2022, 2023, 2024, 2025
- [ ] Collects per-year results into unified output:
  ```json
  {
      "run_id": "run_001",
      "timestamp": "2026-02-26T15:30:00Z",
      "params": { ... },
      "results": {
          "2020": {"return_pct": 45.2, "max_dd_pct": -18.3, "trades": 87, "sharpe": 1.8, "win_rate": 0.72, "monthly_pnl": [...], "max_streak_loss": 4},
          "2021": { ... },
          ...
      },
      "summary": {
          "avg_return": 112.5,
          "min_return": 45.2,
          "max_return": 234.1,
          "worst_dd": -28.4,
          "years_profitable": 6,
          "consistency_score": 1.0
      }
  }
  ```
- [ ] Auto-appends to `output/leaderboard.json`
- [ ] Prints clear summary table to stdout after each run
- [ ] Handles errors gracefully — if one year fails, still runs the others
- [ ] Supports `--dry-run` flag to show what would run without executing
- [ ] Supports `--years 2020,2021` flag to run subset of years (faster iteration)

### 0.5 — Validation Script (`scripts/validate_params.py`)
- [ ] Accepts a param config (same format as optimization script)
- [ ] Runs ALL 7 overfit checks from MASTERPLAN Step 3.5:

#### Check A: Cross-Year Consistency
- [ ] Run backtest for all 6 years with given params
- [ ] Count profitable years
- [ ] Score: `years_profitable / 6` — must be ≥ 0.83

#### Check B: Walk-Forward Validation
- [ ] Run 1: Optimize/run on 2020-2022 (train set)
- [ ] Run 2: Run SAME params on 2023-2025 (test set)
- [ ] Score: `test_avg_return / train_avg_return` — must be ≥ 0.50
- [ ] Also run reverse: train 2023-2025, test 2020-2022 (double validation)

#### Check C: Parameter Sensitivity (Jitter Test)
- [ ] For each numeric param, generate ±10% and ±20% variations
- [ ] Run 5 jittered param sets through full backtest
- [ ] Score: `avg_jittered_return / base_return` — must be ≥ 0.60
- [ ] Flag any single param where ±10% causes >50% return drop ("cliff parameter")

#### Check D: Trade Count Gate
- [ ] Check each year has ≥30 trades
- [ ] Score: 1.0 if all years pass, 0.0 if any year < 30

#### Check E: Regime Diversity
- [ ] Check monthly P&L distribution per year
- [ ] Score: `months_profitable / 12` averaged across years — flag if <0.50
- [ ] Flag if >50% of annual P&L comes from a single month

#### Check F: Drawdown Reality
- [ ] Check max drawdown < 50% for all years
- [ ] Check max drawdown recovery < 60 trading days
- [ ] Check max consecutive losses < 15 trades
- [ ] Score: 1.0 if all pass, degrade proportionally

#### Check G: Composite Score
- [ ] Calculate weighted composite from A-F
- [ ] Output: `overfit_score` with breakdown of each component
- [ ] Verdict: ROBUST (≥0.70) | SUSPECT (0.50-0.69) | OVERFIT (<0.50)

- [ ] Output full validation report as JSON
- [ ] Print human-readable summary with pass/fail per check
- [ ] Integration: `run_optimization.py` calls `validate_params.py` automatically after every run

### 0.6 — Leaderboard & State Management
- [ ] `output/leaderboard.json`: Array of all runs, sorted by avg_return descending
  - Each entry includes: run_id, timestamp, params, results, summary, overfit_score, verdict
  - Tag "current_best" on the highest avg_return with overfit_score ≥ 0.70
- [ ] `output/optimization_log.json`: Array of experiment entries
  ```json
  {
      "experiment_id": "exp_001",
      "timestamp": "2026-02-26T15:30:00Z",
      "phase": "Phase 1",
      "hypothesis": "Tighter DTE (7-14) will increase trade frequency and returns in low-vol years",
      "params_changed": {"dte_min": 7, "dte_max": 14},
      "baseline_params": { ... },
      "outcome": "Improved 2024 from 45% to 78%, but 2022 dropped from 30% to -5%",
      "overfit_score": 0.55,
      "verdict": "SUSPECT",
      "decision": "Rejected — 2022 regression too severe. Try regime-specific DTE instead.",
      "next_action": "Test DTE 7-14 only during low-vol regimes, keep 25-50 for high-vol"
  }
  ```
- [ ] `output/optimization_state.json`: Current session state for recovery
  ```json
  {
      "current_phase": "Phase 1",
      "current_experiment": "exp_042",
      "total_runs": 41,
      "best_run_id": "run_028",
      "best_avg_return": 89.4,
      "best_overfit_score": 0.74,
      "next_action": "Test spread_width=$3 with current best params",
      "params_queue": [ ... ],
      "last_updated": "2026-02-27T03:45:00Z"
  }
  ```
- [ ] Write helper functions: `load_state()`, `save_state()`, `load_leaderboard()`, `append_to_leaderboard()`, `get_current_best()`

### 0.7 — Baseline Run & Benchmarking
- [ ] Run full 6-year backtest with current default params
- [ ] Record as run_000 (baseline) in leaderboard
- [ ] Run full validation suite on baseline
- [ ] Time it: how many minutes per single 6-year run?
- [ ] Time it: how many minutes for full validation (run + 7 jitter runs + walk-forward)?
- [ ] Calculate: how many experiments can we run per 24 hours?
- [ ] Document all benchmarks in `output/benchmarks.md`

### 0.8 — Integration Test
- [ ] Run `scripts/run_optimization.py` end-to-end with baseline params
- [ ] Verify leaderboard.json is created and correct
- [ ] Run `scripts/validate_params.py` on baseline
- [ ] Verify overfit_score is calculated correctly
- [ ] Verify optimization_state.json saves and loads correctly
- [ ] Simulate a "session recovery": load state, pick next experiment, run it
- [ ] Verify the full loop works: pick experiment → run → validate → log → pick next

**Phase 0 Definition of Done:** The full loop (pick → run → validate → log → repeat) executes autonomously with zero manual intervention. Claude Code can read state, decide what to try next, run it, validate it, and continue indefinitely.

---

## Phase 1: Parameter Sweep 🔍
_Do not start until Phase 0 is FULLY complete and integration tested._

### 1.1 — Single-Parameter Sweeps (One at a time, others at baseline)
- [ ] DTE Range sweep: [7-14], [10-20], [14-28], [21-35], [25-50], [30-60], [7-50]
- [ ] Delta Target sweep: 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30
- [ ] Spread Width sweep: $1, $2, $3, $5, $7, $10, $15
- [ ] Entry Threshold sweep: 15, 20, 25, 30, 35, 40, 50
- [ ] Profit Target sweep: 25%, 40%, 50%, 65%, 75%, hold-to-exp
- [ ] Stop Loss sweep: 75%, 100%, 150%, 200%, 300%, none
- [ ] Direction sweep: bull_put only, bear_call only, both, regime-adaptive
- [ ] For each sweep: plot return curve vs parameter value, find optimal region
- [ ] Document findings: which params have biggest impact on returns?

### 1.2 — Multi-Parameter Grid Search (Top 3 most impactful params)
- [ ] Identify top 3 params from 1.1 (highest sensitivity)
- [ ] Run grid search across those 3 dimensions
- [ ] Estimated runs: ~200-500 depending on grid resolution
- [ ] Find global optimum region
- [ ] Run full validation on top 5 grid results

### 1.3 — Phase 1 Analysis
- [ ] Create parameter heatmaps (return vs param pairs)
- [ ] Identify "safe zones" (robust param regions vs cliff edges)
- [ ] Document the optimal param set with full validation
- [ ] Update MASTERPLAN with findings
- [ ] Set this as new baseline for Phase 2

---

## Phase 2: Position Sizing & Compounding 💰
_This is where 200% becomes possible._

### 2.1 — Fixed Fractional Sizing
- [ ] Test: 1%, 2%, 3%, 5%, 7%, 10%, 15%, 20% of equity per trade
- [ ] With best params from Phase 1
- [ ] Track: return, max drawdown, risk of ruin
- [ ] Find the sizing sweet spot (max return with <50% drawdown)

### 2.2 — Kelly Criterion
- [ ] Calculate theoretical Kelly fraction from historical win rate & avg win/loss
- [ ] Test: Full Kelly, 3/4 Kelly, 1/2 Kelly, 1/4 Kelly
- [ ] Compare to fixed fractional results
- [ ] Kelly should theoretically maximize long-term growth rate

### 2.3 — Compound vs Non-Compound
- [ ] Run same params with compounding ON vs OFF
- [ ] Compounding: position size scales with equity (5% of current equity, not starting)
- [ ] Quantify the difference — this is where exponential growth kicks in
- [ ] Check: does compounding make drawdowns worse? By how much?

### 2.4 — Max Concurrent Positions
- [ ] Test: 3, 5, 8, 10, 15, 20, unlimited concurrent positions
- [ ] With compounding ON
- [ ] More positions = more capital deployed = faster compounding BUT more correlated risk
- [ ] Find optimal concurrent count

### 2.5 — Phase 2 Synthesis
- [ ] Combine best sizing + compounding + concurrency with Phase 1 params
- [ ] Run full validation suite
- [ ] Are we at 200%+ on any year? On all years?
- [ ] Update MASTERPLAN with results

---

## Phase 3: Regime-Specific Optimization 🌊
_Different markets need different strategies._

### 3.1 — Regime Detection Accuracy
- [ ] Verify regime detector correctly labels historical periods
- [ ] 2020: COVID crash (high-vol/bear) → recovery (bull)
- [ ] 2021: Strong bull, low vol
- [ ] 2022: Bear market, rising rates
- [ ] 2023: Recovery, mixed
- [ ] 2024: Bull, low vol
- [ ] 2025: Tariff volatility, mixed
- [ ] If detector is wrong → fix it before optimizing per-regime

### 3.2 — Per-Regime Parameter Optimization
- [ ] For each regime type: optimize params independently
- [ ] Bull: likely bull puts, wider spreads, aggressive sizing
- [ ] Bear: likely bear calls, tighter stops, smaller sizing
- [ ] High vol: wider spreads, bigger premiums
- [ ] Low vol: tighter strikes, higher frequency, iron condors
- [ ] Mean-reverting: both directions, quick profit-taking

### 3.3 — Dynamic Switching Backtest
- [ ] Build regime-aware backtester: switches params based on detected regime
- [ ] Run full 6-year backtest with dynamic switching
- [ ] Compare to static best params from Phase 2
- [ ] Validate: does switching improve consistency across years?

---

## Phase 4: Multi-Strategy 🔀
_Only if Phases 1-3 can't reach 200% consistently._

### 4.1 — Iron Condors
- [ ] Add iron condor support to backtester (simultaneous bull put + bear call)
- [ ] Optimize iron condor params independently
- [ ] Test: when to use iron condor vs directional spread

### 4.2 — Strategy Portfolio
- [ ] Run multiple strategies simultaneously
- [ ] Allocate capital across strategies
- [ ] Optimize allocation percentages
- [ ] Check correlation between strategy returns

---

## Phase 5: Final Validation ✅
_Only when we have a candidate that hits 200%+ on all years._

### 5.1 — Full Overfit Suite (Extended)
- [ ] Walk-forward with multiple split points (not just 2020-22 / 2023-25)
- [ ] Monte Carlo: 10,000 shuffled trade simulations
- [ ] Bootstrap confidence intervals on annual returns
- [ ] Slippage modeling: add $0.01-0.03 per leg fill cost
- [ ] Commission modeling: realistic broker fees

### 5.2 — Documentation
- [ ] Generate final HTML report with all results
- [ ] Document the winning strategy completely
- [ ] Create a "how to run live" guide
- [ ] Archive all optimization data

---

## Completed ✅
- [x] Fixed constant σ=25% → realized vol (ATR-based) — 2026-02-26
- [x] Removed 6 max positions cap — 2026-02-26
- [x] Generated backtest report v2 (2020-2025) — 2026-02-26
- [x] Deployed CLAUDE.md to project — 2026-02-26

---

## Decision Log
| Date | Decision | Reason |
|------|----------|--------|
| 2026-02-26 | Target 200%+ all years 2020-2025 | Carlos's directive |
| 2026-02-26 | Mandatory overfit checks every run | Prevent curve-fitting false results |
| 2026-02-26 | Phase order: harness → sweep → sizing → regime → multi | Sizing (Phase 2) is highest-leverage for hitting 200% |
