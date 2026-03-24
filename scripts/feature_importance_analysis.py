#!/usr/bin/env python3
"""
Feature importance analysis for the COMPASS ensemble signal model.

Loads the trained ensemble, runs permutation importance on a held-out test
split, and compares the training feature set against the full FeatureEngine
catalogue to identify unused features worth adding.

Usage:
    python scripts/feature_importance_analysis.py

Output:
    analysis/feature_importance.txt
"""

import sys
import os
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from compass.features import FeatureEngine
from compass.walk_forward import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    prepare_features,
)
from shared.indicators import sanitize_features

# ── Configuration ─────────────────────────────────────────────────────────────

MODEL_PATH = PROJECT_ROOT / "ml" / "models" / "ensemble_model_20260324.joblib"
TRAINING_CSV = PROJECT_ROOT / "compass" / "training_data_combined.csv"
OUTPUT_PATH = PROJECT_ROOT / "analysis" / "feature_importance.txt"
RANDOM_STATE = 42
TEST_SIZE = 0.20
N_PERMUTATION_REPEATS = 10


# ── Wrapper class for permutation_importance ──────────────────────────────────

class EnsembleWrapper:
    """Wraps the calibrated ensemble models so sklearn's permutation_importance
    can call .predict_proba() on it."""

    def __init__(self, calibrated_models, ensemble_weights):
        self.calibrated_models = calibrated_models
        self.ensemble_weights = ensemble_weights

    def predict_proba(self, X):
        weighted_sum = np.zeros((X.shape[0], 2))
        total_weight = 0.0
        for name, model in self.calibrated_models.items():
            w = self.ensemble_weights.get(name, 0.0)
            if w <= 0:
                continue
            proba = model.predict_proba(X)
            weighted_sum += w * proba
            total_weight += w
        if total_weight > 0:
            weighted_sum /= total_weight
        return weighted_sum

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] > 0.5).astype(int)

    def fit(self, X, y):
        """No-op — model is already trained. Required by sklearn API."""
        return self


# ── Main analysis ─────────────────────────────────────────────────────────────

def load_ensemble(path):
    """Load the trained ensemble from disk."""
    data = joblib.load(path)
    wrapper = EnsembleWrapper(
        data["calibrated_models"],
        data["ensemble_weights"],
    )
    return wrapper, data


def load_and_split_data(csv_path, feature_names):
    """Load training CSV and prepare features matching the model's expectations."""
    df = pd.read_csv(csv_path)
    features_df = prepare_features(
        df,
        numeric_features=NUMERIC_FEATURES,
        categorical_features=CATEGORICAL_FEATURES,
    )

    # Align columns to match the saved model's feature order
    for col in feature_names:
        if col not in features_df.columns:
            features_df[col] = 0.0
    features_df = features_df[feature_names]

    X = sanitize_features(features_df.values)
    y = df["win"].values.astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y,
    )
    return X_train, X_test, y_train, y_test, feature_names


def run_permutation_importance(wrapper, X_test, y_test, feature_names):
    """Run permutation importance and return sorted results."""

    def auc_scorer(estimator, X, y):
        proba = estimator.predict_proba(X)[:, 1]
        return roc_auc_score(y, proba)

    result = permutation_importance(
        wrapper,
        X_test,
        y_test,
        scoring=auc_scorer,
        n_repeats=N_PERMUTATION_REPEATS,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    importance_data = []
    for i, name in enumerate(feature_names):
        importance_data.append({
            "feature": name,
            "importance_mean": result.importances_mean[i],
            "importance_std": result.importances_std[i],
        })

    importance_data.sort(key=lambda x: x["importance_mean"], reverse=True)
    return importance_data


def compute_baseline_auc(wrapper, X_test, y_test):
    """Compute the baseline AUC on the test set."""
    proba = wrapper.predict_proba(X_test)[:, 1]
    return roc_auc_score(y_test, proba)


def identify_feature_gaps():
    """Compare FeatureEngine features against current training features."""
    fe = FeatureEngine()
    fe_features = set(fe.get_feature_names())
    wf_features = set(NUMERIC_FEATURES)

    # Features in FeatureEngine but NOT in training data
    unused = fe_features - wf_features

    # Categorize unused features
    categories = {
        "IV Surface / Volatility": [
            ("current_iv", "Current ATM implied volatility — direct measure of option richness"),
            ("rv_iv_spread", "Realized vol minus implied vol — positive = vol premium sellers can harvest"),
            ("realized_vol_60d", "60-day realized vol — longer lookback captures regime shifts"),
            ("put_call_skew_ratio", "Put/call IV ratio — >1.15 signals fear skew, favors bull puts"),
            ("put_skew_steepness", "How steep the put skew is — higher = more tail risk priced in"),
            ("vol_premium", "IV - RV in absolute terms — the core edge for premium sellers"),
            ("vol_premium_pct", "Vol premium as percentage of RV — scale-invariant version"),
        ],
        "Event Risk": [
            ("days_to_earnings", "Days until next earnings — trades near earnings have higher risk"),
            ("days_to_fomc", "Days until next FOMC meeting — vol compression/expansion cycle"),
            ("days_to_cpi", "Days until next CPI release — inflation surprises move markets"),
            ("event_risk_score", "Composite event risk (0-1) — aggregates earnings/FOMC/CPI proximity"),
        ],
        "Seasonal / Calendar": [
            ("is_opex_week", "Options expiration week — elevated gamma, pin risk"),
            ("is_monday", "Monday effect — historically higher volatility from weekend gap"),
            ("is_month_end", "Month-end rebalancing — institutional flows cause anomalies"),
        ],
        "Market Microstructure": [
            ("vix_level", "VIX level — already have 'vix' but this is the live-FeatureEngine version"),
            ("vix_change_1d", "1-day VIX change (%) — sudden spikes signal regime shifts"),
            ("vix_change_5d", "5-day VIX change (points) — trend in fear gauge"),
            ("spy_return_5d", "SPY 5-day return (%) — short-term market momentum"),
            ("spy_return_20d", "SPY 20-day return (%) — medium-term trend context"),
            ("spy_realized_vol", "SPY 20-day realized vol — market-wide volatility backdrop"),
            ("put_call_ratio", "CBOE put/call ratio (currently placeholder=1.0 in FeatureEngine)"),
        ],
        "Technical / Momentum": [
            ("rsi_oversold", "Binary: RSI < 30 — oversold conditions favor bull puts"),
            ("rsi_overbought", "Binary: RSI > 70 — overbought conditions favor bear calls"),
            ("iv_rank_high", "Binary: IV rank > 70 — high-IV-rank regime flag"),
            ("iv_rank_low", "Binary: IV rank < 30 — low-IV-rank regime flag"),
            ("macd", "MACD line — trend-following signal (mixed value for premium selling)"),
            ("macd_signal", "MACD signal line — crossover triggers"),
            ("macd_histogram", "MACD histogram — momentum acceleration"),
            ("bollinger_pct_b", "Bollinger %B — mean-reversion signal"),
            ("atr_pct", "ATR as % of price — normalized volatility measure"),
            ("volume_ratio", "Current volume / 20-day avg — unusual activity detection"),
            ("return_5d", "5-day return % (FeatureEngine version)"),
            ("return_10d", "10-day return %"),
            ("return_20d", "20-day return %"),
            ("risk_adjusted_momentum", "20d return / ATR% — momentum per unit of risk"),
            ("credit_to_width_ratio", "Credit / spread width — direct risk/reward metric"),
        ],
        "Regime (FeatureEngine format)": [
            ("regime_id", "Numeric regime ID (FeatureEngine uses different encoding than training)"),
            ("regime_confidence", "Regime classifier confidence — low confidence = transition period"),
            ("regime_duration_days", "Days in current regime — fresh regimes are less reliable"),
            ("regime_low_vol_trending", "One-hot: low-vol trending regime"),
            ("regime_high_vol_trending", "One-hot: high-vol trending regime"),
            ("regime_mean_reverting", "One-hot: mean-reverting regime"),
            ("regime_crisis", "One-hot: crisis regime"),
        ],
        "SMA Distance (FeatureEngine naming)": [
            ("dist_from_sma20_pct", "Same concept as dist_from_ma20_pct with different naming"),
            ("dist_from_sma50_pct", "Same concept as dist_from_ma50_pct with different naming"),
            ("dist_from_sma200_pct", "Same concept as dist_from_ma200_pct with different naming"),
        ],
    }
    return categories


def format_report(
    baseline_auc,
    importance_data,
    feature_gaps,
    model_data,
    n_train,
    n_test,
):
    """Format the analysis report as a text string."""
    lines = []
    w = lines.append

    stats = model_data.get("training_stats", {})
    timestamp = model_data.get("timestamp", "unknown")

    w("=" * 78)
    w("COMPASS Ensemble — Feature Importance Analysis")
    w("=" * 78)
    w(f"Date:              {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    w(f"Model:             {MODEL_PATH.name}")
    w(f"Model trained:     {timestamp}")
    w(f"Training data:     {TRAINING_CSV.name}")
    w(f"Test split:        {TEST_SIZE*100:.0f}% ({n_test} trades)")
    w(f"Train split:       {100-TEST_SIZE*100:.0f}% ({n_train} trades)")
    w(f"Perm. repeats:     {N_PERMUTATION_REPEATS}")
    w("")

    # ── Model baseline
    w("-" * 78)
    w("MODEL BASELINE")
    w("-" * 78)
    w(f"Test AUC (this split):     {baseline_auc:.4f}")
    w(f"Train AUC (model report):  {stats.get('ensemble_test_auc', 'N/A')}")
    w(f"Total features:            {stats.get('n_features', len(importance_data))}")
    w(f"Positive rate:             {stats.get('positive_rate', 'N/A'):.1%}" if isinstance(stats.get('positive_rate'), float) else "")
    w("")

    weights = model_data.get("ensemble_weights", {})
    w("Ensemble weights:")
    for name, weight in sorted(weights.items()):
        per_model = stats.get("per_model", {}).get(name, {})
        auc = per_model.get("test_auc", "N/A")
        w(f"  {name:<20s}  weight={weight:.4f}  train_AUC={auc}")
    w("")

    # ── Top features
    w("-" * 78)
    w("TOP 10 FEATURES (by permutation importance on AUC)")
    w("-" * 78)
    w(f"{'Rank':<5} {'Feature':<35} {'Imp. Mean':>10} {'Imp. Std':>10}")
    w(f"{'─'*5} {'─'*35} {'─'*10} {'─'*10}")
    for i, d in enumerate(importance_data[:10], 1):
        w(f"{i:<5d} {d['feature']:<35s} {d['importance_mean']:>10.4f} {d['importance_std']:>10.4f}")
    w("")

    # Interpretation
    top = importance_data[0]
    w("Interpretation:")
    if top["importance_mean"] > 0.05:
        w(f"  • {top['feature']} is the dominant feature — shuffling it drops AUC by "
          f"{top['importance_mean']:.4f} (±{top['importance_std']:.4f}).")
    w(f"  • Features with importance > 0.01 are meaningfully contributing to predictions.")
    w(f"  • Features with importance < 0.001 are noise — candidates for removal.")
    w("")

    # ── Bottom features
    w("-" * 78)
    w("BOTTOM 10 FEATURES (lowest / negative importance)")
    w("-" * 78)
    w(f"{'Rank':<5} {'Feature':<35} {'Imp. Mean':>10} {'Imp. Std':>10}")
    w(f"{'─'*5} {'─'*35} {'─'*10} {'─'*10}")
    bottom = importance_data[-10:]
    for i, d in enumerate(bottom, len(importance_data) - 9):
        w(f"{i:<5d} {d['feature']:<35s} {d['importance_mean']:>10.4f} {d['importance_std']:>10.4f}")
    w("")

    negative = [d for d in importance_data if d["importance_mean"] < 0]
    near_zero = [d for d in importance_data if abs(d["importance_mean"]) < 0.001]
    w("Interpretation:")
    if negative:
        w(f"  • {len(negative)} feature(s) have NEGATIVE importance — they actively hurt the model.")
        w(f"    Removing them would improve AUC. Candidates:")
        for d in negative:
            w(f"      - {d['feature']} (importance={d['importance_mean']:.4f})")
    if near_zero:
        w(f"  • {len(near_zero)} feature(s) are near-zero (|imp| < 0.001) — noise, safe to remove.")
    w("")

    # ── Feature gap analysis
    w("=" * 78)
    w("FEATURE GAP ANALYSIS: FeatureEngine features NOT in current training set")
    w("=" * 78)
    w("")

    # Rank categories by expected value
    priority_order = [
        "IV Surface / Volatility",
        "Event Risk",
        "Market Microstructure",
        "Seasonal / Calendar",
        "Technical / Momentum",
        "Regime (FeatureEngine format)",
        "SMA Distance (FeatureEngine naming)",
    ]

    for category in priority_order:
        features = feature_gaps.get(category, [])
        if not features:
            continue
        w(f"── {category} ({len(features)} features) ──")
        w("")
        for feat_name, description in features:
            w(f"  {feat_name:<30s}  {description}")
        w("")

    # ── Recommendations
    w("=" * 78)
    w("RECOMMENDATIONS")
    w("=" * 78)
    w("")
    w("Priority 1 — Add to training data (HIGH expected value):")
    w("  These features capture the core edge of credit spread selling")
    w("  and are computable from data already available in the system.")
    w("")
    w("  1. credit_to_width_ratio    — Direct risk/reward of the trade structure.")
    w("                                 Already in FeatureEngine, trivially computed")
    w("                                 from net_credit and spread_width in training CSV.")
    w("  2. vix_change_5d            — 5-day VIX momentum. Sudden vol spikes are the")
    w("                                 #1 cause of credit spread losses. Available from")
    w("                                 VIX history already loaded in collect_training_data.")
    w("  3. rv_iv_spread             — Realized-vs-implied vol gap. Positive = vol premium")
    w("                                 available to sell. Computable from realized_vol_20d")
    w("                                 and iv_rank (proxy) already in training data.")
    w("  4. event_risk_score         — Composite event proximity. Trades entered near")
    w("                                 FOMC/CPI have different risk profiles. FOMC dates")
    w("                                 are in shared/constants.py.")
    w("  5. days_to_fomc             — Days until next FOMC meeting. Direct calendar")
    w("                                 feature from FOMC_DATES constant.")
    w("")
    w("Priority 2 — Add to training data (MODERATE expected value):")
    w("  These require additional data but have theoretical support.")
    w("")
    w("  6. is_opex_week             — OPEX week has elevated gamma risk and pin effects.")
    w("                                 Binary feature, trivially computed from date.")
    w("  7. regime_confidence        — Low-confidence regime classifications are unreliable.")
    w("                                 Regime detector already computes this.")
    w("  8. regime_duration_days     — Fresh regimes (<5 days) are less reliable than")
    w("                                 established ones (>20 days).")
    w("  9. bollinger_pct_b          — Mean-reversion signal. When %B is extreme (<0 or >1),")
    w("                                 credit spreads on the reversal side outperform.")
    w("")
    w("Priority 3 — Consider removing (NEGATIVE or near-zero importance):")
    w("")
    removal_candidates = [d for d in importance_data if d["importance_mean"] < 0.0005]
    for d in removal_candidates[:5]:
        w(f"  • {d['feature']:<35s}  importance={d['importance_mean']:.4f}")
    w("")
    w("Priority 4 — NOT recommended (duplicate or placeholder):")
    w("")
    w("  • put_call_ratio           — Hardcoded to 1.0 in FeatureEngine. Zero signal.")
    w("  • dist_from_sma*_pct       — Already have dist_from_ma*_pct (different naming only).")
    w("  • regime_id / regime_*     — Already one-hot encoded in training (regime_bull, etc.).")
    w("  • macd / macd_*            — Trend-following signals; philosophically misaligned")
    w("                                with premium-selling strategies.")
    w("")

    # ── Full ranking table
    w("=" * 78)
    w("FULL FEATURE RANKING (all {} features)".format(len(importance_data)))
    w("=" * 78)
    w(f"{'Rank':<5} {'Feature':<35} {'Imp. Mean':>10} {'Imp. Std':>10} {'Verdict':>12}")
    w(f"{'─'*5} {'─'*35} {'─'*10} {'─'*10} {'─'*12}")
    for i, d in enumerate(importance_data, 1):
        imp = d["importance_mean"]
        if imp > 0.01:
            verdict = "STRONG"
        elif imp > 0.001:
            verdict = "useful"
        elif imp > -0.001:
            verdict = "noise"
        else:
            verdict = "HARMFUL"
        w(f"{i:<5d} {d['feature']:<35s} {imp:>10.4f} {d['importance_std']:>10.4f} {verdict:>12}")
    w("")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("COMPASS Feature Importance Analysis")
    print("=" * 60)

    # 1. Load model
    print(f"\n[1/5] Loading ensemble from {MODEL_PATH.name}...")
    if not MODEL_PATH.exists():
        print(f"ERROR: Model not found at {MODEL_PATH}")
        sys.exit(1)
    wrapper, model_data = load_ensemble(MODEL_PATH)
    feature_names = model_data["feature_names"]
    print(f"  Loaded {len(feature_names)} features, "
          f"{len(model_data['calibrated_models'])} base models")

    # 2. Load and split data
    print(f"\n[2/5] Loading training data from {TRAINING_CSV.name}...")
    if not TRAINING_CSV.exists():
        print(f"ERROR: Training data not found at {TRAINING_CSV}")
        sys.exit(1)
    X_train, X_test, y_train, y_test, feature_names = load_and_split_data(
        TRAINING_CSV, feature_names,
    )
    print(f"  Train: {len(X_train)} trades | Test: {len(X_test)} trades")
    print(f"  Win rate: {y_test.mean():.1%} (test) | {y_train.mean():.1%} (train)")

    # 3. Baseline AUC
    print("\n[3/5] Computing baseline AUC...")
    baseline_auc = compute_baseline_auc(wrapper, X_test, y_test)
    print(f"  Baseline test AUC: {baseline_auc:.4f}")

    # 4. Permutation importance
    print(f"\n[4/5] Running permutation importance ({N_PERMUTATION_REPEATS} repeats)...")
    importance_data = run_permutation_importance(
        wrapper, X_test, y_test, feature_names,
    )

    print("\n  Top 5 features:")
    for i, d in enumerate(importance_data[:5], 1):
        print(f"    {i}. {d['feature']:<30s}  {d['importance_mean']:+.4f}")
    print("  Bottom 3 features:")
    for d in importance_data[-3:]:
        print(f"    • {d['feature']:<30s}  {d['importance_mean']:+.4f}")

    # 5. Feature gap analysis
    print("\n[5/5] Analyzing feature gaps vs FeatureEngine...")
    feature_gaps = identify_feature_gaps()
    total_unused = sum(len(v) for v in feature_gaps.values())
    print(f"  {total_unused} FeatureEngine features NOT in current training set")

    # Write report
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = format_report(
        baseline_auc=baseline_auc,
        importance_data=importance_data,
        feature_gaps=feature_gaps,
        model_data=model_data,
        n_train=len(X_train),
        n_test=len(X_test),
    )
    OUTPUT_PATH.write_text(report)
    print(f"\n{'='*60}")
    print(f"Report written to {OUTPUT_PATH}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
