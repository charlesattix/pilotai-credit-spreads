# Migration Guide: XGBoost to Ensemble

Production migration guide for switching from the single-XGBoost `SignalModel` to the `EnsembleSignalModel` (XGBoost + RandomForest + ExtraTrees).

---

## Prerequisites

Before starting the migration:

- [ ] Branch `maximus/ensemble-ml` is merged to `main`
- [ ] A trained ensemble model exists at `ml/models/ensemble_model_*.joblib`
- [ ] The A/B paper trading test (EXP-702 vs EXP-400) has run for 30+ trades with no regressions
- [ ] All tests pass: `python -m pytest tests/ --ignore=tests/test_macro_api.py -x`

---

## 1. Switching from XGBoost to Ensemble

### Step 1: Verify the trained model exists

```bash
ls -la ml/models/ensemble_model_*.joblib
```

If no model exists, train one first:

```bash
python scripts/train_ensemble.py
```

This will:
1. Load training data from `compass/training_data_combined.csv`
2. Run walk-forward validation (5 chronological folds) to compute ensemble weights
3. Train XGBoost, RandomForest, and ExtraTrees on the full training set
4. Calibrate each model via sigmoid method on a held-out calibration split
5. Save to `ml/models/ensemble_model_YYYYMMDD.joblib`

### Step 2: Verify model quality

```bash
python scripts/benchmark_models.py
```

Check that:
- Ensemble test AUC >= 0.80 (minimum viable)
- Ensemble test AUC >= SignalModel test AUC (should be at least equal)
- No single base model has weight < 0.10 (indicates a degenerate learner)
- Positive rate is between 0.40 and 0.80 (class balance is reasonable)

### Step 3: Update the experiment config

In your experiment YAML (e.g., `configs/paper_champion.yaml`), add or modify the `ml_enhanced` section under `strategy`:

```yaml
strategy:
  # ... existing strategy params unchanged ...

  ml_enhanced:
    enabled: true              # Turn on ML gating
    ensemble_mode: true        # Use EnsembleSignalModel instead of SignalModel
    model_dir: "ml/models"     # Directory containing ensemble_model_*.joblib
    confidence_threshold: 0.30 # Drop signals with confidence < 0.30
    ml_sizing: false           # V1: binary gating (recommended for initial rollout)
    use_feature_engine: false  # false = minimal features (faster, fewer cache misses)
```

### Step 4: Restart the scanner

```bash
python main.py scheduler --config configs/your_config.yaml --env-file .env.your_experiment
```

The scanner will:
1. Detect `ml_enhanced.ensemble_mode: true`
2. Load the most recent `ensemble_model_*.joblib` from `model_dir`
3. Wrap the base strategy in `MLEnhancedStrategy`
4. Gate signals through the ensemble before sending alerts

---

## 2. Config Changes Reference

### Minimal change (enable ensemble gating)

Add this block to any existing experiment config:

```yaml
strategy:
  ml_enhanced:
    enabled: true
    ensemble_mode: true
```

All other fields have safe defaults. The system loads the most recent model from `ml/models/`.

### Full configuration reference

```yaml
strategy:
  ml_enhanced:
    enabled: true                      # Master switch
    ensemble_mode: true                # true=ensemble, false=single XGBoost
    model_dir: "ml/models"             # Model artifact directory
    confidence_threshold: 0.30         # V1: minimum confidence to pass gate
    ml_sizing: false                   # false=V1 binary gate, true=V2 sizing
    use_feature_engine: false          # true=full 46-feature FeatureEngine
    regime_model_paths:                # Optional: per-regime model overrides
      bear: "ml/models/bear_model.joblib"
      defensive: "ml/models/defensive_model.joblib"
```

### V1 vs V2 mode

| | V1 (`ml_sizing: false`) | V2 (`ml_sizing: true`) |
|--|---|---|
| Behavior | Signals below `confidence_threshold` are dropped | All signals pass; position size scaled by confidence |
| Size multiplier | N/A | `0.25 + confidence * 1.0` (range 0.25x to 1.25x) |
| Trade count | Reduced (filtered) | Same as baseline (never drops) |
| Recommended for | Initial rollout, conservative | After V1 proven in paper trading |

**Recommendation:** Start with V1 (`ml_sizing: false`, `confidence_threshold: 0.30`). Switch to V2 only after 60+ paper trades confirm V1 improves signal quality.

### Configs that should NOT change

These sections remain identical whether ensemble is enabled or not:
- `strategy.min_dte`, `max_dte`, `target_dte`, `spread_width`, `direction`
- `strategy.regime_mode`, `regime_config`
- `risk.*` (all risk management params)
- `alpaca.*`, `alerts.*`, `data.*`, `logging.*`

The ensemble gate is a pure signal filter — it does not change trade structure, sizing rules, or risk management.

---

## 3. Rollback Procedure

### Immediate rollback (disable ensemble, keep scanner running)

Edit the config and change one line:

```yaml
strategy:
  ml_enhanced:
    enabled: false    # ← disable ML gating entirely
```

Restart the scanner. All signals pass through unfiltered, identical to pre-ensemble behavior.

### Rollback to single XGBoost (keep ML gating, drop ensemble)

```yaml
strategy:
  ml_enhanced:
    enabled: true
    ensemble_mode: false    # ← use SignalModel (single XGBoost) instead
```

This uses the most recent `signal_model_*.joblib` from `model_dir`. Requires a trained single-XGBoost model on disk.

### Rollback to a previous model version

The system loads the most recent `.joblib` by file modification time. To pin a specific version:

```bash
# List available versions
ls -lt ml/models/ensemble_model_*.joblib

# Rollback: touch the desired version to make it "most recent"
touch ml/models/ensemble_model_20260301.joblib

# Restart scanner — it will load the touched file
```

Alternatively, rename or move newer models out of `model_dir/`.

### Emergency rollback (no restart)

If the scanner is running and the ensemble is producing bad signals:

1. The ensemble falls back to neutral predictions (probability=0.5, confidence=0.0) on any error.
2. In V1 mode, confidence=0.0 < threshold=0.30, so all signals are blocked.
3. In V2 mode, confidence=0.0 maps to multiplier=0.25x (minimum sizing, not zero).

To force a fallback without restarting: rename or delete the model file. The next prediction call will fail to load the model and return the neutral fallback.

```bash
mv ml/models/ensemble_model_20260324.joblib ml/models/ensemble_model_20260324.joblib.disabled
```

### Rollback decision criteria

Roll back to XGBoost (or disable ML entirely) if ANY of these are true after 30+ live/paper trades:

| Metric | Rollback threshold |
|--------|--------------------|
| Win rate | Drops > 5 percentage points vs control |
| Avg P&L per trade | Negative when control is positive |
| Max drawdown | > 150% of control's max drawdown |
| Signal rejection rate | > 60% of signals filtered (too aggressive) |
| Fallback rate | > 10% of predictions returning fallback (model health issue) |

---

## 4. Monitoring Ensemble Health

### Daily checks

**1. Fallback counter**

The ensemble tracks prediction failures via `fallback_counter`. Check it after each scan cycle:

```python
from compass.ensemble_signal_model import EnsembleSignalModel

model = EnsembleSignalModel(model_dir="ml/models")
model.load()
print(model.get_fallback_stats())
# Expected: {'predict': 0, 'predict_batch': 0}
# Alert if: any counter > 10
```

In logs, search for:
```
grep "fallback" logs/paper_*.log | tail -20
```

**2. Feature drift warnings**

The model logs a warning when any feature is > 3 std devs from its training distribution:

```
grep "std devs from training mean" logs/paper_*.log | tail -20
```

Occasional drift warnings are normal (market conditions change). Persistent drift across 5+ features over multiple days indicates the model is stale and needs retraining.

**3. Prediction distribution**

Monitor that predictions are not degenerate (all 0.5, all > 0.9, etc.):

```python
# After a scan cycle, check recent predictions in the database
from shared.database import get_trades
trades = get_trades(source="scanner")
ml_confs = [t.get("ml_confidence", 0) for t in trades[-20:]]
print(f"Recent ML confidence: mean={sum(ml_confs)/len(ml_confs):.3f}, "
      f"min={min(ml_confs):.3f}, max={max(ml_confs):.3f}")
```

Healthy range: confidence spread across [0.1, 0.9]. If all predictions cluster at 0.0 or 0.5, the model has failed to load or is returning fallbacks.

### Weekly checks

**4. Model age**

```python
import joblib
data = joblib.load("ml/models/ensemble_model_20260324.joblib")
print(f"Model trained: {data['timestamp']}")
# Alert if > 30 days old
```

**5. A/B paper trading comparison**

Compare EXP-702 (ensemble variant) vs EXP-400 (control) weekly:

```bash
python scripts/check_accounts.py
```

Review: win rate, avg P&L per trade, Sharpe, max drawdown, and number of trades on each side.

**6. Walk-forward validation on latest data**

Re-run walk-forward to check if the model still generalizes:

```bash
python -c "
from compass.walk_forward import WalkForwardValidator
from sklearn.ensemble import GradientBoostingClassifier
import pandas as pd

df = pd.read_csv('compass/training_data_combined.csv')
validator = WalkForwardValidator(GradientBoostingClassifier(n_estimators=50))
results = validator.run(df)
print(f\"OOS AUC: {results['aggregate'].get('auc_mean', 'N/A')}\")
print(f\"OOS Brier: {results['aggregate']['brier_score_mean']:.4f}\")
"
```

### Automated monitoring via online retrainer

The `ModelRetrainer` encapsulates all of the above checks:

```python
from compass.online_retrain import ModelRetrainer

retrainer = ModelRetrainer(
    model_dir="ml/models",
    max_age_days=30,          # Trigger if model > 30 days old
    drift_threshold=3.0,      # Flag features > 3 std devs from training mean
    drift_feature_pct=0.15,   # Trigger if > 15% of features are drifted
    perf_auc_drop=0.05,       # Trigger if AUC drops > 0.05 from baseline
)

# Run as part of a weekly cron job:
result = retrainer.check_and_retrain(features_df, labels)
if result.trigger.triggered:
    print(f"Retrain triggered: {result.trigger.reasons}")
if result.retrained and result.ab_result.promoted:
    print(f"New model promoted: {result.new_model_path}")
```

---

## 5. Training Schedule

### Monthly retrain (recommended cadence)

The ensemble should be retrained monthly to adapt to changing market regimes. The default `max_age_days=30` in `ModelRetrainer` enforces this automatically.

### Manual monthly retrain

Run on the 1st of each month (or after 50+ new closed trades accumulate):

```bash
# Step 1: Regenerate training data from latest closed trades
python -m compass.collect_training_data \
    --config config_exp154.yaml \
    --output compass/training_data_exp400.csv

python -m compass.collect_training_data \
    --config configs/paper_champion.yaml \
    --output compass/training_data_exp401.csv

# Step 2: Merge and deduplicate
python -c "
from compass.collect_training_data import merge_datasets
merge_datasets(
    ['compass/training_data_exp400.csv', 'compass/training_data_exp401.csv'],
    'compass/training_data_combined.csv'
)
"

# Step 3: Train new ensemble
python scripts/train_ensemble.py

# Step 4: Benchmark against previous model
python scripts/benchmark_models.py

# Step 5: Run feature importance to check for drift
python scripts/feature_importance_analysis.py
```

### Automated monthly retrain via `ModelRetrainer`

Add to a cron job or scheduler hook:

```python
import pandas as pd
import numpy as np
from compass.online_retrain import ModelRetrainer
from compass.walk_forward import prepare_features, NUMERIC_FEATURES, CATEGORICAL_FEATURES

# Load latest training data
df = pd.read_csv("compass/training_data_combined.csv")
features = prepare_features(df, NUMERIC_FEATURES, CATEGORICAL_FEATURES)
labels = df["win"].values.astype(int)

# Check triggers and retrain if needed
retrainer = ModelRetrainer(
    model_dir="ml/models",
    max_age_days=30,
    rolling_window_months=12,  # Train on last 12 months of trades
    keep_versions=3,           # Keep 3 versions for rollback
    min_samples=100,           # Need at least 100 trades to retrain
)

result = retrainer.check_and_retrain(features, labels)
print(f"Triggered: {result.trigger.triggered}")
print(f"Reasons: {result.trigger.reasons}")
print(f"Retrained: {result.retrained}")
if result.ab_result:
    print(f"Old AUC: {result.ab_result.old_auc:.4f}")
    print(f"New AUC: {result.ab_result.new_auc:.4f}")
    print(f"Promoted: {result.ab_result.promoted}")
```

### Emergency retrain triggers

Retrain immediately (don't wait for the monthly cycle) if:

| Condition | Action |
|-----------|--------|
| VIX regime shift (VIX crosses 30 for 5+ consecutive days) | Retrain with `force=True` |
| 3 consecutive stop-loss exits on ML-gated trades | Check model health, retrain if AUC dropped |
| Feature drift warnings on 5+ features for 3+ consecutive days | Retrain immediately |
| New strategy type added (e.g., iron butterfly) | Regenerate training data, retrain |

### What NOT to do

- **Do not retrain daily.** 428 trades is too small; daily retraining causes overfitting to recent noise.
- **Do not retrain on losing streaks alone.** Credit spreads have inherent loss clustering (correlated gamma risk). A 3-trade losing streak does not mean the model is broken.
- **Do not skip the A/B holdout gate.** Even with `force=True`, the retrainer compares old vs new on the holdout. Never deploy a model that fails the holdout check without manual review.
- **Do not train on paper trading data that includes ML-gated signals.** This creates a feedback loop (the model learns to predict its own filtering decisions). Always train on unfiltered backtest data or control-experiment (no ML gate) paper trades.
