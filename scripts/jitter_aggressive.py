#!/usr/bin/env python3
"""Run jitter tests on top 10 aggressive configs."""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.jitter_test import run_jitter_test, print_report

TOP10_PATH = ROOT / "output" / "aggressive_top10_configs.json"
OUTPUT_PATH = ROOT / "output" / "aggressive_jitter_results.json"

N_VARIANTS = 25
NOISE = 0.15
TICKERS = ["SPY", "QQQ", "IWM"]


def main():
    configs = json.loads(TOP10_PATH.read_text())
    n_configs = len(configs)

    print(f"\n{'='*72}")
    print(f"  JITTER TEST — Top {n_configs} Aggressive Configs")
    print(f"  Variants per config: {N_VARIANTS}  |  Noise: ±{NOISE:.0%}")
    print(f"  Tickers: {TICKERS}")
    print(f"{'='*72}\n")

    all_results = []
    t_total = time.time()

    for i, cfg in enumerate(configs):
        run_id = cfg["run_id"]
        summary = cfg["summary"]
        strategy_params = cfg["strategy_params"]

        print(f"\n{'#'*72}")
        print(f"  Config #{i+1}/{n_configs}: {run_id}")
        print(f"  Base: {summary['avg_return']:+.1f}%/yr, DD={summary['worst_dd']:.1f}%, "
              f"consistency={summary['consistency_score']:.0%}")
        print(f"  Strategies: {list(strategy_params.keys())}")
        print(f"{'#'*72}")

        report = run_jitter_test(
            base_params=strategy_params,
            n_variants=N_VARIANTS,
            noise=NOISE,
            tickers=TICKERS,
            seed=42 + i,
        )
        print_report(report)

        all_results.append({
            "rank": i + 1,
            "run_id": run_id,
            "base_avg_return": summary["avg_return"],
            "base_worst_dd": summary["worst_dd"],
            "base_consistency": summary["consistency_score"],
            "strategies": list(strategy_params.keys()),
            "strategy_params": strategy_params,
            "jitter_verdict": report["status"],
            "jitter_stability_ratio": report["stability_ratio"],
            "jitter_mean_return": report["jitter_mean_return"],
            "jitter_std_return": report["jitter_std_return"],
            "jitter_min_return": report["jitter_min_return"],
            "jitter_max_return": report["jitter_max_return"],
            "jitter_profitable_pct": report["variant_profitability"],
            "cliff_variants": report["cliff_variants"],
        })

    elapsed = time.time() - t_total

    # Robustness scoring (same formula as conservative pipeline)
    for r in all_results:
        r["robustness_score"] = (
            r["jitter_stability_ratio"] * 0.5
            + r["jitter_profitable_pct"] * 0.3
            + (1 - r["cliff_variants"] / N_VARIANTS) * 0.2
        )

    all_results.sort(key=lambda x: x["robustness_score"], reverse=True)

    print(f"\n\n{'='*72}")
    print(f"  FINAL ROBUSTNESS RANKING (sorted by robustness score)")
    print(f"{'='*72}")
    print(f"{'Rank':>4}  {'Verdict':>8}  {'RobScore':>8}  {'Stability':>9}  {'BaseRet':>8}  {'JitMean':>8}  {'JitMin':>8}  {'DD':>7}  {'Cliffs':>6}")
    print("-" * 90)
    for j, r in enumerate(all_results):
        print(f"{j+1:>4}  {r['jitter_verdict']:>8}  {r['robustness_score']:>8.3f}  "
              f"{r['jitter_stability_ratio']:>9.3f}  {r['base_avg_return']:>+7.1f}%  "
              f"{r['jitter_mean_return']:>+7.1f}%  {r['jitter_min_return']:>+7.1f}%  "
              f"{r['base_worst_dd']:>+6.1f}%  {r['cliff_variants']:>6}")
    print(f"{'='*72}")
    print(f"  Total elapsed: {elapsed/60:.1f} minutes")

    # Save results
    OUTPUT_PATH.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"  Results saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
