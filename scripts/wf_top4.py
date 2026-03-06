#!/usr/bin/env python3
"""Walk-forward validation on top 4 jitter-tested configs."""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.walk_forward import WalkForwardOptimizer
from scripts.run_optimization import run_full, extract_yearly_results, compute_summary

OUTPUT = ROOT / "output"
JITTER_RESULTS = OUTPUT / "jitter_top10_results.json"
WF_OUTPUT = OUTPUT / "wf_top4_results.json"

YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
TICKERS = ["SPY", "QQQ", "IWM"]
MIN_TRAIN_YEARS = 3
EXPERIMENTS_PER_FOLD = 20

# Jitter-sorted indices (0-based) for the 4 configs we want
TARGET_INDICES = [0, 1, 2, 4]  # jitter ranks 1, 2, 3, 5


def run_wf_for_config(label, strategy_params, strategies):
    """Run walk-forward validation for a single config."""
    print(f"\n  Creating WalkForwardOptimizer (years={YEARS}, min_train={MIN_TRAIN_YEARS})")

    wfo = WalkForwardOptimizer(all_years=YEARS, min_train_years=MIN_TRAIN_YEARS)

    t0 = time.time()
    wf_results = wfo.run(
        strategy_names=strategies,
        tickers=TICKERS,
        n_experiments_per_fold=EXPERIMENTS_PER_FOLD,
        base_overrides=strategy_params,
    )
    elapsed = time.time() - t0

    wf_data = wf_results.get("walk_forward", {})

    # Print fold-by-fold results
    folds = wf_data.get("folds", [])
    print(f"\n  {'Fold':>4}  {'Train Yrs':>20}  {'Test':>5}  {'Train Ret':>10}  {'OOS Ret':>9}  {'OOS DD':>8}  {'OOS Trades':>10}")
    print(f"  {'-'*4}  {'-'*20}  {'-'*5}  {'-'*10}  {'-'*9}  {'-'*8}  {'-'*10}")
    for f in folds:
        train_str = f"{f['train'][0]}-{f['train'][-1]}"
        test_str = str(f['test'][0]) if isinstance(f['test'], list) else str(f['test'])
        print(f"  {f['fold']:>4}  {train_str:>20}  {test_str:>5}  "
              f"{f.get('train_return', 0):>+9.1f}%  {f.get('oos_return', 0):>+8.1f}%  "
              f"{f.get('oos_max_dd', 0):>+7.1f}%  {f.get('oos_trades', 0):>10}")

    # Summary
    wf_ratio = wf_data.get("wf_ratio", 0)
    avg_oos = wf_data.get("avg_oos_annual_return", 0)
    avg_train = wf_data.get("avg_train_annual_return", 0)
    folds_ok = wf_data.get("folds_profitable", 0)
    total_folds = wf_data.get("total_folds", 0)

    print(f"\n  WF Summary:")
    print(f"    Avg Train Return:  {avg_train:+.1f}%")
    print(f"    Avg OOS Return:    {avg_oos:+.1f}%")
    print(f"    WF Ratio:          {wf_ratio:.3f} (need >=0.70)")
    print(f"    Folds Profitable:  {folds_ok}/{total_folds}")
    print(f"    Elapsed:           {elapsed:.0f}s")

    if wf_ratio >= 0.70 and avg_oos >= 6.67:
        print(f"\n    >>> PASS: WF ratio {wf_ratio:.3f} >= 0.70, OOS {avg_oos:+.1f}% meets victory <<<")
    elif avg_oos >= 6.67:
        print(f"\n    >>> PARTIAL: OOS {avg_oos:+.1f}% meets victory but WF ratio {wf_ratio:.3f} < 0.70 <<<")
    else:
        print(f"\n    >>> FAIL: OOS {avg_oos:+.1f}% below victory threshold <<<")

    return {
        "wf_ratio": wf_ratio,
        "avg_oos_return": avg_oos,
        "avg_train_return": avg_train,
        "folds_profitable": folds_ok,
        "total_folds": total_folds,
        "folds": folds,
        "elapsed_sec": round(elapsed),
    }


def main():
    jitter_results = json.loads(JITTER_RESULTS.read_text())

    configs = []
    for idx in TARGET_INDICES:
        r = jitter_results[idx]
        configs.append({
            "jitter_rank": idx + 1,
            "orig_rank": r["rank"],
            "run_id": r["run_id"],
            "base_avg_return": r["base_avg_return"],
            "base_worst_dd": r["base_worst_dd"],
            "jitter_mean_return": r["jitter_mean_return"],
            "jitter_stability": r["jitter_stability_ratio"],
            "robustness_score": r["robustness_score"],
            "strategies": r["strategies"],
            "strategy_params": r["strategy_params"],
        })

    print("=" * 72)
    print("  WALK-FORWARD VALIDATION — Top 4 Jitter-Tested Configs")
    print(f"  Years: {YEARS}  |  Tickers: {TICKERS}")
    print(f"  Min train years: {MIN_TRAIN_YEARS}  |  Experiments/fold: {EXPERIMENTS_PER_FOLD}")
    print("=" * 72)

    for c in configs:
        print(f"\n  Config {c['jitter_rank']}: {c['run_id']}")
        print(f"    Base: {c['base_avg_return']:+.1f}%/yr, DD={c['base_worst_dd']:.1f}%, "
              f"jitter_mean={c['jitter_mean_return']:+.1f}%, robustness={c['robustness_score']:.3f}")
        print(f"    Strategies: {c['strategies']}")

    all_results = []
    t_total = time.time()

    for i, c in enumerate(configs):
        print(f"\n{'#' * 72}")
        print(f"  [{i+1}/4] Walk-Forward: Config {c['jitter_rank']} ({c['run_id']})")
        print(f"  Base: {c['base_avg_return']:+.1f}%/yr | Jitter mean: {c['jitter_mean_return']:+.1f}%")
        print(f"  Strategies: {c['strategies']}")
        print(f"{'#' * 72}")

        wf = run_wf_for_config(
            label=f"Config {c['jitter_rank']}",
            strategy_params=c["strategy_params"],
            strategies=c["strategies"],
        )

        result = {**c, "walk_forward": wf}
        del result["strategy_params"]  # too large for summary
        all_results.append(result)

    total_elapsed = time.time() - t_total

    # Final ranking by WF quality
    # Score: wf_ratio * 0.4 + (avg_oos / 30) * 0.4 + (folds_ok / total) * 0.2
    for r in all_results:
        wf = r["walk_forward"]
        r["wf_score"] = (
            min(wf["wf_ratio"], 1.0) * 0.4
            + min(max(wf["avg_oos_return"], 0) / 30.0, 1.0) * 0.4
            + (wf["folds_profitable"] / max(wf["total_folds"], 1)) * 0.2
        )

    all_results.sort(key=lambda x: x["wf_score"], reverse=True)

    print(f"\n\n{'=' * 72}")
    print(f"  FINAL WALK-FORWARD RANKING")
    print(f"{'=' * 72}")
    hdr = f"{'JitRk':>5}  {'WFScore':>7}  {'WFRatio':>7}  {'OOS Ret':>8}  {'Train Ret':>9}  {'Folds OK':>8}  {'BaseRet':>8}  {'JitMean':>8}"
    print(hdr)
    print("-" * 80)
    for r in all_results:
        wf = r["walk_forward"]
        print(f"{r['jitter_rank']:>5}  {r['wf_score']:>7.3f}  {wf['wf_ratio']:>7.3f}  "
              f"{wf['avg_oos_return']:>+7.1f}%  {wf['avg_train_return']:>+8.1f}%  "
              f"{wf['folds_profitable']:>3}/{wf['total_folds']:<4}  "
              f"{r['base_avg_return']:>+7.1f}%  {r['jitter_mean_return']:>+7.1f}%")
    print(f"{'=' * 72}")
    print(f"  Total elapsed: {total_elapsed / 60:.1f} minutes")

    # Save full results (with strategy_params from jitter file)
    # Re-attach strategy_params for the saved output
    for r in all_results:
        for jr in jitter_results:
            if jr["run_id"] == r["run_id"]:
                r["strategy_params"] = jr["strategy_params"]
                break

    WF_OUTPUT.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"  Results saved to {WF_OUTPUT}")


if __name__ == "__main__":
    main()
