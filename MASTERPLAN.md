# MASTERPLAN.md — Operation Crack The Code 🎯

## THE MISSION (Definitive — 24/7)

**Build a fully autonomous trading system that generates 40-80% annual returns with ≤20% max drawdown, validated on real market data, proven in paper trading, and ready for live capital deployment.**

This is NOT a backtest exercise. The end state is **a machine that trades real money with proven, validated edge.**

## 5 Stages to Victory

```
Stage 1: REAL DATA          → Polygon historical options (no synthetic pricing EVER)
Stage 2: HONEST BACKTESTING → Fix all weaknesses, validate out-of-sample
Stage 3: OPTIMIZE           → Find robust params across SPY + QQQ + IWM
Stage 4: PAPER TRADE        → Alpaca paper trading, prove it in real-time
Stage 5: GO LIVE            → Graduate to real money after 8+ weeks paper validation
```

## Victory Conditions

| Metric | Target | Minimum Acceptable |
|--------|--------|--------------------|
| Annual Return | 40-80% | 25% |
| Max Drawdown | ≤15% | ≤20% |
| Win Rate | 65-80% | 60% |
| Sharpe Ratio | 1.5-2.5 | 1.0 |
| Profit Factor | 1.5-2.5 | 1.3 |
| Trades/Year | 100-300 | 50 |
| Walk-Forward Decay | ≤30% | ≤50% |
| Works on | SPY + QQQ + IWM | ≥2 of 3 |
| Paper Trade Validation | 8+ weeks matching backtest | 4 weeks minimum |

**A system that reliably produces 25-50% annually with ≤20% drawdown, validated out-of-sample, would be top-tier among systematic options strategies — better than 95% of hedge funds.**

---

## STAGE 1: REAL DATA (Prerequisite — Nothing Else Matters Without This)

### Status: BLOCKED — Need Polygon API Key

The production app runs at `pilotai-credit-spreads-production.up.railway.app` with Polygon. The key is in Railway environment variables. Once provided:

- [ ] Set `POLYGON_API_KEY` in `.env`
- [ ] Build historical options data cache: SPY/QQQ/IWM 2020-2025
  - Real strikes, real bid/ask, real greeks, real IV
  - Use `backtest/historical_data.py` (already built)
  - Cache to local SQLite for fast repeated backtests
- [ ] **KILL all synthetic BS pricing in the backtester** — real data only
- [ ] Verify data quality: no gaps, reasonable bid-ask spreads, correct greeks
- [ ] Benchmark: how much Polygon data can we pull per day (rate limits)?

**RULE: No optimization results count until they use real Polygon data.**

### Fallback (While Waiting for Key)
Continue fixing backtester weaknesses (Stage 2) so the engine is ready when data arrives.

---

## STAGE 2: HONEST BACKTESTING (Fix All Weaknesses)

The backtester must produce numbers you can trust before any optimization matters.

### ✅ Already Fixed
- [x] A. Bid-ask spread modeling (realistic fills)
- [x] B. Slippage model
- [x] F. Commission modeling ($0.65/leg)
- [x] K. Equity curve mark-to-market (open positions valued daily)

### 🔄 In Progress / Remaining (Priority Order from Review)

#### Priority 1: Walk-Forward INTO Optimizer (HIGH)
- [ ] Train on rolling 3-year windows, test on next year
- [ ] Reject params that don't generalize out-of-sample
- [ ] Optimizer ONLY scores on out-of-sample performance
- [ ] This prevents the fundamental overfitting: search seeing all data

#### Priority 2: IV Skew Model (HIGH)
- [ ] Convex skew for OTM puts: `iv_put = rv * (1 + skew * max(0, (S-K)/S))^1.5`
- [ ] Slight discount for OTM calls
- [ ] Skew scales with VIX level (high VIX = flatter skew)
- [ ] Use VIX/VIX3M ratio to infer skew
- [ ] **MOOT if we get Polygon data** — real IV from market

#### Priority 3: Gap Risk & Jump Modeling (HIGH)
- [ ] Model overnight gaps from historical SPY open-vs-close
- [ ] Stop losses execute at gap price, not stop price
- [ ] Correlated gap losses: ALL positions gap simultaneously
- [ ] This adds the hidden losses the model currently misses

#### Priority 4: VIX-Scaled Friction (MEDIUM)
- [ ] Bid-ask spreads widen with VIX: `spread *= max(1.0, vix/20)`
- [ ] Pass VIX to fill price calculations
- [ ] March 2020 spreads were 3-5x normal — model must capture this

#### Priority 5: Multi-Underlying Validation (MEDIUM)
- [ ] Run all strategies on SPY, QQQ, AND IWM
- [ ] Strategy must work on ≥2 of 3 ETFs
- [ ] QQQ = higher vol, tech-heavy. IWM = wider spreads, lower liquidity
- [ ] If it only works on SPY, it's overfit to SPY

#### Priority 6: Parameter Sensitivity / Jitter Test (MEDIUM)
- [ ] Take best params, perturb each ±10%, ±20%
- [ ] Run 20+ jittered variations
- [ ] Performance must not cliff-edge — graceful degradation only
- [ ] If ±10% change = 50% performance drop → FRAGILE, reject

#### Priority 7: Dynamic Risk-Free Rate (LOW-MEDIUM)
- [ ] Use historical Fed funds rate by year, not static 4.5%
- [ ] 2020-2021: 0.25%, 2022: 0.25→4.5%, 2023-24: 5.25%, 2025: 4.5%
- [ ] Corrects put pricing in early years

#### Priority 8: Portfolio Correlation Awareness (MEDIUM)
- [ ] Track portfolio-level delta across all open positions
- [ ] Reject new trades that push portfolio delta beyond threshold
- [ ] 5 bull put spreads = 1 big directional bet — system must recognize this

#### Priority 9: Compounding Constraints & Margin (LOW-MEDIUM)
- [ ] Margin requirements per spread (~$1K-$2K per $5-wide spread)
- [ ] Buying power reduction for open positions
- [ ] Max total portfolio risk cap

#### Priority 10: Assignment & Pin Risk (LOW)
- [ ] Close-before-expiry rule if <1% OTM
- [ ] Model assignment on ITM short legs at expiry
- [ ] Add friction to expiration settlement

---

## STAGE 3: OPTIMIZE (With Real Data + Honest Backtester)

### Strategy Arsenal
- **Credit Spreads** (bull put / bear call) — primary income
- **Iron Condors** — range-bound, dual premium
- **Straddle/Strangle** (short post-event) — IV crush plays
- **Debit Spreads** — directional conviction
- **Calendar Spreads** — theta harvesting
- **Momentum Swing** — trend/breakout on underlying
- **Gamma Lotto** — asymmetric pre-catalyst plays (small allocation)

### Optimization Engine
- Bayesian/genetic optimizer with walk-forward validation baked in
- Score: `(return / target) × (target_dd / actual_dd) × consistency`
- Endless optimizer daemon runs until goal met or ceiling proven
- Auto-escalation: single strategy → blending → regime switching
- Every result validated: cross-year, walk-forward, jitter, multi-underlying

### Regime Detection
- Bull (SPY up, VIX < 20)
- Bear (SPY down, VIX > 25)
- High Vol (VIX > 30)
- Low Vol Sideways (VIX < 15)
- Crash (VIX > 40, sharp decline)
- Different strategy allocation per regime

### Target: Find params that achieve
- 40-80% annual on SPY (and ≥1 of QQQ/IWM)
- ≤20% max drawdown
- ≥60% win rate
- Sharpe ≥ 1.0
- Walk-forward decay ≤30% (test vs train)
- Overfit score ≥ 0.70

---

## STAGE 4: PAPER TRADE (Prove It's Real)

### Setup
- [ ] Alpaca paper trading account (need API key + secret from Carlos)
- [ ] Build paper trading bot from validated strategy params
- [ ] Real-time signal generation from live market data
- [ ] Automated order execution on Alpaca paper
- [ ] Daily P&L Telegram alerts to Carlos
- [ ] Weekly summary reports (HTML)

### Protocol
- **Week 1-2:** Credit spreads only, 1% risk per trade (conservative)
- **Week 3-4:** Add iron condors. Monitor fill quality vs backtest expectations
- **Week 5-8:** Full strategy blend running. Track real metrics
- **Week 9+:** If paper results within 50% of backtest → prepare for live

### Kill Conditions
- Win rate below 55% over 30+ trades → STOP, investigate
- Drawdown exceeds 25% of paper account → STOP, investigate
- Average fill deviation from expected > 30% → STOP, recalibrate
- 3 consecutive losing weeks → PAUSE, review

### Success Criteria for Live Graduation
- 8+ weeks of paper trading
- Win rate within 10% of backtest prediction
- Drawdown within backtest predicted range
- Fill quality acceptable (within 20% of expected)
- Monthly return positive in ≥6 of 8 weeks

---

## STAGE 5: GO LIVE (The End State)

### Prerequisites (ALL must be met)
- [ ] Stage 4 success criteria achieved
- [ ] Carlos approves capital allocation
- [ ] Risk limits hardcoded: max loss per day, per week, per trade
- [ ] Kill switch: automated shutdown if drawdown exceeds threshold
- [ ] Monitoring: real-time Telegram alerts for every trade

### Live Deployment
- Start with small allocation (5-10% of trading capital)
- Scale up over 4-8 weeks if results hold
- Full automation: signal → size → execute → manage → exit
- Daily Telegram reports, weekly HTML summaries
- Monthly performance review vs backtest expectations

---

## RULES FOR CLAUDE CODE

1. **No synthetic pricing** — once Polygon key is available, ALL backtests use real data
2. **Walk-forward validation is mandatory** — integrated into optimizer, not post-hoc
3. **Multi-underlying or it doesn't count** — must work on ≥2 of SPY/QQQ/IWM
4. **Always log before running** — hypothesis in optimization log
5. **Always validate after running** — overfit score ≥ 0.70 to accept
6. **Save state frequently** — optimization_state.json for recovery
7. **Think before brute-forcing** — analyze what's working and WHY
8. **If it looks too good, it is** — 500% with 15 trades = overfit
9. **Report breakthroughs** — if out-of-sample results meet targets, flag immediately
10. **The goal is LIVE TRADING, not a good backtest** — every decision serves deployment

## FILE STRUCTURE
```
pilotai-credit-spreads/
├── MASTERPLAN.md               ← This file (the mission)
├── .env                        ← API keys (Polygon, Alpaca)
├── strategies/                 ← 7 pluggable strategy modules
│   ├── base.py                 ← Strategy interface
│   ├── credit_spread.py        ← Bull put / bear call
│   ├── iron_condor.py          ← Simultaneous put + call spreads
│   ├── gamma_lotto.py          ← Pre-catalyst OTM plays
│   ├── straddle_strangle.py    ← Vol / IV crush plays
│   ├── debit_spread.py         ← Directional defined-risk
│   ├── calendar_spread.py      ← Theta across expirations
│   ├── momentum_swing.py       ← Trend/breakout
│   └── pricing.py              ← Pricing helpers (fallback only)
├── engine/
│   ├── portfolio_backtester.py ← Multi-strategy portfolio sim
│   ├── regime.py               ← Market regime classification
│   └── optimizer.py            ← Bayesian/genetic param search
├── backtest/
│   ├── backtester.py           ← Original backtester
│   └── historical_data.py      ← Polygon data provider (REAL DATA)
├── strategy/
│   └── polygon_provider.py     ← Live Polygon data (for paper/live)
├── scripts/
│   ├── run_optimization.py     ← Single experiment runner
│   ├── validate_params.py      ← Validation suite
│   └── endless_optimizer.py    ← Autonomous daemon
├── output/
│   ├── leaderboard.json        ← All runs + scores
│   ├── optimization_log.json   ← Hypotheses & outcomes
│   ├── optimization_state.json ← Recovery state
│   ├── data_audit.json         ← Data availability
│   ├── backtest_report.html    ← Latest report
│   └── masterplan_review.md    ← Claude Code's honest review
└── tasks/
    ├── todo.md                 ← Current task tracking
    └── lessons.md              ← Learnings
```

---

*The mission is not a backtest number. The mission is a machine that trades real money, profitably, autonomously, with validated edge. Every line of code, every experiment, every fix serves that end state.*

*40-80% annual. ≤20% drawdown. Proven on paper. Deployed live. That's victory.* 🎯
