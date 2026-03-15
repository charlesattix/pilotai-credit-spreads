#!/usr/bin/env python3
"""
run_monte_carlo.py — Monte Carlo DTE Randomization Runner

Purpose:
    Removes the DTE=35 cliff by running the full 6-year backtest 100 times,
    each with a different random seed. On every trading day, the entry logic
    samples DTE from U(dte_lo, dte_hi) instead of using the fixed target_dte.

    Carlos's directive: "If median drops from 66% to 20%, then 20% IS THE REAL EDGE."

Usage:
    python3 scripts/run_monte_carlo.py --config configs/exp_059_friday_ic_risk10.json
    python3 scripts/run_monte_carlo.py --config configs/exp_059_friday_ic_risk10.json --n-seeds 20 --years 2022,2023

Output:
    output/mc_{run_id}.json  — full per-seed results
    Prints percentile table: P5, P25, P50, P75, P95 for avg return and max DD
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "output"

# Load .env so POLYGON_API_KEY is available when running via Claude or cron
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
OUTPUT.mkdir(exist_ok=True)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mc")


def _load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return json.load(f)


def _build_config(params: dict) -> dict:
    """Mirror of run_optimization.py's _build_config."""
    from scripts.run_optimization import _build_config as _bc
    return _bc(params)


def run_one_seed(seed: int, params: dict, years: list, use_real_data: bool) -> dict:
    """Run the full multi-year backtest with this seed, return per-year results."""
    from scripts.run_optimization import run_year
    per_year = {}
    for year in years:
        result = run_year(
            ticker="SPY",
            year=year,
            params=params,
            use_real_data=use_real_data,
            seed=seed,
        )
        per_year[year] = result
    return per_year


def _percentile(data: list, p: float) -> float:
    """Simple percentile without numpy dependency."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (len(sorted_data) - 1) * p / 100.0
    lo = int(idx)
    hi = lo + 1
    if hi >= len(sorted_data):
        return sorted_data[-1]
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo DTE randomization runner")
    parser.add_argument("--config", required=True, help="Config JSON file")
    parser.add_argument("--n-seeds", type=int, default=100, help="Number of seeds (default: 100)")
    parser.add_argument("--years", default="2020,2021,2022,2023,2024,2025",
                        help="Comma-separated years (default: 2020-2025)")
    parser.add_argument("--heuristic", action="store_true", help="Use heuristic mode (fast, no Polygon)")
    parser.add_argument("--run-id", default=None, help="Custom run ID for output file")
    parser.add_argument("--dte-lo", type=int, default=28, help="DTE range lower bound (default: 28)")
    parser.add_argument("--dte-hi", type=int, default=42, help="DTE range upper bound (default: 42)")
    args = parser.parse_args()

    years = [int(y) for y in args.years.split(",")]
    params = _load_config(args.config)

    # Inject Monte Carlo DTE range into backtest config
    if "monte_carlo" not in params:
        params["monte_carlo"] = {}
    params["monte_carlo"]["dte_lo"] = args.dte_lo
    params["monte_carlo"]["dte_hi"] = args.dte_hi

    use_real_data = not args.heuristic

    config_name = Path(args.config).stem
    run_id = args.run_id or f"mc_{config_name}_seeds{args.n_seeds}_{datetime.now().strftime('%H%M')}"

    print(f"""
════════════════════════════════════════════════════════════════════════
  MONTE CARLO DTE RANDOMIZATION — {run_id}
  Config  : {args.config}
  Seeds   : 0 to {args.n_seeds - 1} (n={args.n_seeds})
  DTE     : U({args.dte_lo}, {args.dte_hi}) sampled per trading day
  Years   : {years}
  Mode    : {'heuristic (fast)' if not use_real_data else 'real data (Polygon)'}
════════════════════════════════════════════════════════════════════════
""")

    all_results = []
    t_start = time.time()

    for seed in range(args.n_seeds):
        t_seed = time.time()
        per_year = run_one_seed(seed, params, years, use_real_data)

        # Compute summary stats for this seed
        returns = [per_year[y].get("return_pct", 0.0) for y in years]
        max_dds = [per_year[y].get("max_drawdown", 0.0) for y in years]
        trade_counts = [per_year[y].get("total_trades", 0) for y in years]
        avg_return = sum(returns) / len(returns) if returns else 0.0
        worst_dd = min(max_dds) if max_dds else 0.0
        total_trades = sum(trade_counts)
        profitable_years = sum(1 for r in returns if r > 0)

        seed_result = {
            "seed": seed,
            "avg_return_pct": avg_return,
            "worst_drawdown_pct": worst_dd,
            "total_trades": total_trades,
            "profitable_years": profitable_years,
            "per_year": {str(y): per_year[y] for y in years},
        }
        all_results.append(seed_result)

        elapsed = time.time() - t_seed
        print(f"  Seed {seed:3d}:  avg={avg_return:+.1f}%  trades={total_trades:3d}  "
              f"worst_DD={worst_dd:.1f}%  ({elapsed:.0f}s)")

    # ── Aggregate statistics ─────────────────────────────────────────────────
    avg_returns = [r["avg_return_pct"] for r in all_results]
    worst_dds = [r["worst_drawdown_pct"] for r in all_results]
    total_trades_list = [r["total_trades"] for r in all_results]

    percentiles = [5, 25, 50, 75, 95]
    ret_pcts = {p: _percentile(avg_returns, p) for p in percentiles}
    dd_pcts = {p: _percentile(worst_dds, p) for p in percentiles}
    trade_pcts = {p: _percentile(total_trades_list, p) for p in percentiles}

    # Per-year percentiles
    per_year_pcts = {}
    for y in years:
        y_returns = [r["per_year"][str(y)].get("return_pct", 0.0) for r in all_results]
        per_year_pcts[y] = {p: _percentile(y_returns, p) for p in percentiles}

    worst_dd_any = min(worst_dds)
    sum(1 for r in avg_returns if r > 0)
    median_return = ret_pcts[50]

    total_elapsed = time.time() - t_start
    print(f"""
════════════════════════════════════════════════════════════════════════
  MONTE CARLO RESULTS — {run_id}
  DTE Randomization: U({args.dte_lo}, {args.dte_hi})  |  {args.n_seeds} seeds
────────────────────────────────────────────────────────────────────────
  AVG ANNUAL RETURN DISTRIBUTION:
    P5  (worst 5%):  {ret_pcts[5]:+.1f}%
    P25 (lower):     {ret_pcts[25]:+.1f}%
    P50 (MEDIAN):    {ret_pcts[50]:+.1f}%   ← This is the REAL edge
    P75 (upper):     {ret_pcts[75]:+.1f}%
    P95 (best 5%):   {ret_pcts[95]:+.1f}%
────────────────────────────────────────────────────────────────────────
  WORST-YEAR DRAWDOWN DISTRIBUTION:
    P5  (worst 5%):  {dd_pcts[5]:.1f}%
    P25 (lower):     {dd_pcts[25]:.1f}%
    P50 (MEDIAN):    {dd_pcts[50]:.1f}%
    P75 (upper):     {dd_pcts[75]:.1f}%
    P95 (best 5%):   {dd_pcts[95]:.1f}%
  Worst-case DD across ALL {args.n_seeds} seeds:  {worst_dd_any:.1f}%
────────────────────────────────────────────────────────────────────────
  PER-YEAR MEDIAN RETURNS (P50):""")

    for y in years:
        p = per_year_pcts[y]
        print(f"    {y}:  P5={p[5]:+.1f}%  P25={p[25]:+.1f}%  P50={p[50]:+.1f}%  P75={p[75]:+.1f}%  P95={p[95]:+.1f}%")

    seeds_positive = sum(1 for r in avg_returns if r > 0)
    print(f"""────────────────────────────────────────────────────────────────────
  Seeds with positive avg return:  {seeds_positive}/{args.n_seeds} ({100*seeds_positive/args.n_seeds:.0f}%)
  Elapsed: {total_elapsed/60:.1f} min
════════════════════════════════════════════════════════════════════════

  {'✅ EDGE CONFIRMED' if median_return > 20 else '⚠️  EDGE QUESTIONABLE' if median_return > 0 else '❌ NO EDGE'}: Median return = {median_return:+.1f}%
  {'✅ DRAWDOWN OK' if dd_pcts[50] > -50 else '❌ DRAWDOWN FAILS'}: Median worst-DD = {dd_pcts[50]:.1f}%
""")

    # ── Save results ──────────────────────────────────────────────────────────
    output = {
        "run_id": run_id,
        "config": args.config,
        "n_seeds": args.n_seeds,
        "dte_lo": args.dte_lo,
        "dte_hi": args.dte_hi,
        "years": years,
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "avg_return_pct": {f"P{p}": ret_pcts[p] for p in percentiles},
            "worst_drawdown_pct": {f"P{p}": dd_pcts[p] for p in percentiles},
            "total_trades": {f"P{p}": trade_pcts[p] for p in percentiles},
            "worst_dd_any_seed": worst_dd_any,
            "seeds_positive_pct": 100 * seeds_positive / args.n_seeds,
            "per_year_p50": {str(y): per_year_pcts[y][50] for y in years},
        },
        "all_seeds": all_results,
    }

    out_path = OUTPUT / f"{run_id}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Results saved → {out_path}")


if __name__ == "__main__":
    main()
