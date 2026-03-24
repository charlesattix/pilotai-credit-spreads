#!/usr/bin/env python3
"""
Hyperparameter Tuning for Ensemble Signal Model
=================================================
Uses Optuna to tune XGBoost, RandomForest, ExtraTrees, and LightGBM
hyperparameters plus ensemble weights.  The objective is mean OOS AUC
from walk-forward validation (expanding-window, chronological splits).

Usage:
    cd /home/node/.openclaw/workspace/pilotai-credit-spreads
    PYTHONPATH=. python3 scripts/tune_ensemble.py                 # 50 trials
    PYTHONPATH=. python3 scripts/tune_ensemble.py --n-trials 100  # more trials
    PYTHONPATH=. python3 scripts/tune_ensemble.py --n-trials 20   # quick test
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from compass.walk_forward import (
    WalkForwardValidator,
    prepare_features,
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    TARGET_COL,
)
from shared.indicators import sanitize_features

# Reuse feature engineering from the expanded training script
from scripts.train_ensemble_expanded import (
    engineer_expanded_features,
    EXPANDED_NUMERIC,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# Silence noisy loggers during optimization
for name in ["compass", "shared", "lightgbm", "xgboost"]:
    logging.getLogger(name).setLevel(logging.WARNING)

logger = logging.getLogger("tune_ensemble")

COMBINED_CSV = ROOT / "compass" / "training_data_combined.csv"
RESULTS_DIR = ROOT / "ml" / "tuning"


# ═══════════════════════════════════════════════════════════════════════════
# Objective
# ═══════════════════════════════════════════════════════════════════════════

def build_ensemble(trial, feature_cols):
    """Build a VotingClassifier with Optuna-sampled hyperparameters."""
    import lightgbm as lgb
    import xgboost as xgb
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        RandomForestClassifier,
        VotingClassifier,
    )

    # ── XGBoost ───────────────────────────────────────────────────────
    xgb_params = {
        "objective": "binary:logistic",
        "max_depth": trial.suggest_int("xgb_max_depth", 3, 10),
        "learning_rate": trial.suggest_float("xgb_learning_rate", 0.01, 0.3, log=True),
        "n_estimators": trial.suggest_int("xgb_n_estimators", 50, 500, step=50),
        "min_child_weight": trial.suggest_int("xgb_min_child_weight", 1, 10),
        "gamma": trial.suggest_float("xgb_gamma", 0.0, 5.0),
        "subsample": trial.suggest_float("xgb_subsample", 0.5, 1.0),
        "colsample_bytree": trial.suggest_float("xgb_colsample_bytree", 0.5, 1.0),
        "reg_alpha": trial.suggest_float("xgb_reg_alpha", 1e-3, 10.0, log=True),
        "reg_lambda": trial.suggest_float("xgb_reg_lambda", 1e-3, 10.0, log=True),
        "random_state": 42,
        "eval_metric": "logloss",
    }

    # ── LightGBM ─────────────────────────────────────────────────────
    lgb_params = {
        "objective": "binary",
        "num_leaves": trial.suggest_int("lgb_num_leaves", 8, 128),
        "max_depth": trial.suggest_int("lgb_max_depth", 3, 10),
        "learning_rate": trial.suggest_float("lgb_learning_rate", 0.01, 0.3, log=True),
        "n_estimators": trial.suggest_int("lgb_n_estimators", 50, 500, step=50),
        "min_child_samples": trial.suggest_int("lgb_min_child_samples", 5, 50),
        "subsample": trial.suggest_float("lgb_subsample", 0.5, 1.0),
        "colsample_bytree": trial.suggest_float("lgb_colsample_bytree", 0.5, 1.0),
        "reg_alpha": trial.suggest_float("lgb_reg_alpha", 1e-3, 10.0, log=True),
        "reg_lambda": trial.suggest_float("lgb_reg_lambda", 1e-3, 10.0, log=True),
        "random_state": 42,
        "verbosity": -1,
        "n_jobs": -1,
    }

    # ── RandomForest ──────────────────────────────────────────────────
    rf_params = {
        "n_estimators": trial.suggest_int("rf_n_estimators", 50, 500, step=50),
        "max_depth": trial.suggest_int("rf_max_depth", 3, 15),
        "min_samples_leaf": trial.suggest_int("rf_min_samples_leaf", 2, 20),
        "max_features": trial.suggest_categorical("rf_max_features", ["sqrt", "log2"]),
        "random_state": 42,
        "n_jobs": -1,
    }

    # ── ExtraTrees ────────────────────────────────────────────────────
    et_params = {
        "n_estimators": trial.suggest_int("et_n_estimators", 50, 500, step=50),
        "max_depth": trial.suggest_int("et_max_depth", 3, 15),
        "min_samples_leaf": trial.suggest_int("et_min_samples_leaf", 2, 20),
        "max_features": trial.suggest_categorical("et_max_features", ["sqrt", "log2"]),
        "random_state": 42,
        "n_jobs": -1,
    }

    # ── Ensemble weights ──────────────────────────────────────────────
    # Sample raw weights, then normalize to sum to 1
    w_xgb = trial.suggest_float("w_xgb", 0.05, 1.0)
    w_lgb = trial.suggest_float("w_lgb", 0.05, 1.0)
    w_rf = trial.suggest_float("w_rf", 0.05, 1.0)
    w_et = trial.suggest_float("w_et", 0.05, 1.0)
    w_total = w_xgb + w_lgb + w_rf + w_et
    weights = [w_xgb / w_total, w_lgb / w_total, w_rf / w_total, w_et / w_total]

    ensemble = VotingClassifier(
        estimators=[
            ("xgboost", xgb.XGBClassifier(**xgb_params)),
            ("lightgbm", lgb.LGBMClassifier(**lgb_params)),
            ("random_forest", RandomForestClassifier(**rf_params)),
            ("extra_trees", ExtraTreesClassifier(**et_params)),
        ],
        voting="soft",
        weights=weights,
    )

    return ensemble


def objective(trial, df_expanded, feature_cols):
    """Optuna objective: mean walk-forward OOS AUC."""
    ensemble = build_ensemble(trial, feature_cols)

    validator = WalkForwardValidator(
        model=ensemble,
        numeric_features=EXPANDED_NUMERIC,
        categorical_features=CATEGORICAL_FEATURES,
        min_train_samples=30,
    )

    try:
        results = validator.run(df_expanded)
    except Exception as e:
        logger.warning("Trial %d failed: %s", trial.number, e)
        return 0.5  # worst-case AUC

    agg = results["aggregate"]
    auc_mean = agg.get("auc_mean")
    if auc_mean is None:
        return 0.5

    # Store extra metrics for analysis
    trial.set_user_attr("accuracy_mean", agg["accuracy_mean"])
    trial.set_user_attr("brier_score_mean", agg["brier_score_mean"])
    if agg.get("signal_sharpe_mean") is not None:
        trial.set_user_attr("signal_sharpe_mean", agg["signal_sharpe_mean"])
    trial.set_user_attr("n_folds", results["n_folds"])

    return auc_mean


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Tune ensemble hyperparameters with Optuna")
    parser.add_argument("--n-trials", type=int, default=50, help="Number of Optuna trials")
    args = parser.parse_args()

    t0 = time.time()
    logger.info("=" * 70)
    logger.info("  Ensemble Hyperparameter Tuning (Optuna)")
    logger.info("  %s  |  %d trials", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), args.n_trials)
    logger.info("=" * 70)

    # ── Load and prepare data ─────────────────────────────────────────
    if not COMBINED_CSV.exists():
        logger.error("Training data not found at %s", COMBINED_CSV)
        sys.exit(1)

    df = pd.read_csv(COMBINED_CSV)
    df_expanded = engineer_expanded_features(df)
    logger.info("Data: %d trades, %.1f%% win rate, expanded to %d numeric features",
                len(df), df[TARGET_COL].mean() * 100, len(EXPANDED_NUMERIC))

    feature_cols = list(prepare_features(
        df_expanded,
        numeric_features=EXPANDED_NUMERIC,
        categorical_features=CATEGORICAL_FEATURES,
    ).columns)

    # ── Run Optuna ────────────────────────────────────────────────────
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    study = optuna.create_study(
        direction="maximize",
        study_name="ensemble_tune",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    logger.info("Starting %d trials (objective = walk-forward mean AUC)...", args.n_trials)
    logger.info("")

    def _callback(study, trial):
        if trial.value is not None and trial.value > 0.5:
            extra = ""
            acc = trial.user_attrs.get("accuracy_mean")
            brier = trial.user_attrs.get("brier_score_mean")
            if acc is not None:
                extra = f"  acc={acc:.4f}  brier={brier:.4f}"
            logger.info(
                "  Trial %3d: AUC=%.4f%s%s",
                trial.number, trial.value, extra,
                "  ** BEST **" if trial.value >= study.best_value else "",
            )

    study.optimize(
        lambda trial: objective(trial, df_expanded, feature_cols),
        n_trials=args.n_trials,
        callbacks=[_callback],
        show_progress_bar=False,
    )

    # ── Results ───────────────────────────────────────────────────────
    best = study.best_trial
    logger.info("")
    logger.info("=" * 70)
    logger.info("  TUNING COMPLETE  (%d trials, %.1f seconds)", args.n_trials, time.time() - t0)
    logger.info("=" * 70)
    logger.info("  Best trial: #%d", best.number)
    logger.info("  Best AUC:   %.4f", best.value)
    if best.user_attrs.get("accuracy_mean"):
        logger.info("  Accuracy:   %.4f", best.user_attrs["accuracy_mean"])
    if best.user_attrs.get("brier_score_mean"):
        logger.info("  Brier:      %.4f", best.user_attrs["brier_score_mean"])
    if best.user_attrs.get("signal_sharpe_mean"):
        logger.info("  Sharpe:     %.4f", best.user_attrs["signal_sharpe_mean"])

    # ── Normalize and display weights ─────────────────────────────────
    w_raw = {
        "xgboost": best.params["w_xgb"],
        "lightgbm": best.params["w_lgb"],
        "random_forest": best.params["w_rf"],
        "extra_trees": best.params["w_et"],
    }
    w_total = sum(w_raw.values())
    weights_norm = {k: round(v / w_total, 4) for k, v in w_raw.items()}
    logger.info("  Weights:    %s", weights_norm)

    # ── Per-model params ──────────────────────────────────────────────
    logger.info("")
    logger.info("  Best hyperparameters:")
    for prefix, label in [("xgb_", "XGBoost"), ("lgb_", "LightGBM"),
                           ("rf_", "RandomForest"), ("et_", "ExtraTrees")]:
        model_params = {k: v for k, v in best.params.items() if k.startswith(prefix)}
        logger.info("    %s:", label)
        for k, v in sorted(model_params.items()):
            logger.info("      %-28s = %s", k, v)

    # ── Save results ──────────────────────────────────────────────────
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Best params JSON
    results = {
        "timestamp": ts,
        "n_trials": args.n_trials,
        "best_trial": best.number,
        "best_auc": round(best.value, 6),
        "best_accuracy": best.user_attrs.get("accuracy_mean"),
        "best_brier": best.user_attrs.get("brier_score_mean"),
        "best_sharpe": best.user_attrs.get("signal_sharpe_mean"),
        "weights": weights_norm,
        "params": best.params,
    }

    params_path = RESULTS_DIR / f"best_params_{ts}.json"
    with open(params_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("")
    logger.info("  Saved best params: %s", params_path)

    # Full trial history
    history = []
    for t in study.trials:
        row = {
            "number": t.number,
            "value": t.value,
            "state": t.state.name,
        }
        row.update(t.params)
        row.update(t.user_attrs)
        history.append(row)

    history_path = RESULTS_DIR / f"trial_history_{ts}.json"
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2, default=str)
    logger.info("  Saved trial history: %s", history_path)

    # ── Top 5 trials ──────────────────────────────────────────────────
    logger.info("")
    logger.info("  Top 5 trials:")
    sorted_trials = sorted(study.trials, key=lambda t: t.value or 0, reverse=True)
    for i, t in enumerate(sorted_trials[:5]):
        acc = t.user_attrs.get("accuracy_mean", 0)
        brier = t.user_attrs.get("brier_score_mean", 0)
        logger.info(
            "    #%-3d  AUC=%.4f  Acc=%.4f  Brier=%.4f",
            t.number, t.value or 0, acc or 0, brier or 0,
        )

    # ── Compare best vs default ───────────────────────────────────────
    logger.info("")
    logger.info("  Baseline comparison (default params from train_ensemble_expanded.py):")
    logger.info("    Default Ens-Expanded WF AUC: 0.8377")
    logger.info("    Tuned   Ens-Expanded WF AUC: %.4f  (%+.4f)",
                best.value, best.value - 0.8377)


if __name__ == "__main__":
    main()
