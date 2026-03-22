# Historical Macro Snapshot Analysis

**Generated:** 2026-03-07  
**Coverage:** 2020-01-03 to 2026-03-06  
**Total snapshots:** 323  
**Snapshots with FRED macro score:** 323  

---

## 1. SPY Forward Return Summary

Average SPY return and % of weeks positive over each horizon:

| Horizon | N Weeks | Avg SPY Return | % Positive |
|---------|---------|---------------|------------|
| 4 weeks | 319 | 1.06% | 66.1% |
| 8 weeks | 315 | 2.12% | 71.7% |
| 12 weeks | 311 | 3.41% | 76.2% |

---

## 2. Macro Score vs Forward SPY Returns

Pearson correlation between macro overall score (0-100) and forward SPY return:

| Horizon | N | Correlation | Low-Score Avg | Mid-Score Avg | High-Score Avg |
|---------|---|-------------|---------------|---------------|----------------|
| 4 weeks | 319 | -0.106 | 1.79% | 0.71% | 0.68% |
| 8 weeks | 315 | -0.134 | 3.31% | 2.21% | 0.82% |
| 12 weeks | 311 | -0.133 | 4.73% | 3.21% | 2.27% |

---

## 3. RRG Quadrant Distribution

How often sectors fall in each RRG quadrant across all snapshots:

| Quadrant | % of Observations |
|----------|-------------------|
| Leading | 25.3% |
| Weakening | 22.3% |
| Lagging | 28.0% |
| Improving | 24.4% |
| **Total** | **4,845 sector-weeks** |

---

## 4. Top Sector Rotation Signals

### Top-Ranked Sector (3M RS) — Frequency by Ticker

Which sectors appear most frequently as the #1 ranked sector:

| Ticker | Count | % of Weeks |
|--------|-------|------------|
| XLE | 78 | 24.1% |
| SOXX | 60 | 18.6% |
| XBI | 52 | 16.1% |
| XLK | 32 | 9.9% |
| XLY | 16 | 5.0% |
| XLRE | 16 | 5.0% |
| XLU | 15 | 4.6% |
| ITA | 15 | 4.6% |
| PAVE | 13 | 4.0% |
| XLP | 9 | 2.8% |
| XLB | 6 | 1.9% |
| XLC | 5 | 1.5% |
| XLV | 4 | 1.2% |
| XLF | 2 | 0.6% |

### Macro Score Distribution

- Mean:   61.1
- Median: 61.4
- Std:    8.9
- Min:    36.2
- Max:    82.1

Score quintile distribution:

| Quintile range | N snapshots |
|----------------|-------------|
| (36.199000000000005, 53.04] | 65 |
| (53.04, 59.28] | 64 |
| (59.28, 63.0] | 66 |
| (63.0, 69.46] | 63 |
| (69.46, 82.1] | 65 |

---

## 5. Methodology Notes

- **RS (3M)**: `(ticker_return_3M / SPY_return_3M - 1) × 100` — percentage outperformance vs benchmark
- **RS (12M)**: same over 12 months (~252 trading days)
- **RRG Quadrant**: cross-sectionally normalized RS-Ratio and RS-Momentum, centered at 100
  - Leading: RS-Ratio ≥ 100 AND RS-Momentum ≥ 100
  - Weakening: RS-Ratio ≥ 100 AND RS-Momentum < 100
  - Lagging: RS-Ratio < 100 AND RS-Momentum < 100
  - Improving: RS-Ratio < 100 AND RS-Momentum ≥ 100
- **Macro Score**: 4 dimensions, each 0-100, equal-weighted to overall score
  - Growth: CFNAI 3M avg (50%) + Nonfarm Payrolls 3M avg (50%) — CFNAI is a composite of 85 indicators
  - Inflation: CPI YoY (35%) + Core CPI YoY (40%) + 5Y Breakeven (25%) — Goldilocks curve peaks at 2-2.5%
  - Fed Policy: 10Y-2Y spread (55%) + Effective Fed Funds (45%)
  - Risk Appetite: VIX (50%) + HY OAS spread (50%)
- **RELEASE_LAG_DAYS**: Applied per FRED series to prevent lookahead bias
  - Daily series (VIX, spreads): 1-day lag
  - Monthly releases (CPI, payrolls, PMI): 31-66 day lag
