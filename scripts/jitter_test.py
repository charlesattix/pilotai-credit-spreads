#!/usr/bin/env python3
"""
jitter_test.py — Parameter robustness via jittered backtests.

Generates N perturbed variants of a base param set (±10-20% noise on
numeric params, occasional flips on choice/bool), runs each through
PortfolioBacktester, and reports stability statistics.

Usage:
    # From leaderboard best:
    python3 scripts/jitter_test.py --from-leaderboard --n 25

    # From a config file:
    python3 scripts/jitter_test.py --config configs/best.json --n 20

    # Single strategy:
    python3 scripts/jitter_test.py --from-leaderboard --strategies credit_spread --n 25

    # Custom noise level:
    python3 scripts/jitter_test.py --from-leaderboard --noise 0.20 --n 30
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "output"


def load_base_params(
    from_leaderboard: bool = False,
    config_path: Optional[str] = None,
    strategy_names: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Load base params — from leaderboard best or config file.

    Returns {strategy_name: params_dict}.
    """
    if config_path:
        with open(config_path) as f:
            data = json.load(f)
        # If flat dict, wrap for first strategy
        if not any(isinstance(v, dict) for v in data.values()):
            name = (strategy_names or ["credit_spread"])[0]
            return {name: data}
        return data

    if from_leaderboard:
        lb_path = OUTPUT / "leaderboard.json"
        if not lb_path.exists():
            print("ERROR: No leaderboard found at output/leaderboard.json")
            sys.exit(1)
        lb = json.loads(lb_path.read_text())
        # Find best robust entry (or best overall)
        robust = [e for e in lb if (e.get("overfit_score") or 0) >= 0.70]
        if robust:
            best = max(robust, key=lambda e: e["summary"]["avg_return"])
        elif lb:
            best = max(lb, key=lambda e: e["summary"]["avg_return"])
        else:
            print("ERROR: Leaderboard is empty")
            sys.exit(1)

        strat_params = best.get("strategy_params", {})
        if strategy_names:
            strat_params = {k: v for k, v in strat_params.items() if k in strategy_names}
        print(f"  Base params from leaderboard run: {best['run_id']}")
        print(f"  Base avg return: {best['summary']['avg_return']:+.1f}%")
        return strat_params

    print("ERROR: Must specify --from-leaderboard or --config")
    sys.exit(1)


def generate_jittered_variants(
    base_params: Dict[str, Dict],
    n_variants: int,
    noise: float = 0.15,
    seed: int = 42,
) -> List[Dict[str, Dict]]:
    """Generate N jittered variants of the base params.

    Uses Optimizer.sample_near_best() per strategy.
    """
    from engine.optimizer import Optimizer

    variants = []
    for i in range(n_variants):
        variant = {}
        for strat_name, params in base_params.items():
            opt = Optimizer(strategy_name=strat_name, seed=seed + i)
            jittered = opt.sample_near_best(params, noise=noise)
            variant[strat_name] = jittered
        variants.append(variant)

    return variants


def run_jitter_test(
    base_params: Dict[str, Dict],
    n_variants: int = 25,
    noise: float = 0.15,
    years: Optional[List[int]] = None,
    tickers: Optional[List[str]] = None,
    seed: int = 42,
) -> Dict:
    """Run the full jitter test and return results."""
    from scripts.run_optimization import run_full, extract_yearly_results, compute_summary

    years = years or [2020, 2021, 2022, 2023, 2024, 2025]
    tickers = tickers or ["SPY"]

    # 1. Run baseline
    print("\n  [Base] Running baseline params...")
    t0 = time.time()
    base_results = run_full(base_params, years, tickers)
    base_by_year = extract_yearly_results(base_results)
    base_summary = compute_summary(base_by_year)
    base_avg = base_summary["avg_return"]
    base_elapsed = time.time() - t0
    print(f"  Baseline: {base_avg:+.1f}% avg return ({base_elapsed:.0f}s)")

    # 2. Generate variants
    variants = generate_jittered_variants(base_params, n_variants, noise, seed)

    # 3. Run each variant
    variant_results = []
    t_start = time.time()

    for i, variant_params in enumerate(variants):
        print(f"\n  [Jitter {i+1}/{n_variants}]", end=" ", flush=True)

        # Show key diffs from base
        diffs = []
        for strat, params in variant_params.items():
            base_p = base_params.get(strat, {})
            for k, v in params.items():
                bv = base_p.get(k)
                if bv != v and isinstance(v, (int, float)):
                    pct_change = ((v - bv) / abs(bv) * 100) if bv else 0
                    diffs.append(f"{k}={v}({pct_change:+.0f}%)")
        if diffs:
            print(f"  diffs: {', '.join(diffs[:4])}", end="", flush=True)

        try:
            results = run_full(variant_params, years, tickers)
            by_year = extract_yearly_results(results)
            summary = compute_summary(by_year)
            variant_results.append({
                "variant_idx": i,
                "params": variant_params,
                "avg_return": summary["avg_return"],
                "worst_dd": summary["worst_dd"],
                "years_profitable": summary["years_profitable"],
                "consistency": summary["consistency_score"],
            })
        except Exception as e:
            print(f"  ERROR: {e}")
            variant_results.append({
                "variant_idx": i,
                "params": variant_params,
                "avg_return": 0,
                "error": str(e),
            })

    total_elapsed = time.time() - t_start

    # 4. Analyze results
    valid = [r for r in variant_results if "error" not in r]
    if not valid:
        return {
            "status": "FAIL",
            "reason": "All jitter runs failed",
            "base_avg_return": base_avg,
            "variants_run": n_variants,
            "variants_succeeded": 0,
        }

    returns = [r["avg_return"] for r in valid]
    mean_return = sum(returns) / len(returns)
    min_return = min(returns)
    max_return = max(returns)
    std_return = (sum((r - mean_return) ** 2 for r in returns) / len(returns)) ** 0.5

    # Stability ratio: mean jittered return / base return
    stability_ratio = mean_return / base_avg if base_avg > 0 else 0
    stability_ratio = max(0, min(2.0, stability_ratio))

    # Cliff detection: any variant drops below 30% of base
    cliff_variants = [r for r in valid if base_avg > 0 and r["avg_return"] < base_avg * 0.30]

    # Consistency: fraction of variants that are profitable
    profitable_variants = sum(1 for r in returns if r > 0)
    variant_profitability = profitable_variants / len(returns)

    # Verdict
    if stability_ratio >= 0.70 and not cliff_variants and variant_profitability >= 0.80:
        verdict = "ROBUST"
    elif stability_ratio >= 0.50 and len(cliff_variants) <= 2:
        verdict = "MARGINAL"
    else:
        verdict = "FRAGILE"

    report = {
        "status": verdict,
        "noise_level": noise,
        "base_avg_return": round(base_avg, 2),
        "jitter_mean_return": round(mean_return, 2),
        "jitter_std_return": round(std_return, 2),
        "jitter_min_return": round(min_return, 2),
        "jitter_max_return": round(max_return, 2),
        "stability_ratio": round(stability_ratio, 3),
        "variants_run": n_variants,
        "variants_succeeded": len(valid),
        "variants_profitable": profitable_variants,
        "variant_profitability": round(variant_profitability, 3),
        "cliff_variants": len(cliff_variants),
        "cliff_details": [
            {"idx": r["variant_idx"], "return": r["avg_return"]}
            for r in cliff_variants
        ],
        "elapsed_sec": round(total_elapsed),
        "per_variant": variant_results,
    }

    return report


def print_report(report: Dict):
    """Pretty-print the jitter test report."""
    print("\n" + "=" * 72)
    print("  JITTER TEST RESULTS")
    print("=" * 72)
    print(f"  Verdict:              {report['status']}")
    print(f"  Noise level:          ±{report['noise_level']:.0%}")
    print(f"  Base avg return:      {report['base_avg_return']:+.1f}%")
    print(f"  Jitter mean return:   {report['jitter_mean_return']:+.1f}%")
    print(f"  Jitter std dev:       {report['jitter_std_return']:.1f}%")
    print(f"  Jitter range:         [{report['jitter_min_return']:+.1f}%, {report['jitter_max_return']:+.1f}%]")
    print(f"  Stability ratio:      {report['stability_ratio']:.3f} (need ≥0.70)")
    print(f"  Variants profitable:  {report['variants_profitable']}/{report['variants_run']} ({report['variant_profitability']:.0%})")
    print(f"  Cliff drops (<30%):   {report['cliff_variants']}")
    print(f"  Elapsed:              {report['elapsed_sec']}s")
    print("-" * 72)

    # Per-variant summary
    valid = [r for r in report["per_variant"] if "error" not in r]
    if valid:
        print(f"  {'#':>3}  {'Return':>10}  {'YrsProf':>8}  {'Consistency':>12}  {'WorstDD':>8}")
        print(f"  {'---':>3}  {'------':>10}  {'-------':>8}  {'-----------':>12}  {'-------':>8}")
        for r in sorted(valid, key=lambda x: x["avg_return"], reverse=True):
            flag = " <<" if r.get("avg_return", 0) < report["base_avg_return"] * 0.30 else ""
            print(f"  {r['variant_idx']:>3}  {r['avg_return']:>+9.1f}%"
                  f"  {r.get('years_profitable', '?'):>8}"
                  f"  {r.get('consistency', 0):>11.0%}"
                  f"  {r.get('worst_dd', 0):>7.1f}%{flag}")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="Parameter robustness jitter test")
    parser.add_argument("--from-leaderboard", action="store_true",
                        help="Use best leaderboard entry as base")
    parser.add_argument("--config", help="JSON file with base params")
    parser.add_argument("--strategies", help="Comma-separated strategy names")
    parser.add_argument("--n", type=int, default=25, help="Number of jittered variants (default: 25)")
    parser.add_argument("--noise", type=float, default=0.15,
                        help="Noise level for perturbation (default: 0.15 = ±15%%)")
    parser.add_argument("--years", help="Comma-separated years")
    parser.add_argument("--tickers", help="Comma-separated tickers (default: SPY)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--save", action="store_true", help="Save report to output/jitter_report.json")
    args = parser.parse_args()

    strategy_names = [s.strip() for s in args.strategies.split(",")] if args.strategies else None
    years = [int(y.strip()) for y in args.years.split(",")] if args.years else None
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None

    print()
    print("=" * 72)
    print("  JITTER TEST — Parameter Robustness Check")
    print(f"  Variants: {args.n}  |  Noise: ±{args.noise:.0%}  |  Seed: {args.seed}")
    print("=" * 72)

    base_params = load_base_params(
        from_leaderboard=args.from_leaderboard,
        config_path=args.config,
        strategy_names=strategy_names,
    )

    print(f"\n  Strategies: {list(base_params.keys())}")
    for name, params in base_params.items():
        print(f"\n  [{name}]")
        for k, v in sorted(params.items()):
            print(f"    {k}: {v}")

    report = run_jitter_test(
        base_params=base_params,
        n_variants=args.n,
        noise=args.noise,
        years=years,
        tickers=tickers,
        seed=args.seed,
    )

    print_report(report)

    if args.save:
        out_path = OUTPUT / "jitter_report.json"
        out_path.write_text(json.dumps(report, indent=2, default=str))
        print(f"\n  Report saved to {out_path}")


if __name__ == "__main__":
    main()
