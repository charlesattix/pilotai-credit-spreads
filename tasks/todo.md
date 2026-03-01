# TODO — Operation Crack The Code
# Last Updated: 2026-02-27
# Mission: 40-80% annual, ≤20% DD, validated, paper traded, deployed live
# Current Focus: Stage 3 (Optimize) — REAL DATA ONLY mode active

---

## Stage 1: Polygon API + Real Data
- [x] Get Polygon API key (verified working, full Options tier)
- [x] Set in .env
- [x] Build historical options cache infrastructure (SQLite + bulk downloader)
- [x] Backtester cache integration (cache-first, NO BS fallback)
- [x] **CARDINAL RULE: NO SYNTHETIC DATA EVER** — backtester rejects trades on cache miss
- [x] Fixed `_fetch_and_cache` date range bug (was querying wrong years for expired contracts)
- [ ] Cache builds running: SPY/QQQ/IWM 2020-2025 (3 parallel nohup processes)

---

## Stage 2: Fix All Backtester Weaknesses — COMPLETE

### Done
- [x] A. Bid-ask spread modeling
- [x] B. Slippage model
- [x] F. Commission modeling ($0.65/leg)
- [x] K. Equity curve mark-to-market
- [x] Phase 0 complete (engine, strategies, backtester, optimizer, regime, daemon)
- [x] 900 optimization runs (INVALIDATED — synthetic pricing, discarded)
- [x] Claude Code MASTERPLAN review completed
- [x] 1. Walk-forward validation INTO optimizer (`--walk-forward` flag)
- [x] C. IV Skew model (OTM puts higher IV, OTM calls discounted)
- [x] 2. Gap risk & jump modeling
- [x] 3. VIX-scaled friction (bid-ask widens with VIX)
- [x] 4. Multi-underlying (QQQ, IWM) — default tickers now SPY+QQQ+IWM
- [x] 5. Jitter test (20+ variations of best params) — `scripts/jitter_test.py`
- [x] 6. Dynamic risk-free rate by year — all 7 strategies + backtester
- [x] 7. Portfolio delta awareness — bs_delta aggregation + delta cap in _can_accept
- [x] 8. Margin / buying power constraints — Reg-T style margin tracking
- [x] 9. Assignment & pin risk — force-close deep ITM shorts ≤2 DTE

---

## Stage 3: Optimize — IN PROGRESS (REAL DATA ONLY)

### Architecture Changes (Feb 27)
- [x] `PortfolioBacktester.require_real_data = True` — cache miss = skip trade
- [x] `_get_real_entry_price()` — validates ALL signal legs against Polygon cache
- [x] Signal `net_credit` overridden with REAL market price at entry
- [x] Exit P&L uses cache or intrinsic value — NO BS fallback
- [x] Mark-to-market uses cache or intrinsic — NO BS fallback
- [x] Gap-stop check uses cache or intrinsic — NO BS fallback
- [x] `HistoricalOptionsData.cache_only=True` — no live Polygon API during backtest
- [x] `run_optimization.py` loads `.env` for Polygon key
- [x] `--leaderboard` flag on endless optimizer for separate output file

### Running Processes
- [x] 700-run optimizer (PID 11279) — `output/real_data_optimizer.log`
  - Phase 1: 100 runs/strategy x 7 strategies
  - Walk-forward validation every 100 runs (20 exp/fold)
  - Results → `output/real_data_leaderboard.json`
  - DATA MODE: REAL DATA ONLY
- [ ] SPY cache build (PID 11098) — `output/cache_build_spy.log`
- [ ] QQQ cache build (PID 11109) — `output/cache_build_qqq.log`
- [ ] IWM cache build (PID 11119) — `output/cache_build_iwm.log`

### Remaining
- [ ] Wait for cache builds to complete (more data = more trades per run)
- [ ] Find params meeting victory conditions (40-80% annual, ≤20% DD, WF decay ≤30%)
- [ ] Validate across SPY + QQQ + IWM with full cached data
- [ ] Generate real-data backtest report (HTML)

---

## Stage 4: Paper Trade (After Stage 3)
- [ ] Get Alpaca paper trading API keys
- [ ] Build paper trading bot
- [ ] 8+ weeks validation
- [ ] Daily Telegram P&L reports

## Stage 5: Go Live (After Stage 4)
- [ ] Carlos approves capital
- [ ] Deploy with risk limits + kill switch
- [ ] Full automation
