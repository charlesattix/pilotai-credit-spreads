#!/usr/bin/env python3
"""
run_aggressive_optimizer.py — 500-run optimizer targeting 25-40%/yr returns.

Changes vs conservative optimizer:
  - DD target loosened to 25% (from 15%) in scoring formula
  - Focused on high-return strategy combos
  - Higher max_risk_pct exploration range
  - Output to output/leaderboard_aggressive.json

Usage:
    python3 scripts/run_aggressive_optimizer.py                  # 500 runs
    python3 scripts/run_aggressive_optimizer.py --max-runs 100   # quick test
    python3 scripts/run_aggressive_optimizer.py --dry-run        # show plan
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.optimizer import Optimizer

# ── Monkey-patch compute_score to use 25% DD target ─────────────────────────


def _aggressive_compute_score(results: dict) -> float:
    """Scoring with 25% DD target (vs 15% conservative).

    Formula: (return/40) * (25/max_dd) * consistency
    - Return target: 40% (vs 50% conservative) — rewards 25-40% configs more
    - DD target: 25% (vs 15%) — stops penalizing 15-25% DD configs
    """
    combined = results.get("combined", {})
    yearly = results.get("yearly", {})

    return_pct = combined.get("return_pct", 0)
    num_years = len(yearly) if yearly else 1
    avg_annual_return = return_pct / max(1, num_years)
    return_component = min(2.0, max(0.0, avg_annual_return / 40.0))

    max_dd = abs(combined.get("max_drawdown", -100))
    if max_dd < 0.01:
        max_dd = 0.01
    dd_component = min(2.0, 25.0 / max_dd)

    if yearly:
        years_profitable = sum(
            1 for y in yearly.values()
            if y.get("return_pct", y.get("total_pnl", 0)) > 0
        )
        consistency = years_profitable / len(yearly)
    else:
        consistency = 0.0

    score = return_component * dd_component * max(0.1, consistency)
    return round(score, 4)


Optimizer.compute_score = _aggressive_compute_score

# ── Now import and run the endless optimizer with patched scoring ────────────
# Override sys.argv to pass our desired flags, then call main()
import scripts.endless_optimizer as eo

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Aggressive 500-run optimizer")
    parser.add_argument("--max-runs", type=int, default=500)
    parser.add_argument("--strategies", default="straddle_strangle,gamma_lotto,credit_spread,iron_condor")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--phase", type=int, default=2,
                        help="Start at phase 2 (blending) since we know which strategies to combine")
    args = parser.parse_args()

    leaderboard = str(ROOT / "output" / "leaderboard_aggressive.json")

    # Build argv for endless_optimizer.main()
    sys.argv = [
        "endless_optimizer",
        "--max-runs", str(args.max_runs),
        "--strategies", args.strategies,
        "--leaderboard", leaderboard,
        "--phase", str(args.phase),
        "--report-interval", "50",
    ]
    if args.dry_run:
        sys.argv.append("--dry-run")

    print()
    print("=" * 72)
    print("  AGGRESSIVE OPTIMIZER — Targeting 25-40%/yr returns")
    print(f"  DD target: 25% (loosened from 15%)")
    print(f"  Scoring:   (return/40) * (25/max_dd) * consistency")
    print(f"  Strategies: {args.strategies}")
    print(f"  Output:    {leaderboard}")
    print(f"  Runs:      {args.max_runs}")
    print("=" * 72)

    eo.main()
