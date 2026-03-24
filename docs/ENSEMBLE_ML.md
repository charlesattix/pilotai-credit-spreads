# Ensemble ML System

## 1. Motivation

### Why We Built the Ensemble

The original SignalModel is a single XGBoost classifier predicting credit spread profitability (binary: profitable=1, unprofitable=0). It works but has three structural weaknesses:

**Calibration fragility.** XGBoost's raw probabilities are poorly calibrated — a predicted 70% probability does not map to a 70% empirical win rate. We apply sigmoid calibration via `CalibratedClassifierCV`, but this requires a held-out calibration set carved from already-limited training data (~430 trades total). With only ~85 calibration samples, the sigmoid fit is noisy. A bad calibration run can invert the confidence → sizing mapping, causing the system to size up on its worst predictions.

**Single-model risk.** A lone XGBoost overfits to whichever market regime dominated the training window. The 2022 bear market (286 bear-call trades, 89.6% win rate) looks nothing like the 2024 low-vol grind (128 trades, 86.7% win rate, 0.30 Sharpe). A model trained primarily on 2022 data will be overconfident on bear-call signals and underconfident on bull-put signals when the regime flips.

**No model diversity.** XGBoost, RandomForest, and ExtraTrees explore different regions of the hypothesis space. XGBoost learns sequentially (correcting prior errors), RF learns in parallel (bagging + feature subsampling), and ExtraTrees adds randomized split points. Their errors are partially uncorrelated, so averaging their calibrated probabilities reduces variance without increasing bias.

The ensemble addresses all three by combining multiple independently-calibrated models with weights derived from walk-forward (out-of-sample) validation, not random-split CV.

---

## 2. Architecture

### Model Composition

```
                    ┌─────────────────┐
   Feature Dict ──▶ │  EnsembleSignal │
                    │     Model       │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌───────────┐ ┌───────────┐ ┌───────────┐
        │  XGBoost  │ │  Random   │ │  Extra    │
        │ Calibrated│ │  Forest   │ │  Trees    │
        │  (sigmoid)│ │ Calibrated│ │ Calibrated│
        └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
              │              │              │
              │  proba_1     │  proba_2     │  proba_3
              └──────────────┼──────────────┘
                             ▼
                   Weighted Average
                   (walk-forward AUC weights)
                             │
                             ▼
                    ┌─────────────────┐
                    │ PredictionResult│
                    │ {probability,   │
                    │  confidence,    │
                    │  signal, ...}   │
                    └─────────────────┘
```

### Base Model Hyperparameters

| Model | max_depth | n_estimators | learning_rate | Key Settings |
|-------|-----------|--------------|---------------|--------------|
| XGBoost | 6 | 200 | 0.05 | subsample=0.8, colsample_bytree=0.8, gamma=1 |
| RandomForest | 8 | 200 | N/A | min_samples_leaf=10, max_features=sqrt |
| ExtraTrees | 8 | 200 | N/A | min_samples_leaf=10, max_features=sqrt |

### Prediction Pipeline

1. Feature dict received (from FeatureEngine or MarketSnapshot minimal features).
2. Features aligned to `self.feature_names` order. Missing features filled with 0.0, NaN/None converted to 0.0.
3. Each calibrated base model produces `predict_proba(X)[:, 1]` — the class-1 probability.
4. Weighted average: `p = sum(w_i * p_i) / sum(w_i)`.
5. Output: `PredictionResult` dict with `prediction` (0/1), `probability`, `confidence` (= abs(p - 0.5) * 2), `signal` (bullish/bearish/neutral), `signal_strength`, `timestamp`.

### Drop-In Compatibility

`EnsembleSignalModel` implements the same public API as `SignalModel`: `predict()`, `predict_batch()`, `train()`, `save()`, `load()`, `backtest()`. It can be used anywhere `SignalModel` is accepted — including `MLEnhancedStrategy`, `RegimeModelRouter`, and the online retrainer.

---

## 3. Walk-Forward Validation

### Why Not Random-Split CV?

Trade data is chronological. Random 5-fold CV leaks future information into training (a 2025 trade in the training fold teaches the model about 2025 conditions that weren't knowable when evaluating a 2024 test fold). This inflates AUC by 5-15% and produces models that look good in backtests but fail in live trading.

### How Walk-Forward Weighting Works

The training data (80% of all trades after the test holdout) is split into K chronological folds:

```
Fold 1: Train [────────]  Test [──]
Fold 2: Train [───────────────]  Test [──]
Fold 3: Train [────────────────────]  Test [──]
Fold 4: Train [─────────────────────────]  Test [──]
```

For each fold k (k >= 1):
1. Train a clone of each base model on folds 0..k-1.
2. Score on fold k using AUC.
3. Accumulate per-model AUC scores.

After all folds, compute mean AUC per model. Convert to weights:
```
edge_i = max(0, mean_auc_i - 0.5)   # only above-chance performance counts
weight_i = edge_i / sum(edges)       # normalize to sum to 1.0
```

If all models are at or below chance level (AUC <= 0.5), weights fall back to equal (1/3 each).

**Default parameters:** `n_folds=5`, `min_fold_samples=30`.

### Separate Walk-Forward Validator

`compass/walk_forward.py` provides `WalkForwardValidator` for standalone model evaluation on the training CSV. It splits by calendar year (expanding window), computes accuracy, precision, recall, Brier score, AUC, and signal Sharpe per fold, and concatenates all out-of-sample predictions.

```python
from compass.walk_forward import WalkForwardValidator
from sklearn.ensemble import GradientBoostingClassifier

validator = WalkForwardValidator(GradientBoostingClassifier())
results = validator.run(pd.read_csv("compass/training_data_combined.csv"))
print(results["aggregate"])  # mean/std of all metrics across folds
```

---

## 4. Feature Importance Findings

Permutation importance analysis on the held-out test set (86 trades, 10 repeats) using the trained ensemble:

### Top Features (positive importance — shuffling hurts AUC)

| Rank | Feature | Importance | Std | Role |
|------|---------|------------|-----|------|
| 1 | `net_credit` | +0.032 | 0.017 | Trade structure: credit received per spread |
| 2 | `strategy_type_CS` | +0.013 | 0.020 | Whether this is a credit spread (vs IC) |
| 3 | `iv_rank` | +0.009 | 0.004 | IV rank at entry — core edge for premium selling |
| 4 | `dist_from_ma200_pct` | +0.007 | 0.004 | Long-term trend context |
| 5 | `momentum_5d_pct` | +0.004 | 0.005 | Short-term momentum |

### Bottom Features (negative importance — shuffling *improves* AUC)

| Rank | Feature | Importance | Std | Issue |
|------|---------|------------|-----|-------|
| 39 | `hold_days` | -0.015 | 0.008 | Look-ahead: only known after trade closes |
| 38 | `dte_at_entry` | -0.007 | 0.009 | Near-constant (all trades use similar DTE) |
| 37 | `vix_percentile_20d` | -0.005 | 0.004 | Noisy short-window percentile |
| 36 | `realized_vol_5d` | -0.005 | 0.007 | Too noisy at 5-day lookback |
| 35 | `spy_price` | -0.005 | 0.003 | Absolute price level is non-stationary |

22 of 39 features have negative importance. The full ranking is in `analysis/feature_importance.txt`.

### Recommended Feature Changes

**Add** (from FeatureEngine, not currently in training data):
1. `credit_to_width_ratio` — direct risk/reward metric
2. `vix_change_5d` — vol momentum catches regime transitions
3. `rv_iv_spread` — variance risk premium (the core theoretical edge)
4. `event_risk_score` / `days_to_fomc` — event proximity risk
5. `is_opex_week` — elevated gamma risk during OPEX

**Remove** (negative importance, hurting the model):
- `hold_days`, `spy_price`, `realized_vol_5d`, `realized_vol_10d`, `vix_percentile_20d`

Run the analysis yourself: `python scripts/feature_importance_analysis.py`

---

## 5. Training Pipeline

### Preparing Training Data

Training data is harvested from closed backtest trades via `compass/collect_training_data.py`:

```bash
# Generate training CSVs from backtest database
python -m compass.collect_training_data --config config_exp154.yaml --output compass/training_data_exp400.csv
python -m compass.collect_training_data --config configs/paper_champion.yaml --output compass/training_data_exp401.csv

# Merge and deduplicate
python -c "
from compass.collect_training_data import merge_datasets
merge_datasets(
    ['compass/training_data_exp400.csv', 'compass/training_data_exp401.csv'],
    'compass/training_data_combined.csv'
)
"
```

### Training the Ensemble

```python
from compass.ensemble_signal_model import EnsembleSignalModel
from compass.walk_forward import prepare_features, NUMERIC_FEATURES, CATEGORICAL_FEATURES
import pandas as pd

df = pd.read_csv("compass/training_data_combined.csv")
features = prepare_features(df, NUMERIC_FEATURES, CATEGORICAL_FEATURES)
labels = df["win"].values

model = EnsembleSignalModel(model_dir="ml/models")
stats = model.train(
    features,
    labels,
    calibrate=True,       # sigmoid calibration per base model
    save_model=True,      # saves to ml/models/ensemble_model_YYYYMMDD.joblib
    n_wf_folds=5,         # chronological folds for weight computation
)

print(f"Ensemble AUC: {stats['ensemble_test_auc']:.4f}")
print(f"Weights: {stats['ensemble_weights']}")
```

### What Gets Saved

`ml/models/ensemble_model_YYYYMMDD.joblib` contains:
- `calibrated_models` — dict of {name: CalibratedClassifierCV}
- `ensemble_weights` — dict of {name: float}
- `feature_names` — list of column names (order matters)
- `training_stats` — AUC, accuracy, precision, recall, per-model stats
- `feature_means` / `feature_stds` — for drift monitoring
- `timestamp` — training timestamp

---

## 6. Online Retraining

`compass/online_retrain.py` provides `ModelRetrainer` — a manager that monitors model staleness and automatically retrains when needed.

### Trigger Conditions

A retrain is triggered when ANY of these fire:

| Trigger | Default Threshold | Check |
|---------|-------------------|-------|
| Model age | 30 days | Model timestamp vs current date |
| Feature drift | 15% of features > 3 std devs | Compare recent feature distribution to training-time mean/std |
| Performance degradation | AUC drop > 0.05 | Evaluate current model on recent trades vs baseline AUC |

### A/B Promotion Gate

After retraining, the new model must pass an A/B holdout test:
1. The most recent 20% of training data is held out.
2. Both old and new models predict on the holdout.
3. New model is promoted if: `new_auc >= old_auc + min_promotion_auc_delta` (default: -0.005, i.e., a tiny regression is tolerated for a fresh model).
4. If the new model fails the gate, the old model stays in production.

### Version Management

- Models are saved with timestamps: `signal_model_YYYYMMDD_HHMMSS.joblib`
- The 3 most recent versions are kept on disk (configurable via `keep_versions`)
- Older versions are automatically pruned
- Each model has a companion `.feature_stats.json` for drift monitoring

### Usage

```python
from compass.online_retrain import ModelRetrainer

retrainer = ModelRetrainer(
    model_dir="ml/models",
    max_age_days=30,
    drift_threshold=3.0,
    perf_auc_drop=0.05,
    rolling_window_months=12,
    min_samples=100,
)

result = retrainer.check_and_retrain(features_df, labels)

if result.retrained:
    print(f"Retrained: {result.trigger.reasons}")
    if result.ab_result.promoted:
        print(f"New model promoted: {result.new_model_path}")
    else:
        print(f"New model rejected: {result.ab_result.reason}")
```

---

## 7. Configuration

### Enabling the Ensemble in a Config YAML

Add or modify the `ml_enhanced` section under `strategy`:

```yaml
strategy:
  ml_enhanced:
    enabled: true                    # Turn on ML gating
    ensemble_mode: true              # Use EnsembleSignalModel (XGB+RF+ET)
    model_dir: "ml/models"           # Directory containing ensemble_model_*.joblib
    confidence_threshold: 0.30       # Drop signals below this confidence (V1 mode)
    ml_sizing: false                 # false=V1 binary gating, true=V2 confidence sizing
    use_feature_engine: false        # false=minimal features, true=full FeatureEngine
```

### V1 vs V2 Mode

| Setting | `ml_sizing: false` (V1) | `ml_sizing: true` (V2) |
|---------|------------------------|------------------------|
| Behavior | Drop signals below `confidence_threshold` | Never drop; scale position size by confidence |
| Multiplier | N/A | `0.25 + confidence * 1.0` → range [0.25, 1.25] |
| Fallback | Pass signal through unfiltered | Apply 0.25x minimum multiplier |

### Model Loading

The system loads the most recent `ensemble_model_*.joblib` (or `signal_model_*.joblib` when `ensemble_mode: false`) from `model_dir` by file modification time. To pin a specific model version, rename or symlink it.

### Feature Engine Toggle

- `use_feature_engine: false` — Features are built from `MarketSnapshot` data (price, VIX, IV, regime) using `_minimal_features()` in `MLEnhancedStrategy`. Faster, fewer cache misses, but only ~15 features.
- `use_feature_engine: true` — Full `FeatureEngine.build_features()` with 46+ features including technicals, volatility surface, event risk, and seasonals. Requires data_provider for historical OHLCV lookups.

---

## 8. A/B Testing Setup

### Paper Trading A/B Test: EXP-400 vs EXP-702

The file `configs/paper_ensemble_test.yaml` defines the variant (EXP-702) for live A/B testing:

| | Control (EXP-400) | Variant (EXP-702) |
|--|-------|---------|
| Config | `configs/paper_champion.yaml` | `configs/paper_ensemble_test.yaml` |
| ML gating | None (all signals pass) | Ensemble V1 (confidence >= 0.30 required) |
| Strategy | Identical | Identical |
| Risk params | Identical | Identical |
| Regime detection | Identical | Identical |
| DB | `data/pilotai_exp400.db` | `data/exp702/pilotai_exp702.db` |
| Log | `logs/paper_champion.log` | `logs/paper_exp702_ensemble.log` |

### Running the A/B Test

```bash
# Terminal 1: Control
python main.py scheduler --config configs/paper_champion.yaml --env-file .env.champion

# Terminal 2: Variant (ensemble ML gate)
python main.py scheduler --config configs/paper_ensemble_test.yaml --env-file .env.ensemble_test
```

### Evaluation Criteria

After 30+ trades on each side, compare:
1. **Win rate** — Does the ensemble filter out losers?
2. **Average P&L per trade** — Does filtering improve average quality?
3. **Sharpe ratio** — Risk-adjusted returns.
4. **Max drawdown** — Does the ensemble avoid the worst losses?
5. **Trade count** — How many signals does the gate reject? (Too aggressive = missed profits.)

The `shared/deviation_tracker.py` module compares paper trading results against backtest expectations for each experiment.

---

## 9. Results vs Baseline

### Ensemble Training Results (2026-03-24)

| Metric | SignalModel (XGBoost only) | EnsembleSignalModel |
|--------|--------------------------|---------------------|
| Test AUC | 0.851 | **0.864** |
| Test Accuracy | 81.4% | **80.2%** |
| Test Precision | — | 81.1% |
| Test Recall | — | 86.0% |
| Training samples | 428 (combined) | 428 (combined) |
| Features | 39 | 39 |

### Per-Model Breakdown

| Base Model | Test AUC | Weight |
|------------|----------|--------|
| XGBoost | 0.851 | 0.318 |
| RandomForest | **0.878** | **0.343** |
| ExtraTrees | 0.852 | 0.338 |

RandomForest has the highest AUC and thus the highest weight. Weights are roughly equal (0.32-0.34), indicating all three models contribute meaningfully — no single model dominates.

### Key Observations

- **+1.3% AUC improvement** over standalone XGBoost (0.864 vs 0.851). On a 86-trade test set this is meaningful but not statistically definitive — the A/B paper trading test will provide the real answer.
- **Recall (86%) > Precision (81%)** — the ensemble correctly identifies most profitable trades but has some false positives. For a premium-selling strategy where the base win rate is ~58%, this bias toward recall is appropriate (missing a winner costs more than filtering a loser).
- **Calibration matters more than raw AUC.** The real value of the ensemble is not the +1.3% AUC but the more stable probability estimates from averaging three independently-calibrated models. This directly improves position sizing in V2 mode.

### Backtest Performance Context

The ML system operates on top of a strategy that already achieves 78-95% win rates across different years (see `output/backtest_results_polygon_REAL_*.json`). The ML gate's job is not to find trades — it's to filter out the 5-22% of trades that lose, which account for outsized dollar losses (avg loss = 2-7x avg win). Even filtering 20% of losers with a 10% false-positive rate would materially improve the Sharpe ratio.
