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
- [x] Build regime classifier (VIX levels + price trends)
  - Result: engine/regime.py — RegimeClassifier with classify() and classify_series(). Rule-based: VIX thresholds + 50-day MA trend slope.
- [x] Regimes: Bull, Bear, High Vol, Low Vol Sideways, Crash
  - Result: Regime enum (bull/bear/high_vol/low_vol/crash) with REGIME_INFO strategy recommendations per regime.
- [x] Tag every trading day 2020-2025 with regime
  - Result: classify_series() tags full date range. summarize() reports distribution + transitions.
- [x] Enable regime-conditional strategy allocation
  - Result: MarketSnapshot.regime field set each day in PortfolioBacktester. Strategies can check snapshot.regime in generate_signals().

### 0.6 — Autonomous Runner (The Daemon)
- [x] Build `scripts/endless_optimizer.py`
  - Result: 3-phase daemon. Phase 1: single-strategy round-robin optimization. Phase 2: multi-strategy blending with best-of Phase 1. Phase 3: regime-conditional with broad exploration.
- [x] Intelligent experiment selection (not random)
  - Result: Uses Optimizer.suggest() (Bayesian-lite: explore first 10, then 70% exploit + 30% explore). Phase 2 weights strategies by Phase 1 scores.
- [x] Auto-escalation: single → blending → regime switching
  - Result: Plateau detection over 20-run window. Phase 1 → 2 after 30+ runs plateau. Phase 2 → 3 after 20+ blending runs plateau.
- [x] Progress reporting every 100 runs
  - Result: print_progress() shows per-strategy run counts, best scores, phase stats. Configurable interval via --report-interval.
- [x] Graceful state saving for session recovery
  - Result: SIGINT/SIGTERM handler saves state before exit. State includes phase1_history, phase2_history, phase3_history per strategy.

---

## Phase 0.7: PRICING REALISM — Fix All Critical Weaknesses 🚨 (CURRENT PRIORITY)

### A. Bid-Ask Spread Modeling (CRITICAL) ✅ DONE
- [x] Add bid-ask spread model to strategies/pricing.py
  - Result: estimate_bid_ask_spread(), get_fill_price(), estimate_spread_value_with_friction()
  - Base $0.03 ATM → $0.12 deep OTM, 1.3x for short DTE, min 8% of price, capped 40%
- [x] SPY OTM spread: $0.05-$0.20, scaling with DTE/moneyness
  - Result: Verified $0.12-$0.24 for typical SPY OTM options
- [x] Entry fills at bid (selling) / ask (buying) — not mid-price
  - Result: All 7 strategies updated to use get_fill_price() at entry
- [x] Verify win rate drops from 99.8% to realistic range
  - Result: Credit spread: 93.6% win, 117.5% return (was 99.8%/1163%)

### B. Slippage & Market Impact (CRITICAL) ✅ DONE (via bid-ask model)
- [x] Centralized slippage via bid-ask spread model (replaces hardcoded per-strategy slippage)
  - Result: Removed hardcoded $0.05 from credit_spread, $0.10 from iron_condor
  - Result: Removed unused self.slippage from PortfolioBacktester
- [x] Mark-to-market exit P&L with friction (replaces hardcoded pnl = credit * pct)
  - Result: _compute_exit_pnl always uses estimate_spread_value_with_friction()
- [x] Debit capital reservation at entry, credit-back at close
  - Result: _open_position deducts debit, _close_position credits back + adds P&L
- [x] Debit rejection if cost > 10% of capital
  - Result: _can_accept rejects oversized debit trades

### C. Implied Volatility Skew (HIGH)
- [ ] IV skew model: OTM puts get higher IV, OTM calls lower
- [ ] Calibrate from typical SPY vol surface
- [ ] Update all strategy pricing calls

### D. Gap Risk & Jump Modeling (HIGH)
- [ ] Model overnight gaps from historical SPY open/close data
- [ ] Stop losses execute at gap price, not stop price
- [ ] Add some losing trades that current model misses

### E. Realistic Compounding Constraints (MEDIUM)
- [ ] Max position size per trade (5%)
- [ ] Max total portfolio risk (20%)
- [ ] Margin requirement modeling
- [ ] Buying power reduction for open positions

### F. Commission Modeling (LOW-MEDIUM)
- [ ] $0.50-$0.65 per contract, 4 legs per round trip

### G. Assignment & Pin Risk (LOW-MEDIUM)
- [ ] Close-before-expiry rule if <1% OTM
- [ ] Model assignment on ITM short legs at expiry

### H. Multi-Underlying (MEDIUM)
- [ ] Run on QQQ and IWM, not just SPY
- [ ] Must work on ≥2 of 3 ETFs

### I. Full Walk-Forward Validation (MEDIUM)
- [ ] Train 2020-22, test 2023-25 (execute fully)
- [ ] Reverse: train 2023-25, test 2020-22
- [ ] Rolling walk-forward

### J. Parameter Sensitivity / Jitter (MEDIUM)
- [ ] 20+ jittered variations of best params
- [ ] No cliff-edge on ±10-20% perturbation

### RE-RUN: After all fixes, re-run Phases 1-4 with realistic pricing
- [ ] Re-run 100 credit spread experiments
- [ ] Re-run 100 blend experiments
- [ ] New leaderboard with REAL numbers
- [ ] Update report with realistic results

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
