"""
python -m backtest — CLI entry point for the modular backtesting framework.

Subcommands:
    run       Run a backtest from a config file
    validate  Run MC + walk-forward + robustness checks
    compare   Side-by-side comparison of experiments from leaderboard
    report    Generate an HTML report for a leaderboard entry

Examples:
    python -m backtest run --config configs/exp_213_champion_maxc100.json --years 2020-2025
    python -m backtest validate --config configs/exp_213_champion_maxc100.json --mc-seeds 10
    python -m backtest compare --experiments exp_213 exp_224
    python -m backtest report --run-id exp_213 --output output/exp_213.html
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# Subcommand: run
# ---------------------------------------------------------------------------

def cmd_run(args) -> None:
    """Run a backtest and print per-year results."""
    import time
    from scripts.run_optimization import run_all_years, compute_summary, print_results_table

    params = _load_config(args.config)
    years = _parse_years(args.years)
    use_real = not args.heuristic

    print(f"\n  Config  : {args.config}")
    print(f"  Ticker  : {args.ticker}")
    print(f"  Years   : {years}")
    print(f"  Data    : {'heuristic' if not use_real else 'real (Polygon)'}\n")

    t0 = time.time()
    results = run_all_years(params, years, use_real, ticker=args.ticker)
    summary = compute_summary(results)
    elapsed = time.time() - t0

    print_results_table(run_id=Path(args.config).stem, params=params,
                        results_by_year=results, summary=summary)
    print(f"\n  Elapsed: {elapsed:.0f}s")

    if args.save:
        from reporting.leaderboard import LeaderboardManager
        from datetime import datetime
        entry = {
            "run_id": Path(args.config).stem,
            "timestamp": datetime.now().isoformat(),
            "params": params,
            "summary": summary,
            "per_year": results,
        }
        lb = LeaderboardManager()
        lb.append(entry)
        print(f"  Saved to leaderboard: {lb.path}")


# ---------------------------------------------------------------------------
# Subcommand: validate
# ---------------------------------------------------------------------------

def cmd_validate(args) -> None:
    """Run MC + walk-forward + robustness checks."""
    from scripts.run_optimization import run_all_years
    from validation.robustness import RobustnessScorer
    from validation.walk_forward import WalkForwardValidator

    params = _load_config(args.config)
    years = _parse_years(args.years)
    use_real = not args.heuristic

    print(f"\n  Config  : {args.config}")
    print(f"  Years   : {years}")
    print(f"  MC seeds: {args.mc_seeds}")
    print(f"  Data    : {'heuristic' if not use_real else 'real (Polygon)'}\n")

    # Run base backtest first
    print("  [1/3] Running base backtest...")
    results = run_all_years(params, years, use_real, ticker=args.ticker)

    # Walk-forward
    print("  [2/3] Walk-forward validation...")
    wfv = WalkForwardValidator()
    wf_result = wfv.run(results)
    print(f"    Pass rate: {wf_result['pass_rate']:.1%}  "
          f"({'CONSISTENT' if wf_result['consistent'] else 'INCONSISTENT'})")
    for fold in wf_result["folds"]:
        status = "✓" if fold["passed"] else "✗"
        print(f"    {status} Train {fold['train_years']} → Test {fold['test_year']}: "
              f"train_avg={fold['train_avg_return']:+.1f}%  "
              f"test={fold['test_return']:+.1f}%  ratio={fold['ratio']:.2f}")

    # Robustness (with optional MC)
    print(f"  [3/3] Robustness scoring (MC seeds={args.mc_seeds})...")
    scorer = RobustnessScorer(run_mc=args.mc_seeds > 0, mc_seeds=args.mc_seeds)
    rob = scorer.compute(params, results, years, use_real_data=use_real)

    print(f"\n  Overfit score : {rob['overfit_score']:.3f}  [{rob['verdict']}]")
    print(f"  WF pass rate  : {rob['wf_pass_rate']:.1%}")
    if args.mc_seeds > 0:
        print(f"  MC P50 return : {rob['mc_p50_return']:+.1f}%")
        print(f"  MC P5  return : {rob['mc_p5_return']:+.1f}%")
    print()


# ---------------------------------------------------------------------------
# Subcommand: compare
# ---------------------------------------------------------------------------

def cmd_compare(args) -> None:
    """Print side-by-side comparison table from leaderboard."""
    from reporting.compare import ExperimentComparison

    comp = ExperimentComparison()
    years = _parse_years(args.years) if args.years else None
    table = comp.compare(args.experiments, years=[str(y) for y in years] if years else None)
    comp.print_table(table)


# ---------------------------------------------------------------------------
# Subcommand: report
# ---------------------------------------------------------------------------

def cmd_report(args) -> None:
    """Generate an HTML report for a leaderboard entry."""
    from reporting.leaderboard import LeaderboardManager
    from reporting.html_report import HTMLReportGenerator

    lb = LeaderboardManager()
    entry = lb.get(args.run_id)
    if entry is None:
        print(f"ERROR: run_id '{args.run_id}' not found in leaderboard.")
        sys.exit(1)

    gen = HTMLReportGenerator()
    out = gen.generate(entry, args.output)
    print(f"  Report written → {out}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _parse_years(years_str: str) -> list:
    """Parse '2020-2025' or '2020,2021,2022' into a list of ints."""
    if "-" in years_str and "," not in years_str:
        parts = years_str.split("-")
        lo, hi = int(parts[0]), int(parts[1])
        return list(range(lo, hi + 1))
    return [int(y) for y in years_str.split(",")]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="python -m backtest",
        description="Modular backtesting framework CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- run ---
    p_run = sub.add_parser("run", help="Run a backtest from a config file")
    p_run.add_argument("--config", required=True, help="Config JSON file path")
    p_run.add_argument("--years", default="2020-2025",
                       help="Years range '2020-2025' or list '2020,2021'")
    p_run.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY)")
    p_run.add_argument("--heuristic", action="store_true",
                       help="Use heuristic pricing (fast, no Polygon)")
    p_run.add_argument("--save", action="store_true",
                       help="Save result to output/leaderboard.json")
    p_run.set_defaults(func=cmd_run)

    # --- validate ---
    p_val = sub.add_parser("validate", help="MC + walk-forward + robustness checks")
    p_val.add_argument("--config", required=True, help="Config JSON file path")
    p_val.add_argument("--years", default="2020-2025")
    p_val.add_argument("--ticker", default="SPY")
    p_val.add_argument("--heuristic", action="store_true")
    p_val.add_argument("--mc-seeds", type=int, default=10,
                       help="Number of MC seeds (0 = skip MC, default: 10)")
    p_val.set_defaults(func=cmd_validate)

    # --- compare ---
    p_cmp = sub.add_parser("compare", help="Side-by-side experiment comparison")
    p_cmp.add_argument("--experiments", nargs="+", required=True,
                       help="Two or more run_id strings to compare")
    p_cmp.add_argument("--years", default=None,
                       help="Year range or list (default: all in leaderboard)")
    p_cmp.set_defaults(func=cmd_compare)

    # --- report ---
    p_rep = sub.add_parser("report", help="Generate HTML report from leaderboard entry")
    p_rep.add_argument("--run-id", required=True, help="run_id to look up in leaderboard")
    p_rep.add_argument("--output", required=True, help="Output HTML file path")
    p_rep.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
