# XLE Real Data vs Heuristic Comparison (2020–2025)

**Strategy params**: `direction=bull_put`, `regime_mode=ma`, `otm_pct=5%`, `iron_condor_enabled=False`

## Side-by-Side Results

| Year | Heuristic Return | Heuristic WR | Heuristic Trades | Real Return | Real WR | Real Trades | Real MaxDD |
|------|-----------------|-------------|-----------------|------------|---------|------------|------------|
| 2020 | +6.7% | 100.0% | 20 | +0.0% | 0.0% | 0 | 0.0% |
| 2021 | +9.2% | 100.0% | 25 | +0.0% | 0.0% | 0 | 0.0% |
| 2022 | +10.3% | 100.0% | 30 | +0.0% | 0.0% | 0 | 0.0% |
| 2023 | +10.0% | 100.0% | 27 | +0.0% | 0.0% | 0 | 0.0% |
| 2024 | +10.8% | 100.0% | 29 | +0.0% | 0.0% | 0 | 0.0% |
| 2025 | +10.7% | 100.0% | 29 | +0.0% | 0.0% | 0 | 0.0% |
| **AVG** | **+9.6%** | **100.0%** | **160T total** | **+0.0%** | **0.0%** | **0T total** | **0.0%** |

## Analysis: Why Heuristic Inflates Results

The heuristic mode produces completely fabricated results for sector ETFs like XLE for several compounding reasons:

### 1. $5-Wide Spreads Are Structurally Impossible with Real XLE Data

The most critical finding: **XLE in the SQLite cache has only 1–4 puts per expiration, all within a $3–4 strike range**.

Sample from the cache (puts only):
- `2020-04-17 P`: strikes 12, 13 (2 strikes — $1 wide max)
- `2020-06-19 P`: strikes 13, 14, 15, 16 (4 strikes — $3 wide max)
- `2021-01-15 P`: strikes 15, 17, 18 (gaps! no contiguous $5-wide spread)
- `2022-01-21 P`: strikes 22, 23, 24, 25, 26, 27 (best coverage, $5 possible on this one)

The backtester requires `spread_width=5`, meaning a short put and a long put exactly $5 apart. For most XLE expirations, the maximum available spread is $1–$3 wide. Result: **0 trades found in real mode for all 6 years**.

### 2. Heuristic Mode Assumes Infinite Strike Availability

In heuristic mode, the backtester synthesizes option prices at any OTM% by calling Black-Scholes on the underlying price. It never checks whether that strike actually has a market. This means it happily constructs 5%-OTM bull put spreads at any desired width regardless of what market makers actually quoted. This inflates the trade count from **0 real trades** to **20–30 heuristic trades per year**.

### 3. 100% Win Rate Is Mathematically Impossible in Practice

Heuristic win rates of 100% across all years expose a fundamental circularity: the synthetic option price is derived from the same price path used to determine if the trade wins. Since the backtester opens the spread when the underlying is above its MA (bull_put mode) and the heuristic prices options assuming those conditions persist, the spread almost always expires OTM. Real market dynamics — gap-downs, earnings surprises, sector-specific shocks — are not captured by the smooth heuristic pricing model.

### 4. Zero Drawdown Is Physically Impossible

In heuristic mode, XLE shows DD = 0.0% every year, including 2020 (COVID crash — XLE fell ~65% from Jan to Mar 2020). Even a bull_put strategy would have experienced significant drawdown during that period. The heuristic MA filter blocks new entries during the crash, but existing positions are modeled as expiring cleanly rather than getting stopped out at real mark-to-market prices.

### 5. Structural Data Sparsity: 1,005 Contracts vs. SPY's Hundreds of Thousands

The XLE cache contains:
- **1,005 total contracts** across all expirations (2020–2026)
- **Most expirations**: 1–4 strikes per expiry
- **Daily bars by year**: 2020=1,977 · 2021=2,705 · 2022=2,274 · 2023=746 · 2024=414 · 2025=3,088

SPY, by contrast, has hundreds of strikes per weekly expiration. The XLE data was incidentally collected during prior SPY-focused backtest runs, capturing only the handful of XLE contracts that happened to appear in market scans — not a systematic backfill.

## Conclusion: Data Quality and What We Need

**The real-data XLE backtest reveals the true opportunity set: zero viable $5-wide spreads exist in the current cache.** The heuristic comparison shows fabricated returns (+9.6% avg, 100% WR) that cannot be replicated in practice.

### To use XLE reliably in portfolio mode, we need:

1. **Systematic Polygon backfill for XLE 2020–2025**: Run `scripts/fetch_sector_options.py` to pull all XLE option chains for each monthly/weekly expiration in the target DTE window (25–45 DTE). This would yield hundreds of strikes per expiry rather than 1–4.

2. **Narrow the spread width for sector ETFs**: XLE's price during 2020–2025 ranged $20–$100. A `spread_width=2` or `spread_width=3` would be more appropriate until a full backfill is available.

3. **Use `_ticker_has_real_data()` as the data quality gate**: The fix applied to `run_portfolio_backtest.py` correctly routes tickers through this check before deciding whether to use real or heuristic mode. Until XLE is fully backfilled, the portfolio correctly shows 0 contribution from XLE sectors when real mode is forced.

### The fix applied to `run_portfolio_backtest.py`:

The hardcoded `ticker_real = use_real_data and (ticker == "SPY")` was replaced with:

```python
ticker_real = use_real_data and _ticker_has_real_data(ticker)
```

Where `_ticker_has_real_data(ticker, min_contracts=50)` queries `data/options_cache.db` to count contracts. This creates a data-quality gate that:
- Automatically uses real data for any ticker with sufficient cache coverage (e.g., a fully backfilled XLE would qualify)
- Falls back to heuristic for tickers with < 50 contracts (e.g., SOXX, IWM with no cache data)
- Removes the hardcoded SPY-only special case, making the code correct by construction

Note: XLE currently has 1,005 contracts (above the 50-contract threshold), so it does use real mode — but still finds 0 trades because the strikes are too sparse for $5-wide spreads. The actual solution is a full data backfill.

**Until XLE is properly backfilled, sector ETF results in portfolio mode should be treated as directional signals only, not realistic P&L projections.**

---
*Generated by `scripts/run_xle_comparison.py` — 2026-03-08*
