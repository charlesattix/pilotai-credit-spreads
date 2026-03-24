#!/usr/bin/env python3
"""
Train Pruned Ensemble — drop 9 harmful features identified by ablation analysis.

Harmful features (hurt OOS AUC when included):
  hold_days, dte_at_entry, spy_price, realized_vol_5d, realized_vol_10d,
  vix_percentile_20d, ma20_slope_ann_pct, day_of_week, otm_pct

Pipeline:
  1. Load cached training data (or run backtests).
  2. Prepare features with the 9 harmful columns removed.
  3. Train pruned EnsembleSignalModel.
  4. Walk-forward validate pruned vs unpruned vs XGBoost baseline.
  5. Save the pruned model only if it beats the unpruned ensemble on WF AUC.

Usage:
    cd /home/node/.openclaw/workspace/pilotai-credit-spreads
    PYTHONPATH=. python3 scripts/train_ensemble_pruned.py
"""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from compass.collect_training_data import (
    _load_full_market_data,
    enrich_trades,
    run_year_backtest_exp400,
    YEARS,
)
from compass.ensemble_signal_model import EnsembleSignalModel
from compass.signal_model import SignalModel
from compass.walk_forward import (
    WalkForwardValidator,
    prepare_features,
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    TARGET_COL,
)
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_pruned")

MODEL_DIR = ROOT / "ml" / "models"
COMBINED_CSV = ROOT / "compass" / "training_data_combined.csv"
CACHE_CSV = ROOT / "compass" / "training_data_exp400.csv"
DEFAULT_BASELINE = "signal_model_20260321.joblib"

# ── Features to drop ────────────────────────────────────────────────────────
HARMFUL_FEATURES = [
    "hold_days",
    "dte_at_entry",
    "spy_price",
    "realized_vol_5d",
    "realized_vol_10d",
    "vix_percentile_20d",
    "ma20_slope_ann_pct",
    "day_of_week",
    "otm_pct",
]

# Pruned feature lists (remove harmful from defaults)
PRUNED_NUMERIC = [f for f in NUMERIC_FEATURES if f not in HARMFUL_FEATURES]


# ═══════════════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════════════

def load_data() -> pd.DataFrame:
    """Load training data from cache or run backtests."""
    for path in [COMBINED_CSV, CACHE_CSV]:
        if path.exists():
            logger.info("Loading cached data from %s", path)
            df = pd.read_csv(path)
            logger.info("  %d trades loaded", len(df))
            return df

    logger.info("No cached data — running EXP-400 backtests")
    full_spy, full_vix = _load_full_market_data()
    all_trades = []
    for year in YEARS:
        bt, results = run_year_backtest_exp400(year)
        trades = enrich_trades(bt, year, spy_closes=full_spy["Close"], vix_series=full_vix)
        logger.info("  Year %d: %d trades", year, len(trades))
        all_trades.extend(trades)
    df = pd.DataFrame(all_trades).sort_values("entry_date").reset_index(drop=True)
    df.to_csv(CACHE_CSV, index=False)
    return df


# ═══════════════════════════════════════════════════════════════════════════
# Walk-forward helper
# ═══════════════════════════════════════════════════════════════════════════

def _make_voting_classifier():
    """Build VotingClassifier matching EnsembleSignalModel base learners."""
    import xgboost as xgb
    from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier, VotingClassifier

    return VotingClassifier(
        estimators=[
            ("xgboost", xgb.XGBClassifier(
                objective="binary:logistic",
                max_depth=6, learning_rate=0.05, n_estimators=200,
                min_child_weight=5, subsample=0.8, colsample_bytree=0.8,
                gamma=1, reg_alpha=0.1, reg_lambda=1.0,
                random_state=42, eval_metric="logloss",
            )),
            ("random_forest", RandomForestClassifier(
                n_estimators=200, max_depth=8, min_samples_leaf=5,
                max_features="sqrt", random_state=42, n_jobs=-1,
            )),
            ("extra_trees", ExtraTreesClassifier(
                n_estimators=200, max_depth=8, min_samples_leaf=5,
                max_features="sqrt", random_state=42, n_jobs=-1,
            )),
        ],
        voting="soft",
    )


def run_walk_forward(df: pd.DataFrame, numeric_features, label: str) -> Dict:
    """Run walk-forward validation with the given numeric features."""
    validator = WalkForwardValidator(
        model=_make_voting_classifier(),
        numeric_features=numeric_features,
        categorical_features=CATEGORICAL_FEATURES,
        min_train_samples=30,
    )
    return validator.run(df)


def log_wf_results(label: str, wf: Dict) -> None:
    """Pretty-print walk-forward results."""
    agg = wf["aggregate"]
    logger.info("")
    logger.info("  [%s] %d folds, %d total OOS samples:", label, wf["n_folds"], agg["total_oos_samples"])
    for fold in wf["folds"]:
        auc_str = f"{fold['auc']:.4f}" if fold["auc"] is not None else "N/A"
        logger.info(
            "    Fold %d: %s  train=%d test=%d  AUC=%s  Acc=%.4f  Brier=%.4f",
            fold["fold"], fold["test_period"],
            fold["n_train"], fold["n_test"],
            auc_str, fold["accuracy"], fold["brier_score"],
        )
    logger.info(
        "    Mean AUC=%.4f +/- %.4f   Acc=%.4f +/- %.4f   Brier=%.4f +/- %.4f",
        agg.get("auc_mean") or 0, agg.get("auc_std") or 0,
        agg["accuracy_mean"], agg["accuracy_std"],
        agg["brier_score_mean"], agg["brier_score_std"],
    )


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    logger.info("=" * 70)
    logger.info("  PRUNED ENSEMBLE TRAINING PIPELINE")
    logger.info("  %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 70)

    # ── Step 1: Load data ────────────────────────────────────────────────
    df = load_data()
    labels = df[TARGET_COL].values.astype(int)
    logger.info("  %d trades, win rate %.1f%%", len(df), labels.mean() * 100)

    # ── Step 2: Show what's being pruned ─────────────────────────────────
    logger.info("")
    logger.info("=" * 70)
    logger.info("  FEATURE PRUNING")
    logger.info("=" * 70)
    logger.info("  Dropping %d harmful numeric features:", len(HARMFUL_FEATURES))
    for f in HARMFUL_FEATURES:
        logger.info("    - %s", f)
    logger.info("")
    logger.info("  Unpruned numeric: %d features", len(NUMERIC_FEATURES))
    logger.info("  Pruned numeric:   %d features", len(PRUNED_NUMERIC))
    logger.info("  Categorical:      %s (unchanged)", CATEGORICAL_FEATURES)
    logger.info("  Kept features:    %s", PRUNED_NUMERIC)

    # ── Step 3: Prepare both feature sets ────────────────────────────────
    features_full = prepare_features(df, NUMERIC_FEATURES, CATEGORICAL_FEATURES)
    features_pruned = prepare_features(df, PRUNED_NUMERIC, CATEGORICAL_FEATURES)
    logger.info("")
    logger.info("  Unpruned matrix: %d x %d", *features_full.shape)
    logger.info("  Pruned matrix:   %d x %d", *features_pruned.shape)

    # ── Step 4: Train pruned ensemble ────────────────────────────────────
    logger.info("")
    logger.info("=" * 70)
    logger.info("  TRAINING PRUNED ENSEMBLE")
    logger.info("=" * 70)
    pruned_model = EnsembleSignalModel(model_dir=str(MODEL_DIR))
    pruned_stats = pruned_model.train(
        features_pruned, labels,
        calibrate=True, save_model=False, n_wf_folds=5,
    )
    if not pruned_stats:
        logger.error("Pruned ensemble training failed")
        sys.exit(1)

    logger.info("")
    logger.info("  Pruned ensemble results:")
    logger.info("    Test AUC:       %.4f", pruned_stats["ensemble_test_auc"])
    logger.info("    Test Accuracy:  %.4f", pruned_stats["ensemble_test_accuracy"])
    logger.info("    Test Precision: %.4f", pruned_stats["ensemble_test_precision"])
    logger.info("    Test Recall:    %.4f", pruned_stats["ensemble_test_recall"])
    logger.info("    Gates:          %s", pruned_stats.get("gates", {}))
    logger.info("    Weights:")
    for name, w in pruned_stats["ensemble_weights"].items():
        pm = pruned_stats["per_model"].get(name, {})
        logger.info("      %-15s  weight=%.3f  AUC=%.4f", name, w, pm.get("test_auc", 0))

    # ── Step 5: Walk-forward comparison — Pruned vs Unpruned vs XGBoost ──
    logger.info("")
    logger.info("=" * 70)
    logger.info("  WALK-FORWARD VALIDATION")
    logger.info("=" * 70)

    wf_pruned = run_walk_forward(df, PRUNED_NUMERIC, "Pruned Ensemble")
    log_wf_results("Pruned Ensemble", wf_pruned)

    wf_unpruned = run_walk_forward(df, NUMERIC_FEATURES, "Unpruned Ensemble")
    log_wf_results("Unpruned Ensemble", wf_unpruned)

    # XGBoost baseline for reference
    import xgboost as xgb
    xgb_model = xgb.XGBClassifier(
        objective="binary:logistic", max_depth=6, learning_rate=0.05,
        n_estimators=200, min_child_weight=5, subsample=0.8,
        colsample_bytree=0.8, gamma=1, reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, eval_metric="logloss",
    )
    xgb_validator = WalkForwardValidator(
        model=xgb_model,
        numeric_features=NUMERIC_FEATURES,
        categorical_features=CATEGORICAL_FEATURES,
        min_train_samples=30,
    )
    wf_xgb = xgb_validator.run(df)
    log_wf_results("XGBoost Baseline", wf_xgb)

    # ── Step 6: Head-to-head comparison table ────────────────────────────
    logger.info("")
    logger.info("=" * 70)
    logger.info("  HEAD-TO-HEAD COMPARISON (Walk-Forward OOS)")
    logger.info("=" * 70)

    agg_p = wf_pruned["aggregate"]
    agg_u = wf_unpruned["aggregate"]
    agg_x = wf_xgb["aggregate"]

    logger.info(
        "  %-18s %12s %12s %12s",
        "Metric", "XGBoost", "Unpruned", "Pruned",
    )
    logger.info("  " + "-" * 56)
    for metric_key, metric_label in [
        ("auc_mean", "AUC"),
        ("accuracy_mean", "Accuracy"),
        ("brier_score_mean", "Brier Score"),
    ]:
        xv = agg_x.get(metric_key)
        uv = agg_u.get(metric_key)
        pv = agg_p.get(metric_key)
        logger.info(
            "  %-18s %12s %12s %12s",
            metric_label,
            f"{xv:.4f}" if xv is not None else "N/A",
            f"{uv:.4f}" if uv is not None else "N/A",
            f"{pv:.4f}" if pv is not None else "N/A",
        )

    # Per-fold AUC comparison
    logger.info("")
    logger.info("  Per-fold AUC:")
    logger.info("  %-8s %12s %12s %12s", "Fold", "XGBoost", "Unpruned", "Pruned")
    logger.info("  " + "-" * 46)
    for i in range(max(len(wf_xgb["folds"]), len(wf_unpruned["folds"]), len(wf_pruned["folds"]))):
        xa = wf_xgb["folds"][i]["auc"] if i < len(wf_xgb["folds"]) else None
        ua = wf_unpruned["folds"][i]["auc"] if i < len(wf_unpruned["folds"]) else None
        pa = wf_pruned["folds"][i]["auc"] if i < len(wf_pruned["folds"]) else None
        logger.info(
            "  Fold %-2d %12s %12s %12s",
            i,
            f"{xa:.4f}" if xa is not None else "N/A",
            f"{ua:.4f}" if ua is not None else "N/A",
            f"{pa:.4f}" if pa is not None else "N/A",
        )

    # ── Step 7: Compare pruned ensemble vs baseline SignalModel ──────────
    logger.info("")
    logger.info("=" * 70)
    logger.info("  PRUNED ENSEMBLE vs BASELINE XGBoost (full dataset)")
    logger.info("=" * 70)

    baseline = SignalModel(model_dir=str(MODEL_DIR))
    if baseline.load(DEFAULT_BASELINE):
        baseline_df = pd.DataFrame(0.0, index=features_full.index, columns=baseline.feature_names)
        shared = [c for c in baseline.feature_names if c in features_full.columns]
        baseline_df[shared] = features_full[shared]

        base_proba = baseline.predict_batch(baseline_df)
        pruned_proba = pruned_model.predict_batch(features_pruned)

        base_pred = (base_proba > 0.5).astype(int)
        pruned_pred = (pruned_proba > 0.5).astype(int)

        logger.info(
            "  %-22s %12s %12s %10s",
            "Metric", "Baseline", "Pruned Ens", "Delta",
        )
        logger.info("  " + "-" * 58)
        for name, bv, pv in [
            ("AUC", roc_auc_score(labels, base_proba), roc_auc_score(labels, pruned_proba)),
            ("Accuracy", accuracy_score(labels, base_pred), accuracy_score(labels, pruned_pred)),
            ("Precision", precision_score(labels, base_pred, zero_division=0), precision_score(labels, pruned_pred, zero_division=0)),
            ("Recall", recall_score(labels, base_pred, zero_division=0), recall_score(labels, pruned_pred, zero_division=0)),
        ]:
            d = pv - bv
            logger.info("  %-22s %12.4f %12.4f %10s", name, bv, pv, f"{'+' if d >= 0 else ''}{d:.4f}")

    # ── Step 8: Decision — save or not ───────────────────────────────────
    pruned_auc = agg_p.get("auc_mean") or 0
    unpruned_auc = agg_u.get("auc_mean") or 0
    xgb_auc = agg_x.get("auc_mean") or 0
    pruned_brier = agg_p.get("brier_score_mean", 1.0)
    unpruned_brier = agg_u.get("brier_score_mean", 1.0)

    # Pruned is better if it beats unpruned on AUC or matches AUC with lower Brier
    beats_unpruned = (
        pruned_auc > unpruned_auc + 0.001
        or (abs(pruned_auc - unpruned_auc) <= 0.001 and pruned_brier < unpruned_brier)
    )
    beats_xgb = pruned_auc > xgb_auc

    logger.info("")
    logger.info("=" * 70)
    logger.info("  DECISION")
    logger.info("=" * 70)
    logger.info("  WF AUC — XGBoost: %.4f  Unpruned: %.4f  Pruned: %.4f", xgb_auc, unpruned_auc, pruned_auc)
    logger.info("  WF Brier — Unpruned: %.4f  Pruned: %.4f", unpruned_brier, pruned_brier)
    logger.info("  Pruned beats unpruned: %s", beats_unpruned)
    logger.info("  Pruned beats XGBoost:  %s", beats_xgb)

    if beats_unpruned:
        filename = f"ensemble_model_pruned_{datetime.now().strftime('%Y%m%d')}.joblib"
        pruned_model.save(filename)
        logger.info("  SAVED pruned model to ml/models/%s", filename)
    else:
        logger.info("  NOT SAVED — pruned model did not improve on unpruned ensemble")

    elapsed = time.time() - t0
    logger.info("")
    logger.info("=" * 70)
    logger.info("  COMPLETE (%.1f seconds)", elapsed)
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
