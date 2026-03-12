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
- [x] Test fixed fractional: 2%, 5%, 8.5%, 10%, 15%, 20%
  - Result: Returns plateau at ~10% risk_pct (+34.9%). Strategy is signal-constrained, not capital-constrained.
  - Best risk-adjusted (Sharpe 2.80): 5% risk → +23.6% avg, -6.4% DD
  - Current 8.5% captures 96% of max return (+33.7% avg, -11.2% DD, Sharpe 2.67)
  - Scripts: scripts/test_position_sizing.py, output/position_sizing_results.json
- [x] Kelly criterion variants
  - Result: Kelly f* = 59% raw (win_rate=84.8%, avg_win=$1474, avg_loss=$2497), capped at 25%
  - Kelly result identical to 15%+ fixed fractional due to signal-constraint plateau
- [ ] Compound mode (reinvest profits)
- [ ] Max concurrent positions optimization

## Phase 3: Portfolio Blending 🔀
- [x] Combine top strategies, optimize weights
  - Result: 11 equal-weight blends + 423 weight-optimized combos tested across 2020-2025
  - Scripts: scripts/portfolio_blend.py, output/portfolio_blend_results.json
- [x] Exploit uncorrelated strategies for low drawdown
  - Result: Correlation matrix computed. CS↔Calendar -0.509 (best diversifier). CS↔IC -0.247. CS↔SS +0.268.
  - Straddle/strangle adds +3-4% avg return with minimal DD increase
- [x] Find max-score blend
  - Result: **CRED(12%) + STRA(3%) = +39.1% avg, -9.5% worst DD, 6/6 profitable years, 2.96 Sharpe**
  - Runner-up: CRED(12%)+IRON(2%)+STRA(3%) = +38.6% avg, -9.6% DD, 6/6 profitable
  - Position limits (8/4 vs 10/5 vs 12/6) have NO effect — strategies are signal-constrained, not position-limited
  - Credit spread risk_pct is the dominant weight lever (5%→12% drives +28%→+39%)
  - Calendar spread consistently drags returns -1 to -3%

### Phase 3 — Optimal Weights Found
| Rank | Blend | Weights | Avg Ret | Worst DD | Sharpe | Prof Yrs |
|------|-------|---------|---------|----------|--------|----------|
| 1 | CRED + STRA | CS=12%, SS=3% | **+39.1%** | -9.5% | 2.96 | 6/6 |
| 2 | CRED + IRON + STRA | CS=12%, IC=2%, SS=3% | +38.6% | -9.6% | 2.92 | 6/6 |
| 3 | CRED + STRA | CS=10%, SS=3% | +38.9% | -9.7% | 2.96 | 6/6 |
| 4 | CRED + STRA + CALE | CS=12%, SS=3%, Cal=2% | +37.4% | -8.6% | 2.81 | 6/6 |

### Best Blend Year-by-Year (CS 12% + SS 3%)
| Year | Return | Max DD | Trades | Win Rate | Sharpe |
|------|--------|--------|--------|----------|--------|
| 2020 | +20.7% | -6.8% | 51 | 78.4% | 1.63 |
| 2021 | +107.2% | -3.7% | 86 | 89.5% | 6.77 |
| 2022 | +2.1% | -9.5% | 39 | 74.4% | -0.01 |
| 2023 | +42.8% | -3.6% | 60 | 86.7% | 3.91 |
| 2024 | +26.0% | -6.6% | 62 | 79.0% | 2.72 |
| 2025 | +35.9% | -6.9% | 55 | 90.9% | 2.76 |

## Phase 4: Regime Switching 🌊
- [x] Dynamic allocation per regime
  - Result: Made REGIME_SIZE_SCALE configurable via `self._p()` in CreditSpreadStrategy
  - Added SS_REGIME_SIZE_SCALE + regime-aware sizing to StraddleStrangleStrategy
  - Staged grid search: 144 CS combos → 108 SS combos → 25 joint fine-tune
- [x] Train on 2020-2022, validate 2023-2025
  - Training: 277 configs tested, all valid (DD well under 15%)
  - Validation: 20/20 pass DD<15% gate, best score=27.2
- [x] Drawdown improvement achieved
  - Worst DD improved from -9.4% (baseline) to -7.0% (optimized)
  - All 6 years profitable, avg return +40.7% (vs +39.3% baseline)

### Phase 4 — Best Regime Scales
| Strategy | Bull | Bear | High Vol | Low Vol | Crash |
|----------|------|------|----------|---------|-------|
| CreditSpread | 1.0 | 0.3 | 0.3 | 0.8 | 0.0 |
| StraddleStrangle | 1.5 | 1.5 | 2.5 | 1.0 | 0.5 |

### Phase 4 vs Phase 3 Comparison
| Metric | Phase 3 (static) | Phase 4 (regime) | Delta |
|--------|-------------------|-------------------|-------|
| Avg Return | +39.3% | +40.7% | +1.4% |
| Worst DD | -9.4% | -7.0% | +2.5% |
| 2022 (bear) | +2.9% | +8.1% | +5.2% |
| All Years Profitable | 6/6 | 6/6 | = |

### Phase 4 Year-by-Year (Optimized)
| Year | Return | Max DD | Trades | Win Rate |
|------|--------|--------|--------|----------|
| 2020 | +24.1% | -6.6% | 51 | 78.4% |
| 2021 | +107.4% | -3.7% | 86 | 89.5% |
| 2022 | +8.1% | -7.0% | 39 | 74.4% |
| 2023 | +43.2% | -3.6% | 60 | 86.7% |
| 2024 | +26.4% | -6.6% | 62 | 79.0% |
| 2025 | +35.0% | -3.6% | 55 | 90.9% |

## Phase 5: Validation & Stress Testing ✅
- [ ] Walk-forward validation
- [ ] Monte Carlo (10,000 paths)
- [ ] Slippage & fill modeling
- [ ] Tail risk scenarios
- [ ] DECLARE VICTORY 🏆
