# Active Experiments — Closing Strategy Report
**Generated:** 2026-03-11
**Experiments:** exp_036, exp_059, exp_154, exp_305

---

## Q1: What is the closing strategy for open trades?

| Experiment | Strategy Type | Profit Target | Stop Loss | DTE Exit |
|---|---|---|---|---|
| **exp_036** | Bull put + Bear call (no IC) | 50% of credit collected | 2.5× credit collected | None — hold to expiration |
| **exp_059** | Bull put + Bear call + Iron Condors | 50% of credit collected | 2.5× credit collected | None — hold to expiration |
| **exp_154** | Bull put + Bear call + IC (neutral regime only) | 50% of credit collected | 3.5× credit collected | None — hold to expiration |
| **exp_305** | Same as exp_154, multi-underlying (SPY + top-2 sectors) | 50% of credit collected | 3.5× credit collected | None — hold to expiration |

**Notes:**
- All experiments enter at target DTE 35, min DTE 25. There is no active "close at 21 DTE" rule — positions that don't hit profit target or stop loss are held to expiration.
- Stop loss fires intraday (checked against intraday spread values, not just daily close).
- exp_154 and exp_305 use the Combo Regime Detector (3-signal: price vs MA200, RSI, VIX structure) to gate entries. ICs are only entered in neutral regime readings.

---

## Q2: What is the expected average holding time?

Based on backtester results (real Polygon data, 2020–2025):

| Experiment | Leg Type | Avg Days in Trade | Primary Exit Trigger |
|---|---|---|---|
| **exp_036** | Bull put spreads | ~12–14 days | Profit target (50%) |
| **exp_036** | Bear call spreads | ~8–10 days | Profit target (50%) |
| **exp_059** | Bull put spreads | ~12–14 days | Profit target (50%) |
| **exp_059** | Iron condors | ~19–20 days | Stop loss (2.5×) |
| **exp_154** | Bull put spreads | ~12–14 days | Profit target (50%) |
| **exp_154** | Iron condors | ~19–20 days | Stop loss (3.5×) |
| **exp_305** | Bull put spreads (multi-ticker) | ~12–14 days | Profit target (50%) |
| **exp_305** | Iron condors (multi-ticker) | ~19–20 days | Stop loss (3.5×) |

Positions not exited early are held the full ~30–35 calendar days to expiration Friday.

---

## Q3: Is this holding time normal vs. published research?

**Short answer: Yes for spreads. Yes for IC duration, but IC win rates are below benchmarks.**

| Source | Setup | Avg Hold Reported | vs. Our Results |
|---|---|---|---|
| **tastytrade** *(Managing Winners, 2016)* | 45 DTE spreads/strangles, 50% PT or 21 DTE exit | ~20–24 days (max before 21 DTE rule fires) | Our 12–14 day spread hold is faster — consistent with 35 DTE entry (shorter runway) and no forced 21 DTE close |
| **DTR Trading** *(96,624 SPX IC trades, 2007–2016)* | 45 DTE iron condors, 8-delta, 50% PT | 16–26 days for winning trades | Our 19–20 day IC hold is within this range |
| **projectfinance** *(71,417 SPY IC trades)* | 16-delta ICs, 30–60 DTE, early profit management | 18–44 days depending on management rule | Our 19–20 days is at the fast end, consistent with active profit-taking |
| **spintwig** *(SPX vertical puts, 45 DTE)* | 45 DTE, managed at 50% profit or 21 DTE | ~50% of hold-to-expiration duration | For our 35 DTE entry, "unmanaged" hold = 35 days; 50% PT should produce ~15–18 days. Our 12–14 days is slightly fast but plausible given regime filter selecting favorable entries. |

**Bottom line by strategy:**
- **Credit spreads (exp_036, spreads in exp_059/154/305):** 12–14 day avg hold is normal. Tastytrade, spintwig, and DTR all support 10–20 days for 35–45 DTE entries managed at 50% profit.
- **Iron condors (exp_059, exp_154, exp_305):** 19–20 day duration is within the published 16–26 day range (DTR). Duration is not the concern — IC win rates in our system are below benchmarks (37% observed vs. 65–95% in published studies). This is flagged separately in `output/holding_period_research.md`.

---

## Sources
- tastytrade — *Managing Winners by Managing Earlier* (2016): tastytrade.com
- DTR Trading — *45 DTE Iron Condor Results Summary* (2017): dtr-trading.blogspot.com
- projectfinance — *Iron Condor Management Results from 71,417 Trades*: projectfinance.com/iron-condor-management
- spintwig — *Short SPX Vertical Put 45-DTE Options Backtest*: spintwig.com
