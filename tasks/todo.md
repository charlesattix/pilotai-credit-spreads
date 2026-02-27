# TODO — Operation Crack The Code
# Last Updated: 2026-02-27
# Current Phase: Phase 0 — Build the Strategy Discovery Engine

---

## Phase 0: Build the Strategy Discovery Engine ⚡

### 0.1 — Data Inventory & Preparation
- [x] Audit all historical data from Polygon (date ranges per ticker)
  - Result: No Polygon API key set, no options_cache.db exists, data/ dir missing
- [x] Verify SPY/QQQ/IWM daily OHLCV: 2020-01-01 through 2025-12-31
  - Result: All 3 tickers + VIX + TLT have 1507 gap-free rows (2020-01-02 to 2025-12-30) via yfinance
- [x] Verify VIX data availability
  - Result: ^VIX has 1507 rows, gap-free, 0% null closes
- [x] Verify options chain data (strikes, premiums, greeks)
  - Result: BLOCKED — no POLYGON_API_KEY, no options_cache.db. Can use Black-Scholes synthetic pricing as fallback.
- [x] Check intraday vs daily granularity
  - Result: Daily OHLCV available for all tickers. Intraday limited to last 60 days via yfinance. Polygon needed for historical intraday.
- [x] Document gaps in `output/data_audit.json`
  - Result: Full audit written with 8 missing data items, 6 recommendations, 4 backfill items
- [x] Backfill script if gaps exist
  - Result: No OHLCV gaps found. Backfill needed for: FOMC dates 2020-2024, options cache, economic calendar history. Documented in audit.
- [x] Economic calendar data (FOMC, CPI, NFP, GDP dates 2020-2025)
  - Result: FOMC covers 2025-2026 only (17 dates). Algorithmic calendar covers current+next year only. Need ~40 FOMC dates + ~180 CPI/PPI/NFP dates for 2020-2024.

### 0.2 — Strategy Module Architecture
- [x] Design pluggable strategy interface (generate_signals, size_position, manage_position)
  - Result: BaseStrategy ABC in strategies/base.py with Signal, Position, TradeLeg, MarketSnapshot, PortfolioState, ParamDef
- [x] Implement `strategies/base.py` — abstract strategy class
  - Result: ABC + all data types + enums (TradeDirection, PositionAction, LegType)
- [x] Implement `strategies/credit_spread.py` (port existing backtester)
  - Result: Ported MA trend filter, momentum filter, BS pricing from backtester.py. 12 params.
- [x] Implement `strategies/iron_condor.py`
  - Result: RSI + IV rank filters, dual-wing construction, 12 params.
- [x] Implement `strategies/gamma_lotto.py`
  - Result: Event-driven OTM debit plays, FOMC/CPI/NFP/PPI/GDP events, 0.5% risk cap. 10 params.
- [x] Implement `strategies/straddle_strangle.py`
  - Result: Long pre-event / short post-event vol trading, IV boost/crush modeling. 10 params.
- [x] Implement `strategies/debit_spread.py`
  - Result: Trend-following bull call / bear put debit spreads, momentum + MA filter. 10 params.
- [x] Implement `strategies/calendar_spread.py`
  - Result: Front/back month time decay, low-vol preference, BS pricing across expirations. 9 params.
- [x] Implement `strategies/momentum_swing.py`
  - Result: Equity + ITM debit spread modes, EMA cross + ADX + RSI + breakout detection. 12 params.
- [x] Each strategy defines its own parameter space
  - Result: 75 total params across 7 strategies. All validated with ParamDef schema.
- [x] Also: strategies/pricing.py (BS helpers), strategies/__init__.py (registry), shared/economic_calendar.py (years param fix)

### 0.3 — Portfolio Backtester (Multi-Strategy)
- [x] Build portfolio-level backtester (multiple strategies, shared equity)
  - Result: engine/portfolio_backtester.py — PortfolioBacktester class with day loop, snapshot builder, P&L calculation
- [x] Position limits (max concurrent, max per strategy, max total risk)
  - Result: _can_accept() enforces max_positions=10, max_per_strategy=5, max_portfolio_risk_pct=40%, no duplicate ticker+strategy
- [x] Portfolio P&L, drawdown, Sharpe calculation
  - Result: _calculate_results() computes Sharpe, max drawdown, profit factor, win/loss streaks, equity curve
- [x] Monthly P&L breakdown per strategy AND combined
  - Result: monthly_pnl dict + per_strategy breakdown in results JSON
- [x] Per-trade log (entry/exit/strategy/pnl)
  - Result: Full trade log with id, strategy, ticker, direction, dates, exit_reason, pnl, return_pct, legs
- [x] Benchmark: full 6-year multi-strategy timing
  - Result: 1046 trades across 7 strategies, 3 tickers, 2020-2025. All 7 strategies produce trades. JSON output to output/portfolio_backtest_*.json
- [x] Also: engine/__init__.py, scripts/run_portfolio_backtest.py (CLI with argparse)

### 0.4 — Optimization Engine
- [x] Implement Bayesian optimization or genetic algorithm
  - Result: engine/optimizer.py — Optimizer class with random search + Bayesian-lite exploitation (sample_params, sample_near_best, suggest). Pure Python + numpy, no scipy/optuna.
- [x] Support optimizing: strategy params, allocation weights, regime thresholds
  - Result: Optimizer samples from per-strategy ParamDef spaces. Supports single-strategy or multi-strategy optimization. suggest() uses explore/exploit (random first 10, then 70% perturb best + 30% random).
- [x] `scripts/run_optimization.py` — config → backtest → JSON results
  - Result: Refactored to use PortfolioBacktester. Supports --strategies flag, --strategy-params JSON, --auto N for auto-experiments. Removed old single-strategy Backtester dependency.
- [x] `scripts/validate_params.py` — all overfit checks automated
  - Result: Check C (jitter) refactored to use PortfolioBacktester via run_fn callback. CLI updated for multi-strategy. All 7 checks (A-G) working.
- [x] `output/leaderboard.json` — runs + scores + overfit_scores
  - Result: Leaderboard records multi-strategy configs, per-strategy params, combined + yearly results.
- [x] `output/optimization_log.json` — hypotheses & outcomes
  - Result: Pre/post experiment logging with hypothesis, strategies, outcome.
- [x] `output/optimization_state.json` — session recovery
  - Result: Tracks total_runs, best_run_id, best_avg_return, best_overfit_score.

### 0.5 — Regime Detection
- [ ] Build regime classifier (VIX levels + price trends)
- [ ] Regimes: Bull, Bear, High Vol, Low Vol Sideways, Crash
- [ ] Tag every trading day 2020-2025 with regime
- [ ] Enable regime-conditional strategy allocation

### 0.6 — Autonomous Runner (The Daemon)
- [ ] Build `scripts/endless_optimizer.py`
- [ ] Intelligent experiment selection (not random)
- [ ] Auto-escalation: single → blending → regime switching
- [ ] Progress reporting every 100 runs
- [ ] Graceful state saving for session recovery

---

## Phase 1: Single Strategy Optimization 🔍
- [ ] Optimize each strategy individually across full param space
- [ ] Find ceiling of each strategy alone
- [ ] Rank strategies by composite score
- [ ] Identify regime-strategy affinity

## Phase 2: Position Sizing & Compounding 💰
- [ ] Test fixed fractional: 2%, 5%, 10%, 15%, 20%
- [ ] Kelly criterion variants
- [ ] Compound mode (reinvest profits)
- [ ] Max concurrent positions optimization

## Phase 3: Portfolio Blending 🔀
- [ ] Combine top strategies, optimize weights
- [ ] Exploit uncorrelated strategies for low drawdown
- [ ] Find max-score blend

## Phase 4: Regime Switching 🌊
- [ ] Dynamic allocation per regime
- [ ] Train on 2020-2022, validate 2023-2025
- [ ] This is where drawdown hits ≤15%

## Phase 5: Validation & Stress Testing ✅
- [ ] Walk-forward validation
- [ ] Monte Carlo (10,000 paths)
- [ ] Slippage & fill modeling
- [ ] Tail risk scenarios
- [ ] DECLARE VICTORY 🏆
