#!/usr/bin/env python3
"""
Benchmark the production XGBoost signal model.

Loads the saved model from ml/models/, inspects its properties, and cross-
references walk-forward accuracy with per-year backtest results from
output/backtest_results_polygon_REAL_*.json to establish the baseline that
the ensemble must beat.

Usage:
    python scripts/benchmark_models.py
    python scripts/benchmark_models.py --model ml/models/signal_model_20260321.joblib
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

# Resolve project root (one level up from scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.WARNING)

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_MODEL = PROJECT_ROOT / "ml" / "models" / "signal_model_20260321.joblib"
BACKTEST_DIR = PROJECT_ROOT / "output"
BACKTEST_GLOB = "backtest_results_polygon_REAL_*.json"

# ── Helpers ──────────────────────────────────────────────────────────────────


def _fmt_pct(v, digits=1):
    """Format a fraction as a percentage string."""
    if v is None:
        return "n/a"
    return f"{v * 100:.{digits}f}%"


def _fmt_money(v):
    if v is None:
        return "n/a"
    return f"${v:,.0f}"


def _bar(label, width=60):
    print(f"\n{'─' * width}")
    print(f"  {label}")
    print(f"{'─' * width}")


# ── Model inspection ─────────────────────────────────────────────────────────


def inspect_model(model_path: Path) -> dict:
    """Load and inspect a saved SignalModel joblib.

    Returns a summary dict for later printing and comparison.
    """
    resolved = os.path.realpath(model_path)
    expected = os.path.realpath(model_path.parent)
    if not resolved.startswith(expected + os.sep) and resolved != expected:
        print(f"SECURITY: path {resolved} outside {expected}, aborting.")
        sys.exit(1)

    data = joblib.load(model_path)

    model = data["model"]
    feature_names = data.get("feature_names", [])
    training_stats = data.get("training_stats", {})
    timestamp = data.get("timestamp")
    feature_means = data.get("feature_means")
    feature_stds = data.get("feature_stds")
    calibrated = data.get("calibrated_model") is not None

    # Model metadata
    params = model.get_params() if hasattr(model, "get_params") else {}
    classes = list(model.classes_) if hasattr(model, "classes_") else []

    # Age
    age_days = None
    if timestamp:
        try:
            trained_at = datetime.fromisoformat(timestamp)
            if trained_at.tzinfo is None:
                trained_at = trained_at.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - trained_at).days
        except (ValueError, TypeError):
            pass

    # Feature importances (global from the model, not per-fold)
    importances = {}
    if hasattr(model, "feature_importances_") and feature_names:
        for name, imp in zip(feature_names, model.feature_importances_):
            importances[name] = float(imp)

    return {
        "path": str(model_path),
        "model_type": type(model).__name__,
        "n_features": len(feature_names),
        "feature_names": feature_names,
        "n_estimators": params.get("n_estimators"),
        "max_depth": params.get("max_depth"),
        "learning_rate": params.get("learning_rate"),
        "subsample": params.get("subsample"),
        "colsample_bytree": params.get("colsample_bytree"),
        "gamma": params.get("gamma"),
        "reg_alpha": params.get("reg_alpha"),
        "reg_lambda": params.get("reg_lambda"),
        "min_child_weight": params.get("min_child_weight"),
        "classes": classes,
        "calibrated": calibrated,
        "timestamp": timestamp,
        "age_days": age_days,
        "training_stats": training_stats,
        "importances": importances,
        "has_drift_stats": feature_means is not None and feature_stds is not None,
    }


# ── Backtest loading ─────────────────────────────────────────────────────────


def load_backtest_results(backtest_dir: Path) -> dict:
    """Load all per-year backtest JSONs. Returns {year_label: result_dict}."""
    results = {}
    for fp in sorted(backtest_dir.glob(BACKTEST_GLOB)):
        with open(fp) as f:
            data = json.load(f)

        # Derive year label from filename
        stem = fp.stem  # e.g. backtest_results_polygon_REAL_2023
        year_label = stem.replace("backtest_results_polygon_REAL_", "")

        if data.get("results"):
            r = data["results"][0]
            results[year_label] = {
                "total_trades": r.get("total_trades", 0),
                "win_rate": r.get("win_rate", 0),
                "total_pnl": r.get("total_pnl", 0),
                "return_pct": r.get("return_pct", 0),
                "max_drawdown": r.get("max_drawdown", 0),
                "sharpe_ratio": r.get("sharpe_ratio", 0),
                "avg_win": r.get("avg_win", 0),
                "avg_loss": r.get("avg_loss", 0),
                "bull_put_trades": r.get("bull_put_trades", 0),
                "bear_call_trades": r.get("bear_call_trades", 0),
                "iron_condor_trades": r.get("iron_condor_trades", 0),
                "weekly_consistency": r.get("weekly_consistency", 0),
            }

    return results


# ── Printing ─────────────────────────────────────────────────────────────────


def print_model_summary(info: dict):
    _bar("MODEL PROPERTIES")

    print(f"  Path            : {info['path']}")
    print(f"  Model type      : {info['model_type']}")
    print(f"  Trained         : {info['timestamp']}")
    print(f"  Age             : {info['age_days']} days")
    print(f"  Calibrated      : {info['calibrated']}")
    print(f"  Drift stats     : {info['has_drift_stats']}")
    print(f"  Classes         : {info['classes']}")
    print()
    print(f"  n_features      : {info['n_features']}")
    print(f"  n_estimators    : {info['n_estimators']}")
    print(f"  max_depth       : {info['max_depth']}")
    print(f"  learning_rate   : {info['learning_rate']}")
    print(f"  subsample       : {info['subsample']}")
    print(f"  colsample_bytree: {info['colsample_bytree']}")
    print(f"  gamma           : {info['gamma']}")
    print(f"  min_child_weight: {info['min_child_weight']}")
    print(f"  reg_alpha       : {info['reg_alpha']}")
    print(f"  reg_lambda      : {info['reg_lambda']}")

    _bar("FEATURE NAMES")
    for i, name in enumerate(info["feature_names"]):
        imp = info["importances"].get(name)
        imp_str = f"  (importance: {imp:.4f})" if imp is not None else ""
        print(f"  {i + 1:>2}. {name:<30s}{imp_str}")

    # Top features by importance
    if info["importances"]:
        _bar("TOP 10 FEATURES (global importance)")
        ranked = sorted(info["importances"].items(), key=lambda x: x[1], reverse=True)
        for rank, (name, imp) in enumerate(ranked[:10], 1):
            bar_len = int(imp * 200)
            print(f"  {rank:>2}. {name:<30s} {imp:.4f}  {'█' * bar_len}")


def print_walk_forward(info: dict):
    folds = info["training_stats"].get("walk_forward_folds", [])
    if not folds:
        print("\n  (no walk-forward data in training_stats)")
        return

    _bar("WALK-FORWARD RESULTS (ML model out-of-sample)")

    header = f"  {'Year':>6s}  {'N_train':>7s}  {'N_test':>6s}  {'AUC':>7s}  {'Acc':>7s}  {'Prec':>7s}  {'Recall':>7s}  {'WR_test':>7s}"
    print(header)
    print(f"  {'─' * (len(header) - 2)}")

    auc_vals = []
    acc_vals = []
    for fold in folds:
        yr = fold.get("test_year", "?")
        n_tr = fold.get("n_train", 0)
        n_te = fold.get("n_test", 0)
        auc = fold.get("auc", 0)
        acc = fold.get("accuracy", 0)
        prec = fold.get("precision", 0)
        rec = fold.get("recall", 0)
        wr = fold.get("test_win_rate", 0)
        auc_vals.append(auc)
        acc_vals.append(acc)
        print(
            f"  {yr:>6}  {n_tr:>7d}  {n_te:>6d}  {auc:>7.4f}  "
            f"{acc:>7.4f}  {prec:>7.4f}  {rec:>7.4f}  {_fmt_pct(wr):>7s}"
        )

    if auc_vals:
        print(f"  {'─' * (len(header) - 2)}")
        print(
            f"  {'AVG':>6s}  {'':>7s}  {'':>6s}  {np.mean(auc_vals):>7.4f}  "
            f"{np.mean(acc_vals):>7.4f}"
        )

    # Quality gates
    gates = info["training_stats"].get("gates", {})
    if gates:
        _bar("QUALITY GATES")
        for gate, passed in gates.items():
            status = "PASS" if passed else "FAIL"
            marker = "✓" if passed else "✗"
            print(f"  {marker} {gate:<25s} {status}")


def print_backtest_results(backtest: dict):
    _bar("BACKTEST RESULTS (per-year, real Polygon data)")

    header = (
        f"  {'Year':>8s}  {'Trades':>6s}  {'Win%':>6s}  {'PnL':>10s}  "
        f"{'Return':>8s}  {'MaxDD':>7s}  {'Sharpe':>7s}  {'Consist':>7s}"
    )
    print(header)
    print(f"  {'─' * (len(header) - 2)}")

    total_trades = 0
    total_pnl = 0
    sharpe_vals = []

    for year_label, r in sorted(backtest.items()):
        trades = r["total_trades"]
        wr = r["win_rate"]
        pnl = r["total_pnl"]
        ret = r["return_pct"]
        dd = r["max_drawdown"]
        sr = r["sharpe_ratio"]
        wc = r["weekly_consistency"]

        total_trades += trades
        total_pnl += pnl
        if trades > 20:
            sharpe_vals.append(sr)

        print(
            f"  {year_label:>8s}  {trades:>6d}  {wr:>5.1f}%  {_fmt_money(pnl):>10s}  "
            f"{ret:>7.1f}%  {dd:>6.1f}%  {sr:>7.2f}  {wc:>6.1f}%"
        )

    print(f"  {'─' * (len(header) - 2)}")
    print(
        f"  {'TOTAL':>8s}  {total_trades:>6d}  {'':>6s}  {_fmt_money(total_pnl):>10s}  "
        f"{'':>8s}  {'':>7s}  {np.mean(sharpe_vals):>7.2f}"
    )


def print_cross_reference(info: dict, backtest: dict):
    """Side-by-side: ML walk-forward accuracy vs backtest win rate per year."""
    folds = info["training_stats"].get("walk_forward_folds", [])
    if not folds:
        return

    _bar("CROSS-REFERENCE: ML accuracy vs backtest win rate")

    header = f"  {'Year':>6s}  {'ML AUC':>7s}  {'ML Acc':>7s}  {'BT Trades':>9s}  {'BT Win%':>7s}  {'BT Sharpe':>9s}  {'BT PnL':>10s}"
    print(header)
    print(f"  {'─' * (len(header) - 2)}")

    for fold in folds:
        yr = str(fold.get("test_year", "?"))
        auc = fold.get("auc", 0)
        acc = fold.get("accuracy", 0)

        bt = backtest.get(yr, {})
        bt_trades = bt.get("total_trades", "—")
        bt_wr = bt.get("win_rate")
        bt_sr = bt.get("sharpe_ratio")
        bt_pnl = bt.get("total_pnl")

        bt_wr_s = f"{bt_wr:.1f}%" if bt_wr is not None else "—"
        bt_sr_s = f"{bt_sr:.2f}" if bt_sr is not None else "—"
        bt_pnl_s = _fmt_money(bt_pnl) if bt_pnl is not None else "—"

        print(
            f"  {yr:>6s}  {auc:>7.4f}  {acc:>7.4f}  {bt_trades:>9}  "
            f"{bt_wr_s:>7s}  {bt_sr_s:>9s}  {bt_pnl_s:>10s}"
        )


def print_ensemble_targets(info: dict):
    """Print the targets the ensemble model should beat."""
    folds = info["training_stats"].get("walk_forward_folds", [])
    auc_vals = [f["auc"] for f in folds if "auc" in f]
    acc_vals = [f["accuracy"] for f in folds if "accuracy" in f]

    _bar("ENSEMBLE TARGETS (must beat these baselines)")
    if auc_vals:
        print(f"  Avg AUC       : {np.mean(auc_vals):.4f}  (min fold: {min(auc_vals):.4f})")
        print(f"  Avg Accuracy  : {np.mean(acc_vals):.4f}  (min fold: {min(acc_vals):.4f})")
    print(f"  Model type    : {info['model_type']} (single model)")
    print(f"  n_estimators  : {info['n_estimators']}")
    print(f"  n_features    : {info['n_features']}")
    print()
    print("  The ensemble should improve on:")
    print("    1. Average OOS AUC across walk-forward folds")
    print("    2. Worst-fold AUC (robustness)")
    print("    3. Calibration (g3_calibration gate currently FAILS)")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Benchmark the production signal model")
    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_MODEL,
        help="Path to the .joblib model file",
    )
    parser.add_argument(
        "--backtest-dir",
        type=Path,
        default=BACKTEST_DIR,
        help="Directory containing backtest_results_polygon_REAL_*.json",
    )
    args = parser.parse_args()

    if not args.model.exists():
        print(f"ERROR: model not found at {args.model}")
        sys.exit(1)

    # 1. Inspect model
    info = inspect_model(args.model)
    print_model_summary(info)

    # 2. Walk-forward results
    print_walk_forward(info)

    # 3. Backtest results
    backtest = load_backtest_results(args.backtest_dir)
    if backtest:
        print_backtest_results(backtest)
        print_cross_reference(info, backtest)
    else:
        print("\n  (no backtest result files found)")

    # 4. Targets
    print_ensemble_targets(info)

    print()


if __name__ == "__main__":
    main()
