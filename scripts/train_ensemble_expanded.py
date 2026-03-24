#!/usr/bin/env python3
"""
Train Ensemble with Expanded Feature Set
==========================================
Adds features inspired by compass/features.py FeatureEngine that aren't in
the base training CSV:

  NEW FEATURES (derived from existing columns — no live data needed):
    vol_premium          — implied minus realized vol (IV-RV spread)
    vol_premium_pct      — vol premium as % of realized vol
    credit_to_width_ratio— net_credit / spread_width (edge density)
    event_risk_score     — proximity to FOMC/CPI dates (0.2/0.5/0.8)
    days_to_fomc         — calendar days to next FOMC meeting
    days_to_cpi          — calendar days to next CPI release
    rsi_oversold         — RSI < 30 flag
    rsi_overbought       — RSI > 70 flag
    iv_rank_high         — IV rank > 70 flag
    iv_rank_low          — IV rank < 30 flag
    month                — entry month (1-12)
    is_opex_week         — 3rd Friday week flag
    is_month_end         — day >= 25 flag
    vix_rv_ratio         — VIX / realized_vol_20d (term structure proxy)

Pipeline:
  1. Load combined training data
  2. Engineer expanded features from existing columns
  3. Train ensemble on expanded features
  4. Walk-forward validate both XGBoost and Ensemble (expanded)
  5. Compare expanded ensemble vs baseline (original features)

Usage:
    cd /home/node/.openclaw/workspace/pilotai-credit-spreads
    PYTHONPATH=. python3 scripts/train_ensemble_expanded.py
"""

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from compass.ensemble_signal_model import EnsembleSignalModel
from compass.signal_model import SignalModel
from compass.walk_forward import (
    WalkForwardValidator,
    prepare_features,
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    TARGET_COL,
)
from shared.constants import CPI_RELEASE_DAYS, FOMC_DATES
from shared.indicators import sanitize_features

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_expanded")

MODEL_DIR = ROOT / "ml" / "models"
COMBINED_CSV = ROOT / "compass" / "training_data_combined.csv"
BASELINE_MODEL = "signal_model_20260321.joblib"

# New numeric features to add on top of the base set
EXPANDED_NUMERIC = NUMERIC_FEATURES + [
    "vol_premium",
    "vol_premium_pct",
    "credit_to_width_ratio",
    "event_risk_score",
    "days_to_fomc",
    "days_to_cpi",
    "rsi_oversold",
    "rsi_overbought",
    "iv_rank_high",
    "iv_rank_low",
    "month",
    "is_opex_week",
    "is_month_end",
    "vix_rv_ratio",
]


# ═══════════════════════════════════════════════════════════════════════════
# Feature engineering
# ═══════════════════════════════════════════════════════════════════════════

def _days_to_next_fomc(entry_date: datetime) -> int:
    """Calendar days from entry_date to the next FOMC meeting."""
    if entry_date.tzinfo is None:
        entry_date = entry_date.replace(tzinfo=timezone.utc)
    upcoming = [d for d in FOMC_DATES if d > entry_date]
    if not upcoming:
        return 999
    return (min(upcoming) - entry_date).days


def _days_to_next_cpi(entry_date: datetime) -> int:
    """Calendar days from entry_date to next CPI release (~12th-14th of month)."""
    import calendar as cal
    cpi_day = CPI_RELEASE_DAYS[len(CPI_RELEASE_DAYS) // 2]  # median day
    day = entry_date.day
    if day < cpi_day + 1:
        return cpi_day - day
    days_in_month = cal.monthrange(entry_date.year, entry_date.month)[1]
    return days_in_month - day + cpi_day


def _event_risk_score(days_to_fomc: int, days_to_cpi: int) -> float:
    """Score per FeatureEngine: 0.8 if < 7d, 0.5 if < 14d, else 0.2."""
    min_days = min(days_to_fomc, days_to_cpi)
    if min_days < 7:
        return 0.8
    elif min_days < 14:
        return 0.5
    return 0.2


def engineer_expanded_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add new columns to the training DataFrame.

    All features are derived from existing columns — no live data provider
    needed.  This mirrors the features that FeatureEngine would produce at
    trade time, computed retroactively from the training CSV.
    """
    df = df.copy()
    dates = pd.to_datetime(df["entry_date"])

    # ── Volatility premium ────────────────────────────────────────────
    # vol_premium = implied vol proxy - realized vol
    # We use (iv_rank / 100) * vix as an IV proxy since we don't have
    # the actual per-ticker IV in the CSV.  Realized vol is realized_vol_20d.
    iv_proxy = df["vix"].fillna(20.0)
    rv20 = df["realized_vol_20d"].fillna(15.0)
    df["vol_premium"] = iv_proxy - rv20
    df["vol_premium_pct"] = np.where(rv20 > 0, (iv_proxy - rv20) / rv20 * 100, 0.0)

    # ── Credit to width ratio ─────────────────────────────────────────
    nc = df["net_credit"].fillna(0)
    sw = df["spread_width"].fillna(0)
    df["credit_to_width_ratio"] = np.where(sw > 0, nc / sw, 0.0)

    # ── Event risk features ───────────────────────────────────────────
    fomc_days = dates.apply(lambda d: _days_to_next_fomc(d.to_pydatetime()))
    cpi_days = dates.apply(lambda d: _days_to_next_cpi(d.to_pydatetime()))
    df["days_to_fomc"] = fomc_days
    df["days_to_cpi"] = cpi_days
    df["event_risk_score"] = [
        _event_risk_score(f, c) for f, c in zip(fomc_days, cpi_days)
    ]

    # ── RSI flags ─────────────────────────────────────────────────────
    rsi = df["rsi_14"].fillna(50.0)
    df["rsi_oversold"] = (rsi < 30).astype(float)
    df["rsi_overbought"] = (rsi > 70).astype(float)

    # ── IV rank flags ─────────────────────────────────────────────────
    ivr = df["iv_rank"].fillna(50.0)
    df["iv_rank_high"] = (ivr > 70).astype(float)
    df["iv_rank_low"] = (ivr < 30).astype(float)

    # ── Seasonal features ─────────────────────────────────────────────
    df["month"] = dates.dt.month
    df["is_opex_week"] = ((dates.dt.day >= 15) & (dates.dt.day <= 21)).astype(float)
    df["is_month_end"] = (dates.dt.day >= 25).astype(float)

    # ── VIX / realized vol ratio ──────────────────────────────────────
    df["vix_rv_ratio"] = np.where(rv20 > 0, iv_proxy / rv20, 1.0)

    n_new = len(EXPANDED_NUMERIC) - len(NUMERIC_FEATURES)
    logger.info("Engineered %d new features (%d total numeric)", n_new, len(EXPANDED_NUMERIC))

    return df


# ═══════════════════════════════════════════════════════════════════════════
# Walk-forward helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_xgb():
    import xgboost as xgb
    return xgb.XGBClassifier(
        objective="binary:logistic", max_depth=6, learning_rate=0.05,
        n_estimators=200, min_child_weight=5, subsample=0.8,
        colsample_bytree=0.8, gamma=1, reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, eval_metric="logloss",
    )


def _make_ensemble():
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        RandomForestClassifier,
        VotingClassifier,
    )
    import xgboost as xgb
    return VotingClassifier(
        estimators=[
            ("xgboost", _make_xgb()),
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


def run_wf(label: str, model, df: pd.DataFrame, numeric_feats, cat_feats) -> Dict:
    """Run walk-forward and log results."""
    validator = WalkForwardValidator(
        model=model,
        numeric_features=numeric_feats,
        categorical_features=cat_feats,
        min_train_samples=30,
    )
    res = validator.run(df)
    agg = res["aggregate"]

    logger.info("")
    logger.info("  [%s] %d folds, %d OOS samples", label, res["n_folds"], agg["total_oos_samples"])
    for fold in res["folds"]:
        auc_s = f"{fold['auc']:.4f}" if fold["auc"] is not None else "N/A"
        logger.info(
            "    Fold %d: %s  train=%d test=%d  AUC=%s  Acc=%.4f  Brier=%.4f",
            fold["fold"], fold["test_period"],
            fold["n_train"], fold["n_test"],
            auc_s, fold["accuracy"], fold["brier_score"],
        )
    logger.info("    Aggregate: AUC=%.4f+/-%.4f  Acc=%.4f+/-%.4f  Brier=%.4f+/-%.4f",
                agg.get("auc_mean", 0) or 0, agg.get("auc_std", 0) or 0,
                agg["accuracy_mean"], agg["accuracy_std"],
                agg["brier_score_mean"], agg["brier_score_std"])
    if agg.get("signal_sharpe_mean") is not None:
        logger.info("    Signal Sharpe: %.4f+/-%.4f", agg["signal_sharpe_mean"], agg["signal_sharpe_std"])

    return res


# ═══════════════════════════════════════════════════════════════════════════
# Saved-model comparison
# ═══════════════════════════════════════════════════════════════════════════

def compare_with_saved_baseline(
    ensemble: EnsembleSignalModel,
    features_df: pd.DataFrame,
    labels: np.ndarray,
) -> None:
    """Compare trained ensemble vs saved XGBoost on full dataset."""
    from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

    baseline = SignalModel(model_dir=str(MODEL_DIR))
    if not baseline.load(BASELINE_MODEL):
        logger.warning("No baseline model %s — skipping saved-model comparison", BASELINE_MODEL)
        return

    logger.info("=" * 70)
    logger.info("STEP 5: Expanded Ensemble vs Saved Baseline (%s)", BASELINE_MODEL)
    logger.info("=" * 70)

    # Ensemble predictions (already has expanded features)
    ens_proba = ensemble.predict_batch(features_df)
    ens_pred = (ens_proba > 0.5).astype(int)

    # Baseline predictions — align to its feature columns
    bl_cols = baseline.feature_names
    bl_df = pd.DataFrame(0.0, index=features_df.index, columns=bl_cols)
    shared = [c for c in bl_cols if c in features_df.columns]
    bl_df[shared] = features_df[shared]
    bl_proba = baseline.predict_batch(bl_df)
    bl_pred = (bl_proba > 0.5).astype(int)

    rows = []
    for name, bv, ev in [
        ("AUC", roc_auc_score(labels, bl_proba), roc_auc_score(labels, ens_proba)),
        ("Accuracy", accuracy_score(labels, bl_pred), accuracy_score(labels, ens_pred)),
        ("Precision", precision_score(labels, bl_pred, zero_division=0),
         precision_score(labels, ens_pred, zero_division=0)),
        ("Recall", recall_score(labels, bl_pred, zero_division=0),
         recall_score(labels, ens_pred, zero_division=0)),
    ]:
        delta = ev - bv
        rows.append((name, bv, ev, delta))

    logger.info("  %-18s %12s %12s %10s", "Metric", "Baseline", "Expanded", "Delta")
    logger.info("  " + "-" * 54)
    for name, bv, ev, delta in rows:
        sign = "+" if delta >= 0 else ""
        logger.info("  %-18s %12.4f %12.4f %10s", name, bv, ev, f"{sign}{delta:.4f}")

    agree = (ens_pred == bl_pred).sum()
    disagree = len(labels) - agree
    logger.info("  Agreement: %d/%d (%.1f%%)", agree, len(labels), agree / len(labels) * 100)
    if disagree > 0:
        mask = ens_pred != bl_pred
        ens_right = (ens_pred[mask] == labels[mask]).sum()
        bl_right = (bl_pred[mask] == labels[mask]).sum()
        logger.info(
            "  On %d disagreements: expanded correct %d (%.0f%%), baseline correct %d (%.0f%%)",
            disagree, ens_right, ens_right / disagree * 100,
            bl_right, bl_right / disagree * 100,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    logger.info("=" * 70)
    logger.info("  Expanded Feature Ensemble Training Pipeline")
    logger.info("  %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 70)

    # ── Step 1: Load data ─────────────────────────────────────────────
    if not COMBINED_CSV.exists():
        logger.error("Training data not found at %s", COMBINED_CSV)
        sys.exit(1)

    df = pd.read_csv(COMBINED_CSV)
    logger.info("Loaded %d trades from %s", len(df), COMBINED_CSV.name)
    logger.info("  Date range: %s to %s", df["entry_date"].min(), df["entry_date"].max())
    logger.info("  Win rate: %.1f%%", df[TARGET_COL].mean() * 100)
    logger.info("  Strategies: %s", df["strategy_type"].value_counts().to_dict())

    # ── Step 2: Engineer expanded features ────────────────────────────
    logger.info("=" * 70)
    logger.info("STEP 2: Engineering expanded features")
    logger.info("=" * 70)

    df_expanded = engineer_expanded_features(df)

    # Verify all new columns exist
    missing = [c for c in EXPANDED_NUMERIC if c not in df_expanded.columns]
    if missing:
        logger.error("Missing engineered columns: %s", missing)
        sys.exit(1)

    # Show distribution of new features
    new_cols = [c for c in EXPANDED_NUMERIC if c not in NUMERIC_FEATURES]
    logger.info("  New feature distributions:")
    for col in new_cols:
        s = df_expanded[col].dropna()
        logger.info("    %-25s mean=%7.2f  std=%7.2f  min=%7.2f  max=%7.2f",
                     col, s.mean(), s.std(), s.min(), s.max())

    # ── Step 3: Train EnsembleSignalModel on expanded features ────────
    logger.info("=" * 70)
    logger.info("STEP 3: Training EnsembleSignalModel (expanded features)")
    logger.info("=" * 70)

    features_df = prepare_features(
        df_expanded,
        numeric_features=EXPANDED_NUMERIC,
        categorical_features=CATEGORICAL_FEATURES,
    )
    labels = df_expanded[TARGET_COL].values.astype(int)

    logger.info("  Feature matrix: %d x %d", features_df.shape[0], features_df.shape[1])

    ensemble = EnsembleSignalModel(model_dir=str(MODEL_DIR))
    stats = ensemble.train(features_df, labels, calibrate=True, save_model=True, n_wf_folds=5)

    if not stats:
        logger.error("Training failed")
        sys.exit(1)

    logger.info("  Test AUC:       %.4f", stats["ensemble_test_auc"])
    logger.info("  Test Accuracy:  %.4f", stats["ensemble_test_accuracy"])
    logger.info("  Test Precision: %.4f", stats["ensemble_test_precision"])
    logger.info("  Test Recall:    %.4f", stats["ensemble_test_recall"])
    logger.info("  Weights: %s", {k: f"{v:.3f}" for k, v in stats["ensemble_weights"].items()})

    # ── Step 4: Walk-forward — 4-way comparison ───────────────────────
    logger.info("=" * 70)
    logger.info("STEP 4: Walk-forward validation (4-way comparison)")
    logger.info("=" * 70)

    # A) XGBoost on original features
    wf_xgb_orig = run_wf("XGB-Original", _make_xgb(), df,
                          NUMERIC_FEATURES, CATEGORICAL_FEATURES)

    # B) XGBoost on expanded features
    wf_xgb_exp = run_wf("XGB-Expanded", _make_xgb(), df_expanded,
                         EXPANDED_NUMERIC, CATEGORICAL_FEATURES)

    # C) Ensemble on original features
    wf_ens_orig = run_wf("Ensemble-Original", _make_ensemble(), df,
                          NUMERIC_FEATURES, CATEGORICAL_FEATURES)

    # D) Ensemble on expanded features
    wf_ens_exp = run_wf("Ensemble-Expanded", _make_ensemble(), df_expanded,
                         EXPANDED_NUMERIC, CATEGORICAL_FEATURES)

    # ── Summary table ────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 70)
    logger.info("  WALK-FORWARD COMPARISON MATRIX")
    logger.info("=" * 70)
    logger.info("  %-25s %8s %8s %8s %8s", "Metric", "XGB-Orig", "XGB-Exp", "Ens-Orig", "Ens-Exp")
    logger.info("  " + "-" * 59)

    configs = [
        ("XGB-Orig", wf_xgb_orig),
        ("XGB-Exp", wf_xgb_exp),
        ("Ens-Orig", wf_ens_orig),
        ("Ens-Exp", wf_ens_exp),
    ]

    for metric in ["auc_mean", "accuracy_mean", "brier_score_mean", "signal_sharpe_mean"]:
        label = metric.replace("_mean", "").replace("_", " ").title()
        vals = []
        for _, res in configs:
            v = res.get("aggregate", {}).get(metric)
            vals.append(f"{v:.4f}" if v is not None else "N/A")
        logger.info("  %-25s %8s %8s %8s %8s", label, *vals)

    # Highlight best AUC
    auc_vals = []
    for name, res in configs:
        v = res.get("aggregate", {}).get("auc_mean")
        if v is not None:
            auc_vals.append((name, v))
    if auc_vals:
        best = max(auc_vals, key=lambda x: x[1])
        logger.info("")
        logger.info("  Best OOS AUC: %s = %.4f", best[0], best[1])

    # ── Step 5: Compare with saved baseline model ─────────────────────
    compare_with_saved_baseline(ensemble, features_df, labels)

    # ── Done ──────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    logger.info("")
    logger.info("=" * 70)
    logger.info("  PIPELINE COMPLETE  (%.1f seconds)", elapsed)
    logger.info("=" * 70)
    logger.info("  Training trades:  %d", len(df))
    logger.info("  Original features: %d numeric + categoricals", len(NUMERIC_FEATURES))
    logger.info("  Expanded features: %d numeric + categoricals", len(EXPANDED_NUMERIC))
    logger.info("  Ensemble AUC:     %.4f", stats["ensemble_test_auc"])


if __name__ == "__main__":
    main()
