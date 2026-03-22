# EXP-601 IBIT Feature Importance

XGBoost gain-based feature importance (higher = more predictive).

| Rank | Feature | Importance |
|------|---------|------------|
| 1 | `dte` | 0.1678 |
| 2 | `vix` | 0.1429 |
| 3 | `credit_received` | 0.1417 |
| 4 | `ma50_distance_pct` | 0.1216 |
| 5 | `btc_corr_30d` | 0.1158 |
| 6 | `rsi_14` | 0.1083 |
| 7 | `volume_ratio` | 0.1048 |
| 8 | `credit_pct` | 0.0971 |
| 9 | `otm_pct` | 0.0000 |
| 10 | `spread_width` | 0.0000 |
| 11 | `realized_vol_20d` | 0.0000 |
| 12 | `direction_bull` | 0.0000 |

## Interpretation Notes

- `credit_pct`: proxy for implied volatility level (credit / spread_width)
- `ma50_distance_pct`: distance from MA50 — trend strength signal
- `realized_vol_20d`: 20-day realized volatility (annualized, %)
- `vix`: VIX level at entry (forward-filled from weekly macro_score)
- `rsi_14`: 14-day RSI — momentum/overbought signal
- `volume_ratio`: today vol / 20d avg — unusual activity signal
- `btc_corr_30d`: IBIT-ETHA 30d return correlation (BTC regime proxy)
