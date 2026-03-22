# EXP-601 IBIT ML Signal Filter — Model Report

Generated: 2026-03-22 19:01 UTC

## Summary

- **Model**: XGBoost binary classifier (win/loss)
- **Training samples**: 249
- **Baseline win rate**: 84.3%
- **Features**: 12
- **CV**: TimeSeriesSplit (n_splits=3) — chronological only
- **Backtest period**: 2024-11-19 → 2026-03-20

## CV Results

| Fold | Train | Val | Acc | AUC | Prec | Recall |
|------|-------|-----|-----|-----|------|--------|
| 1 | 63 | 62 | 0.032 | 0.500 | 0.000 | 0.000 |
| 2 | 125 | 62 | 0.774 | 0.500 | 0.774 | 1.000 |
| 3 | 187 | 62 | 0.710 | 0.502 | 0.782 | 0.878 |
| **Mean** | - | - | **0.505** | **0.501** | **0.519** | **0.626** |

## XGBoost Parameters

```
max_depth: 3
min_child_weight: 5
n_estimators: 50
learning_rate: 0.1
subsample: 0.8
colsample_bytree: 0.8
gamma: 1.0
reg_alpha: 0.5
reg_lambda: 2.0
scale_pos_weight: 0.186
eval_metric: logloss
random_state: 42
```

## Feature Importances

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

## Notes

- IBIT options data available from 2024-11-19 only
- With 249 samples, ML signal is preliminary — accumulate more trades before relying on filter
- `btc_corr_30d` uses ETHA (Ethereum ETF) as BTC correlation proxy
- `vix` is SPX VIX forward-filled from weekly macro_score readings
- `credit_pct` = credit / spread_width × 100 (no Black-Scholes)
- Threshold 0.5: skip trade if P(win) < 0.5
