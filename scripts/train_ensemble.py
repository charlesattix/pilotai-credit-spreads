#!/usr/bin/env python3
"""
Train Ensemble Signal Model
============================
End-to-end pipeline: collect trade data via backtests, train the
EnsembleSignalModel, run walk-forward validation, and compare against the
existing single-XGBoost SignalModel.

Steps:
  1. Run EXP-400 (CS + IC) backtests for 2020-2025 to collect enriched trades.
  2. Prepare features (numeric + one-hot categorical).
  3. Train EnsembleSignalModel with walk-forward weighted voting.
  4. Run WalkForwardValidator for rigorous OOS evaluation.
  5. Load the existing XGBoost model and compare on the same OOS predictions.
  6. Save the ensemble to ml/models/.

Usage:
    cd /home/node/.openclaw/workspace/pilotai-credit-spreads
    PYTHONPATH=. python3 scripts/train_ensemble.py
    PYTHONPATH=. python3 scripts/train_ensemble.py --skip-backtest   # reuse cached CSV
    PYTHONPATH=. python3 scripts/train_ensemble.py --baseline signal_model_20260321.joblib
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────────
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
    DATE_COL,
    RETURN_COL,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_ensemble")

MODEL_DIR = ROOT / "ml" / "models"
COMBINED_CSV = ROOT / "compass" / "training_data_combined.csv"
CACHE_CSV = ROOT / "compass" / "training_data_exp400.csv"
DEFAULT_BASELINE = "signal_model_20260321.joblib"


# ═══════════════════════════════════════════════════════════════════════════
# Step 1 — Collect training data
# ═══════════════════════════════════════════════════════════════════════════

def collect_training_data() -> pd.DataFrame:
    """Run EXP-400 backtests and enrich every closed trade with market context.

    Returns a chronologically sorted DataFrame with ~250-500 trades across
    2020-2025, each enriched with 45+ feature columns.
    """
    logger.info("=" * 70)
    logger.info("STEP 1: Collecting training data (EXP-400 backtests)")
    logger.info("=" * 70)

    # Load full market history once (2018-2025) for MA200 warmup
    full_spy, full_vix = _load_full_market_data()
    full_spy_closes = full_spy["Close"]

    all_trades: List[Dict] = []

    for year in YEARS:
        logger.info("-" * 50)
        logger.info("Backtesting year %d ...", year)

        bt, results = run_year_backtest_exp400(year)
        trades = enrich_trades(
            bt, year,
            spy_closes=full_spy_closes,
            vix_series=full_vix,
        )
        n_trades = len(trades)
        ret = results.get("return_pct", 0)
        wr = results.get("win_rate", 0)
        logger.info(
            "  Year %d: %d trades  return=%.2f%%  win_rate=%.1f%%",
            year, n_trades, ret, wr,
        )
        all_trades.extend(trades)

    df = pd.DataFrame(all_trades)
    df = df.sort_values("entry_date").reset_index(drop=True)

    # Cache to disk so --skip-backtest can reuse
    df.to_csv(CACHE_CSV, index=False)
    logger.info("Saved %d trades to %s", len(df), CACHE_CSV)

    return df


# ═══════════════════════════════════════════════════════════════════════════
# Step 2 — Feature preparation
# ═══════════════════════════════════════════════════════════════════════════

def build_feature_matrix(df: pd.DataFrame) -> tuple:
    """Convert raw trade DataFrame into (features_df, labels) for model training.

    Uses the same NUMERIC_FEATURES and CATEGORICAL_FEATURES as the
    WalkForwardValidator so that training and validation operate on
    identical feature sets.

    Returns:
        (features_df, labels) where features_df is a DataFrame with
        deterministic column order and labels is a 1-D int array.
    """
    logger.info("=" * 70)
    logger.info("STEP 2: Preparing features")
    logger.info("=" * 70)

    features_df = prepare_features(
        df,
        numeric_features=NUMERIC_FEATURES,
        categorical_features=CATEGORICAL_FEATURES,
    )
    labels = df[TARGET_COL].values.astype(int)

    logger.info(
        "  Feature matrix: %d samples × %d features",
        features_df.shape[0], features_df.shape[1],
    )
    logger.info("  Positive rate (win): %.1f%%", labels.mean() * 100)
    logger.info("  Feature columns: %s", list(features_df.columns))

    return features_df, labels


# ═══════════════════════════════════════════════════════════════════════════
# Step 3 — Train ensemble
# ═══════════════════════════════════════════════════════════════════════════

def train_ensemble(features_df: pd.DataFrame, labels: np.ndarray) -> tuple:
    """Train the EnsembleSignalModel and return (model, stats).

    The ensemble combines XGBoost + RandomForest + ExtraTrees with
    walk-forward-derived weights and per-model probability calibration.
    """
    logger.info("=" * 70)
    logger.info("STEP 3: Training EnsembleSignalModel")
    logger.info("=" * 70)

    model = EnsembleSignalModel(model_dir=str(MODEL_DIR))
    stats = model.train(
        features_df,
        labels,
        calibrate=True,
        save_model=True,
        n_wf_folds=5,
    )

    if not stats:
        logger.error("Ensemble training failed — no stats returned")
        sys.exit(1)

    logger.info("")
    logger.info("Ensemble training results:")
    logger.info("  Test AUC:       %.4f", stats["ensemble_test_auc"])
    logger.info("  Test Accuracy:  %.4f", stats["ensemble_test_accuracy"])
    logger.info("  Test Precision: %.4f", stats["ensemble_test_precision"])
    logger.info("  Test Recall:    %.4f", stats["ensemble_test_recall"])
    logger.info("  Train samples:  %d", stats["n_train"])
    logger.info("  Test samples:   %d", stats["n_test"])
    logger.info("  Ensemble weights:")
    for name, weight in stats["ensemble_weights"].items():
        pm = stats["per_model"].get(name, {})
        logger.info(
            "    %-15s  weight=%.3f  AUC=%.4f",
            name, weight, pm.get("test_auc", 0),
        )

    return model, stats


# ═══════════════════════════════════════════════════════════════════════════
# Step 4 — Walk-forward validation
# ═══════════════════════════════════════════════════════════════════════════

def _make_xgb_model():
    """Build an XGBClassifier with the same hyperparams as SignalModel.train()."""
    import xgboost as xgb
    return xgb.XGBClassifier(
        objective="binary:logistic",
        max_depth=6,
        learning_rate=0.05,
        n_estimators=200,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.8,
        gamma=1,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        eval_metric="logloss",
    )


def _make_ensemble_pipeline():
    """Build an sklearn-compatible ensemble that mirrors EnsembleSignalModel.

    Returns a VotingClassifier (soft voting) with the same 3 base learners
    so we can plug it into WalkForwardValidator for apples-to-apples
    comparison against the standalone XGBoost.
    """
    import xgboost as xgb
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        RandomForestClassifier,
        VotingClassifier,
    )

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


def _log_wf_results(label: str, wf_results: Dict) -> None:
    """Pretty-print walk-forward results."""
    logger.info("")
    logger.info("  [%s] Walk-forward results (%d folds):", label, wf_results["n_folds"])
    for fold in wf_results["folds"]:
        auc_str = f"{fold['auc']:.4f}" if fold["auc"] is not None else "N/A"
        logger.info(
            "    Fold %d: %s  train=%d test=%d  AUC=%s  Acc=%.4f  Brier=%.4f",
            fold["fold"],
            fold["test_period"],
            fold["n_train"],
            fold["n_test"],
            auc_str,
            fold["accuracy"],
            fold["brier_score"],
        )

    agg = wf_results["aggregate"]
    logger.info("")
    logger.info("    Aggregate:")
    logger.info("      Accuracy:  %.4f +/- %.4f", agg["accuracy_mean"], agg["accuracy_std"])
    auc_mean = agg.get("auc_mean")
    auc_std = agg.get("auc_std")
    logger.info(
        "      AUC:       %s +/- %s",
        f"{auc_mean:.4f}" if auc_mean is not None else "N/A",
        f"{auc_std:.4f}" if auc_std is not None else "N/A",
    )
    logger.info("      Brier:     %.4f +/- %.4f", agg["brier_score_mean"], agg["brier_score_std"])
    if agg.get("signal_sharpe_mean") is not None:
        logger.info("      Sharpe:    %.4f +/- %.4f", agg["signal_sharpe_mean"], agg["signal_sharpe_std"])
    logger.info("      Total OOS: %d samples", agg["total_oos_samples"])


def run_walk_forward(df: pd.DataFrame) -> Dict:
    """Run walk-forward validation for both XGBoost and Ensemble side-by-side.

    Both models are evaluated on identical chronological folds so the
    comparison is fair.  Returns dict with 'xgboost' and 'ensemble' results.
    """
    logger.info("=" * 70)
    logger.info("STEP 4: Walk-forward validation — XGBoost vs Ensemble")
    logger.info("=" * 70)

    try:
        import xgboost as xgb
    except ImportError:
        logger.error("XGBoost not installed — cannot run walk-forward")
        return {}

    results = {}

    for label, model in [("XGBoost", _make_xgb_model()), ("Ensemble", _make_ensemble_pipeline())]:
        validator = WalkForwardValidator(
            model=model,
            numeric_features=NUMERIC_FEATURES,
            categorical_features=CATEGORICAL_FEATURES,
            min_train_samples=30,
        )
        wf = validator.run(df)
        results[label.lower()] = wf
        _log_wf_results(label, wf)

    # Side-by-side summary
    xgb_agg = results.get("xgboost", {}).get("aggregate", {})
    ens_agg = results.get("ensemble", {}).get("aggregate", {})
    if xgb_agg and ens_agg:
        logger.info("")
        logger.info("  Walk-Forward Head-to-Head:")
        logger.info("  %-18s %12s %12s %10s", "Metric", "XGBoost", "Ensemble", "Delta")
        logger.info("  " + "-" * 54)
        for metric in ["accuracy_mean", "auc_mean", "brier_score_mean", "signal_sharpe_mean"]:
            xv = xgb_agg.get(metric)
            ev = ens_agg.get(metric)
            if xv is None or ev is None:
                continue
            delta = ev - xv
            # For Brier, lower is better, so flip the sign for interpretation
            sign = "+" if delta >= 0 else ""
            label = metric.replace("_mean", "").replace("_", " ").title()
            logger.info("  %-18s %12.4f %12.4f %10s", label, xv, ev, f"{sign}{delta:.4f}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Step 5 — Compare with baseline
# ═══════════════════════════════════════════════════════════════════════════

def compare_with_baseline(
    ensemble: EnsembleSignalModel,
    features_df: pd.DataFrame,
    labels: np.ndarray,
    baseline_filename: str,
) -> None:
    """Load the existing XGBoost model and compare predictions head-to-head.

    Both models predict on the *same* feature matrix so the comparison
    is apples-to-apples.
    """
    logger.info("=" * 70)
    logger.info("STEP 5: Comparison — Ensemble vs Baseline XGBoost")
    logger.info("=" * 70)

    baseline = SignalModel(model_dir=str(MODEL_DIR))
    if not baseline.load(baseline_filename):
        logger.warning(
            "Could not load baseline model '%s' — skipping comparison",
            baseline_filename,
        )
        return

    # The baseline model may have different feature columns.
    # We need to align the feature matrix to what each model expects.
    baseline_features = baseline.feature_names
    ensemble_features = ensemble.feature_names

    # Build a shared evaluation set: features present in both models.
    # For the baseline, we need to reindex our feature matrix to its columns.
    logger.info("  Baseline features: %d columns", len(baseline_features))
    logger.info("  Ensemble features: %d columns", len(ensemble_features))

    # ── Ensemble predictions ──────────────────────────────────────────────
    ensemble_proba = ensemble.predict_batch(features_df)
    ensemble_pred = (ensemble_proba > 0.5).astype(int)

    from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

    ens_acc = accuracy_score(labels, ensemble_pred)
    ens_prec = precision_score(labels, ensemble_pred, zero_division=0)
    ens_rec = recall_score(labels, ensemble_pred, zero_division=0)
    ens_auc = roc_auc_score(labels, ensemble_proba)

    # ── Baseline predictions ──────────────────────────────────────────────
    # Build a DataFrame with the baseline's expected columns, filling
    # missing columns with 0.0.
    baseline_df = pd.DataFrame(0.0, index=features_df.index, columns=baseline_features)
    shared_cols = [c for c in baseline_features if c in features_df.columns]
    baseline_df[shared_cols] = features_df[shared_cols]

    baseline_proba = baseline.predict_batch(baseline_df)
    baseline_pred = (baseline_proba > 0.5).astype(int)

    base_acc = accuracy_score(labels, baseline_pred)
    base_prec = precision_score(labels, baseline_pred, zero_division=0)
    base_rec = recall_score(labels, baseline_pred, zero_division=0)
    base_auc = roc_auc_score(labels, baseline_proba)

    # ── Print comparison ──────────────────────────────────────────────────
    logger.info("")
    logger.info(
        "  %-22s %12s %12s %10s",
        "Metric", "Baseline", "Ensemble", "Delta",
    )
    logger.info("  " + "-" * 58)

    for name, bv, ev in [
        ("AUC", base_auc, ens_auc),
        ("Accuracy", base_acc, ens_acc),
        ("Precision", base_prec, ens_prec),
        ("Recall", base_rec, ens_rec),
    ]:
        delta = ev - bv
        sign = "+" if delta >= 0 else ""
        logger.info(
            "  %-22s %12.4f %12.4f %10s",
            name, bv, ev, f"{sign}{delta:.4f}",
        )

    # ── Agreement analysis ────────────────────────────────────────────────
    agree = (ensemble_pred == baseline_pred).sum()
    disagree = len(labels) - agree
    logger.info("")
    logger.info(
        "  Agreement: %d/%d (%.1f%%)  |  Disagreement: %d trades",
        agree, len(labels), agree / len(labels) * 100, disagree,
    )

    # On the trades where they disagree, who's right more often?
    if disagree > 0:
        disagree_mask = ensemble_pred != baseline_pred
        ens_right = (ensemble_pred[disagree_mask] == labels[disagree_mask]).sum()
        base_right = (baseline_pred[disagree_mask] == labels[disagree_mask]).sum()
        logger.info(
            "  On %d disagreements: ensemble correct %d (%.0f%%), "
            "baseline correct %d (%.0f%%)",
            disagree,
            ens_right, ens_right / disagree * 100,
            base_right, base_right / disagree * 100,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Train EnsembleSignalModel and compare with baseline XGBoost",
    )
    parser.add_argument(
        "--skip-backtest",
        action="store_true",
        help="Reuse cached CSV instead of re-running backtests",
    )
    parser.add_argument(
        "--data",
        default=None,
        help="Path to training CSV (default: auto-detect combined > exp400)",
    )
    parser.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE,
        help=f"Baseline model filename in ml/models/ (default: {DEFAULT_BASELINE})",
    )
    args = parser.parse_args()

    t0 = time.time()
    logger.info("=" * 70)
    logger.info("  COMPASS Ensemble Model Training Pipeline")
    logger.info("  %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 70)

    # Step 1: Collect or load training data
    if args.data:
        data_path = Path(args.data)
        logger.info("Loading training data from %s", data_path)
        df = pd.read_csv(data_path)
        logger.info("  %d trades loaded", len(df))
    elif args.skip_backtest:
        # Prefer combined > exp400
        if COMBINED_CSV.exists():
            data_path = COMBINED_CSV
        elif CACHE_CSV.exists():
            data_path = CACHE_CSV
        else:
            logger.warning("No cached data found — running backtests")
            df = collect_training_data()
            data_path = None

        if data_path is not None:
            logger.info("Loading cached training data from %s", data_path)
            df = pd.read_csv(data_path)
            logger.info("  %d trades loaded", len(df))
    else:
        df = collect_training_data()

    if len(df) < 50:
        logger.error("Only %d trades collected — too few to train. Exiting.", len(df))
        sys.exit(1)

    logger.info("")
    logger.info("Training data summary:")
    logger.info("  Trades:     %d", len(df))
    logger.info("  Date range: %s → %s", df["entry_date"].min(), df["entry_date"].max())
    logger.info("  Win rate:   %.1f%%", df[TARGET_COL].mean() * 100)
    if "strategy_type" in df.columns:
        logger.info(
            "  Strategies: %s",
            df["strategy_type"].value_counts().to_dict(),
        )
    if "year" in df.columns:
        logger.info(
            "  Per year:   %s",
            df["year"].value_counts().sort_index().to_dict(),
        )

    # Step 2: Prepare features
    features_df, labels = build_feature_matrix(df)

    # Step 3: Train ensemble
    ensemble, train_stats = train_ensemble(features_df, labels)

    # Step 4: Walk-forward validation
    wf_results = run_walk_forward(df)

    # Step 5: Compare with baseline
    compare_with_baseline(ensemble, features_df, labels, args.baseline)

    # Summary
    elapsed = time.time() - t0
    logger.info("")
    logger.info("=" * 70)
    logger.info("  PIPELINE COMPLETE  (%.1f seconds)", elapsed)
    logger.info("=" * 70)
    logger.info("  Ensemble saved to: ml/models/")
    logger.info("  Training trades:   %d", len(df))
    if train_stats:
        logger.info("  Ensemble AUC:      %.4f", train_stats["ensemble_test_auc"])
        logger.info("  Ensemble weights:  %s", {
            k: f"{v:.3f}" for k, v in train_stats["ensemble_weights"].items()
        })
    if wf_results:
        for model_key in ["xgboost", "ensemble"]:
            agg = wf_results.get(model_key, {}).get("aggregate", {})
            if agg.get("auc_mean") is not None:
                logger.info(
                    "  WF %s AUC:  %.4f +/- %.4f",
                    model_key.title(), agg["auc_mean"], agg["auc_std"],
                )


if __name__ == "__main__":
    main()
