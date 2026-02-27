# TODO — Operation Crack The Code
# Last Updated: 2026-02-27
# Mission: 40-80% annual, ≤20% DD, validated, paper traded, deployed live
# Current Focus: Stage 2 (Honest Backtesting) + Polygon cache build running

---

## Stage 1: Polygon API + Real Data
- [x] Get Polygon API key (verified working, full Options tier)
- [x] Set in .env
- [x] Build historical options cache infrastructure (SQLite + bulk downloader)
- [x] Backtester cache integration (cache-first pricing with BS fallback)
- [ ] Run full cache build: `python3 scripts/build_options_cache.py --tickers SPY,QQQ,IWM --start-year 2020 --end-year 2025`
- [ ] Kill all synthetic pricing (after cache build completes)
- [ ] Re-run everything with real data

---

## Stage 2: Fix All Backtester Weaknesses

### Done
- [x] A. Bid-ask spread modeling
- [x] B. Slippage model
- [x] F. Commission modeling ($0.65/leg)
- [x] K. Equity curve mark-to-market
- [x] Phase 0 complete (engine, strategies, backtester, optimizer, regime, daemon)
- [x] 900 optimization runs (invalidated — synthetic pricing)
- [x] Claude Code MASTERPLAN review completed
- [x] 1. Walk-forward validation INTO optimizer (`--walk-forward` flag)

### In Progress
- [ ] C. IV Skew model (Claude Code working on this)

### Remaining (Priority Order)
- [x] 2. Gap risk & jump modeling
- [ ] 3. VIX-scaled friction (bid-ask widens with VIX)
- [ ] 4. Multi-underlying (QQQ, IWM)
- [ ] 5. Jitter test (20+ variations of best params)
- [ ] 6. Dynamic risk-free rate by year
- [ ] 7. Portfolio correlation / delta awareness
- [ ] 8. Margin & compounding constraints
- [ ] 9. Assignment & pin risk

### After All Fixes
- [ ] Re-run optimization with ALL fixes (real data if available)
- [ ] Full walk-forward validation on best params
- [ ] Multi-underlying confirmation
- [ ] Generate new honest backtest report (HTML)

---

## Stage 3: Optimize (After Stage 1+2)
- [ ] Endless optimizer with real data + honest backtester
- [ ] Find params meeting victory conditions
- [ ] Validate across SPY + QQQ + IWM

## Stage 4: Paper Trade (After Stage 3)
- [ ] Get Alpaca paper trading API keys
- [ ] Build paper trading bot
- [ ] 8+ weeks validation
- [ ] Daily Telegram P&L reports

## Stage 5: Go Live (After Stage 4)
- [ ] Carlos approves capital
- [ ] Deploy with risk limits + kill switch
- [ ] Full automation
