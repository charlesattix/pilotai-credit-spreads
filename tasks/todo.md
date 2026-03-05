# TODO — Operation Crack The Code
# Last Updated: 2026-03-05
# Mission: 40-80% annual, ≤20% DD, validated, paper traded, deployed live
# Current Focus: Stage 4 (Paper Trade) — scheduler running, 14 scans/day

---

## Stage 1: Polygon API + Real Data — COMPLETE
- [x] Get Polygon API key (verified working, full Options tier)
- [x] Set in .env
- [x] Build historical options cache infrastructure (SQLite + bulk downloader)
- [x] Backtester cache integration (cache-first, NO BS fallback)
- [x] **CARDINAL RULE: NO SYNTHETIC DATA EVER** — backtester rejects trades on cache miss
- [x] Fixed `_fetch_and_cache` date range bug (was querying wrong years for expired contracts)
- [x] Cache builds: SPY/QQQ/IWM 2020-2025

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

## Stage 3: Optimize — COMPLETE

### Summary
- **500-run optimizer** on real Polygon data — **34/500 met victory conditions**
- **Top 10 jitter-tested** (25 variants each, ±15%, SPY+QQQ+IWM)
- **Top 4 walk-forward validated** (3 folds, expanding window, 20 exp/fold)
- **Champion selected:** 12.6%/yr avg return, -10.4% max DD, jitter stability 0.71, WF 3/3 folds profitable

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

### Optimization Pipeline (600 total runs)
- [x] 100-run real-data optimizer — 7/100 met victory conditions
- [x] 500-run optimizer — **34/500 met victory conditions**
- [x] Jitter tests on top 10 — ranked by robustness (25 variants, ±15%, SPY+QQQ+IWM)
- [x] Walk-forward validation on top 4 — 3 folds, 20 exp/fold, expanding window

### Walk-Forward Results
| Config | Base Ret | WF OOS | WF Ratio | Folds OK | Verdict |
|--------|----------|--------|----------|----------|---------|
| Jitter #2 (credit_spread+iron_condor+momentum_swing+debit_spread) | 12.6% | **+9.5%** | **0.631** | **3/3** | **CHAMPION** |
| Jitter #3 (straddle_strangle+gamma_lotto+credit_spread+iron_condor) | 26.9% | +13.4% | 0.329 | 2/3 | Secondary |
| Jitter #1 | 14.4% | — | — | — | Failed |
| Jitter #5 | 22.1% | — | — | — | Failed |

### Champion Config: `configs/champion.json`
- **Strategies:** credit_spread, iron_condor, momentum_swing, debit_spread
- **Backtest (2020-2025):** +89.4% total, 560 trades, 64.3% WR, -10.4% max DD
- **Walk-forward OOS:** +4.6% (2023), +4.5% (2024), +19.3% (2025) — all profitable
- **Jitter:** stability 0.712, robustness 0.772, mean +9.0%
- **Report:** `output/champion_report.html`

### Secondary Config: `configs/secondary.json`
- **Strategies:** straddle_strangle, gamma_lotto, credit_spread, iron_condor
- **Higher returns (26.9% base) but inconsistent WF** — 2024 fold was -19.0%
- **Kept as aggressive alternative for future evaluation**

---

## Stage 4: Paper Trade — IN PROGRESS (started 2026-03-05)

### Setup — COMPLETE
- [x] Get Alpaca paper trading API keys (Account ***I9BA, Options Level 3, $9,429 cash)
- [x] Create `config.yaml` with champion params + Alpaca + Polygon credentials
- [x] Upgrade alpaca-py SDK (0.21.1 → 0.43.2) for options trading support
- [x] Build paper trading bot using champion config (`configs/champion.json`)
- [x] Wire up live Polygon data feed for signal generation
- [x] Create `scripts/daily_report.py` — daily P&L report from SQLite
- [x] Add daily report hook to scheduler (fires at 4:15 PM ET)
- [x] End-to-end test: Alpaca ON, PaperTrader ON, ML pipeline OK, all scanners init
- [x] Scheduler launched as nohup (PID 69663), 14 scans/day on ET market hours
- [x] Next scan: 9:15 AM ET, logs at `logs/scheduler.log`

### Validation — Running
- [ ] 8+ weeks paper trading validation (started 2026-03-05)
- [ ] Daily P&L reports (scheduler auto-generates at 4:15 PM ET)
- [ ] Track live vs backtest performance deviation
- [ ] Wire up Telegram alerts (deferred — stdout reports first)

---

## Stage 5: Go Live (After Stage 4)
- [ ] Carlos approves capital
- [ ] Deploy with risk limits + kill switch
- [ ] Full automation
