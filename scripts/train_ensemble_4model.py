#!/usr/bin/env python3
"""
Train and evaluate the 4-model ensemble (XGBoost + LightGBM + RF + ExtraTrees).

Loads training data from compass/training_data_combined.csv, prepares features
using the same pipeline as ml_walkforward_train.py, then trains the ensemble
via EnsembleSignalModel.train().

Prints per-model and ensemble metrics, compares with the production XGBoost
baseline from ml/models/signal_model_20260321.joblib, and saves the trained
ensemble to ml/models/.

Usage:
    python scripts/train_ensemble_4model.py
    python scripts/train_ensemble_4model.py --data compass/training_data_combined.csv
    python scripts/train_ensemble_4model.py --no-save    # evaluate only, don't save
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# Resolve project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from compass.ensemble_signal_model import EnsembleSignalModel, _build_base_models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────

DEFAULT_DATA = PROJECT_ROOT / "compass" / "training_data_combined.csv"
MODEL_DIR = PROJECT_ROOT / "ml" / "models"
BASELINE_MODEL = MODEL_DIR / "signal_model_20260321.joblib"

RAW_FEATURE_COLS = [
    'day_of_week', 'days_since_last_trade', 'dte_at_entry',
    'rsi_14', 'momentum_5d_pct', 'momentum_10d_pct',
    'vix', 'vix_percentile_20d', 'vix_percentile_50d', 'vix_percentile_100d',
    'iv_rank',
    'dist_from_ma20_pct', 'dist_from_ma50_pct', 'dist_from_ma80_pct', 'dist_from_ma200_pct',
    'ma20_slope_ann_pct', 'ma50_slope_ann_pct',
    'realized_vol_atr20', 'realized_vol_5d', 'realized_vol_10d', 'realized_vol_20d',
]

CAT_COLS = ['strategy_type', 'regime']
LABEL_COL = 'win'


# ── Data loading ────────────────────────────────────────────────────────────

def load_and_prepare(data_path: Path) -> tuple:
    """Load CSV, one-hot encode categoricals, return (features_df, labels)."""
    df = pd.read_csv(data_path)
    logger.info("Loaded %d trades from %s", len(df), data_path)

    # One-hot encode
    for col in CAT_COLS:
        if col in df.columns:
            dummies = pd.get_dummies(df[col], prefix=col, dtype=float)
            df = pd.concat([df, dummies], axis=1)

    # Build feature columns
    encoded_cols = sorted(
        c for c in df.columns
        if any(c.startswith(f'{cat}_') for cat in CAT_COLS)
    )
    feature_cols = RAW_FEATURE_COLS + encoded_cols

    # Fill NaN
    df[feature_cols] = df[feature_cols].fillna(0.0)

    features_df = df[feature_cols]
    labels = df[LABEL_COL].values.astype(int)

    logger.info("Features: %d columns, %d samples", len(feature_cols), len(features_df))
    logger.info("Label distribution: %s", dict(zip(*np.unique(labels, return_counts=True))))

    return features_df, labels


# ── Baseline loading ────────────────────────────────────────────────────────

def load_baseline_stats() -> dict:
    """Load training stats from the production XGBoost model."""
    if not BASELINE_MODEL.exists():
        logger.warning("Baseline model not found at %s", BASELINE_MODEL)
        return {}

    data = joblib.load(BASELINE_MODEL)
    stats = data.get('training_stats', {})
    return stats


# ── Printing ────────────────────────────────────────────────────────────────

def _bar(label, width=70):
    print(f"\n{'─' * width}")
    print(f"  {label}")
    print(f"{'─' * width}")


def print_model_roster():
    """Print which models are available in the ensemble."""
    _bar("ENSEMBLE MODEL ROSTER")
    models = _build_base_models()
    for i, (name, est) in enumerate(models, 1):
        cls_name = type(est).__name__
        n_est = getattr(est, 'n_estimators', '?')
        depth = getattr(est, 'max_depth', '?')
        lr = getattr(est, 'learning_rate', 'n/a')
        print(f"  {i}. {name:<20s}  {cls_name:<30s}  trees={n_est}  depth={depth}  lr={lr}")
    print(f"\n  Total models: {len(models)}")

    try:
        import lightgbm
        print(f"  LightGBM version: {lightgbm.__version__}")
    except ImportError:
        print("  LightGBM: NOT INSTALLED")

    try:
        import xgboost
        print(f"  XGBoost version: {xgboost.__version__}")
    except ImportError:
        print("  XGBoost: NOT INSTALLED")


def print_ensemble_results(stats: dict):
    """Print ensemble training results."""
    _bar("ENSEMBLE TRAINING RESULTS")

    print(f"  Ensemble Test AUC:       {stats.get('ensemble_test_auc', 0):.4f}")
    print(f"  Ensemble Test Accuracy:  {stats.get('ensemble_test_accuracy', 0):.4f}")
    print(f"  Ensemble Test Precision: {stats.get('ensemble_test_precision', 0):.4f}")
    print(f"  Ensemble Test Recall:    {stats.get('ensemble_test_recall', 0):.4f}")
    print(f"  Samples: train={stats.get('n_train', 0)}, cal={stats.get('n_calibration', 0)}, test={stats.get('n_test', 0)}")
    print(f"  Features: {stats.get('n_features', 0)}")
    print(f"  Positive rate: {stats.get('positive_rate', 0):.3f}")

    _bar("PER-MODEL BREAKDOWN")
    per_model = stats.get('per_model', {})
    header = f"  {'Model':<20s}  {'AUC':>7s}  {'Acc':>7s}  {'Prec':>7s}  {'Recall':>7s}  {'Weight':>7s}"
    print(header)
    print(f"  {'─' * (len(header) - 2)}")
    for name, ms in sorted(per_model.items()):
        print(
            f"  {name:<20s}  {ms['test_auc']:>7.4f}  {ms['test_accuracy']:>7.4f}  "
            f"{ms['test_precision']:>7.4f}  {ms['test_recall']:>7.4f}  {ms['weight']:>7.3f}"
        )

    _bar("ENSEMBLE WEIGHTS")
    weights = stats.get('ensemble_weights', {})
    for name, w in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        bar_len = int(w * 40)
        print(f"  {name:<20s}  {w:.3f}  {'█' * bar_len}")

    _bar("QUALITY GATES")
    gates = stats.get('gates', {})
    for gate, passed in gates.items():
        marker = "PASS" if passed else "FAIL"
        icon = "+" if passed else "x"
        print(f"  {icon} {gate:<25s} {marker}")

    cal_bins = stats.get('calibration_bins', [])
    if cal_bins:
        _bar("CALIBRATION BINS")
        for b in cal_bins:
            ev = "  " if b.get('evaluable') else " *"
            print(
                f"  {b['bin']:<12s}  n={b['n']:<4d}  "
                f"predicted={b['predicted']:.3f}  actual={b['actual']:.3f}  "
                f"gap={b['gap']:.3f}{ev}"
            )


def print_comparison(ensemble_stats: dict, baseline_stats: dict):
    """Compare ensemble vs baseline XGBoost."""
    _bar("ENSEMBLE vs BASELINE XGBOOST")

    baseline_folds = baseline_stats.get('walk_forward_folds', [])
    if not baseline_folds:
        print("  (no baseline walk-forward data available)")
        return

    baseline_aucs = [f['auc'] for f in baseline_folds if 'auc' in f]
    baseline_accs = [f['accuracy'] for f in baseline_folds if 'accuracy' in f]
    baseline_avg_auc = np.mean(baseline_aucs) if baseline_aucs else 0
    baseline_avg_acc = np.mean(baseline_accs) if baseline_accs else 0

    ens_auc = ensemble_stats.get('ensemble_test_auc', 0)
    ens_acc = ensemble_stats.get('ensemble_test_accuracy', 0)

    auc_delta = ens_auc - baseline_avg_auc
    acc_delta = ens_acc - baseline_avg_acc

    auc_dir = "+" if auc_delta >= 0 else ""
    acc_dir = "+" if acc_delta >= 0 else ""

    header = f"  {'Metric':<20s}  {'Baseline (XGB)':>15s}  {'Ensemble (4-model)':>18s}  {'Delta':>10s}"
    print(header)
    print(f"  {'─' * (len(header) - 2)}")
    print(f"  {'AUC':<20s}  {baseline_avg_auc:>15.4f}  {ens_auc:>18.4f}  {auc_dir}{auc_delta:>9.4f}")
    print(f"  {'Accuracy':<20s}  {baseline_avg_acc:>15.4f}  {ens_acc:>18.4f}  {acc_dir}{acc_delta:>9.4f}")

    n_baseline_models = 1
    n_ensemble_models = len(ensemble_stats.get('per_model', {}))
    print(f"  {'Models':<20s}  {n_baseline_models:>15d}  {n_ensemble_models:>18d}")

    baseline_g3 = baseline_stats.get('gates', {}).get('g3_calibration', False)
    ensemble_g3 = ensemble_stats.get('gates', {}).get('g3_calibration', False)
    b_str = "PASS" if baseline_g3 else "FAIL"
    e_str = "PASS" if ensemble_g3 else "FAIL"
    print(f"  {'Calibration (G3)':<20s}  {b_str:>15s}  {e_str:>18s}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Train 4-model ensemble")
    parser.add_argument(
        "--data", type=Path, default=DEFAULT_DATA,
        help="Path to training CSV",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Evaluate only, don't save model to disk",
    )
    parser.add_argument(
        "--wf-folds", type=int, default=5,
        help="Number of walk-forward folds (default 5)",
    )
    args = parser.parse_args()

    if not args.data.exists():
        print(f"ERROR: training data not found at {args.data}")
        sys.exit(1)

    # 1. Show model roster
    print_model_roster()

    # 2. Load data
    features_df, labels = load_and_prepare(args.data)

    # 3. Train ensemble
    _bar("TRAINING ENSEMBLE")
    model = EnsembleSignalModel(model_dir=str(MODEL_DIR))
    stats = model.train(
        features_df,
        labels,
        calibrate=True,
        save_model=not args.no_save,
        n_wf_folds=args.wf_folds,
    )

    if not stats:
        print("\nERROR: Training failed — check logs above.")
        sys.exit(1)

    # 4. Print results
    print_ensemble_results(stats)

    # 5. Compare with baseline
    baseline_stats = load_baseline_stats()
    if baseline_stats:
        print_comparison(stats, baseline_stats)

    # 6. Summary
    _bar("SUMMARY")
    n_models = len(stats.get('per_model', {}))
    all_pass = stats.get('gates', {}).get('all_pass', False)
    print(f"  Models trained:  {n_models}")
    print(f"  All gates pass:  {all_pass}")
    if not args.no_save and model.trained:
        files = sorted(MODEL_DIR.glob("ensemble_model_*.joblib"), key=lambda p: p.stat().st_mtime)
        if files:
            print(f"  Saved to:        {files[-1]}")

    print()


if __name__ == "__main__":
    main()
