"""
ExperimentComparison — side-by-side year-by-year comparison of experiments.

Refactored from scripts/compare_experiments.py logic.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from reporting.leaderboard import LeaderboardManager

# Years to show in the comparison table
DEFAULT_YEARS = ["2020", "2021", "2022", "2023", "2024", "2025"]


class ExperimentComparison:
    """Compare multiple experiments side-by-side.

    Usage::

        comp = ExperimentComparison()
        table = comp.compare(["exp_213", "exp_224"])
        comp.print_table(table)
    """

    def __init__(self, leaderboard_path: str = "output/leaderboard.json") -> None:
        self._lb = LeaderboardManager(leaderboard_path)

    def compare(
        self,
        exp_ids: List[str],
        years: Optional[List[str]] = None,
    ) -> Dict:
        """Build a side-by-side comparison dict.

        Args:
            exp_ids: List of run_id strings to compare.
            years:   Years to include (default: 2020–2025).

        Returns:
            Dict with 'experiments' list and 'years' list.
        """
        years = years or DEFAULT_YEARS
        experiments = []
        for eid in exp_ids:
            entry = self._lb.get(eid)
            if entry is None:
                experiments.append({"run_id": eid, "error": "not found in leaderboard"})
                continue
            per_year = entry.get("per_year", {})
            summary = entry.get("summary", {})
            exp_data = {
                "run_id": eid,
                "summary": summary,
                "overfit_score": entry.get("overfit_score"),
                "verdict": entry.get("verdict"),
                "per_year": {
                    y: {
                        "return_pct": per_year.get(y, {}).get("return_pct", None),
                        "max_drawdown": per_year.get(y, {}).get("max_drawdown", None),
                        "total_trades": per_year.get(y, {}).get("total_trades", None),
                    }
                    for y in years
                },
            }
            experiments.append(exp_data)

        return {"experiments": experiments, "years": years}

    def print_table(self, comparison: Dict) -> None:
        """Print an ASCII comparison table to stdout."""
        years = comparison["years"]
        experiments = comparison["experiments"]

        col_w = 12
        id_w = 20

        # Header
        header = f"{'Run ID':<{id_w}}"
        for y in years:
            header += f"  {y:>{col_w}}"
        header += f"  {'Avg':>{col_w}}  {'WorstDD':>{col_w}}  {'Score':>{8}}"
        sep = "─" * len(header)

        print()
        print(sep)
        print(header)
        print(sep)

        for exp in experiments:
            if "error" in exp:
                print(f"{exp['run_id']:<{id_w}}  ERROR: {exp['error']}")
                continue

            row = f"{exp['run_id']:<{id_w}}"
            for y in years:
                ret = exp["per_year"][y].get("return_pct")
                cell = f"{ret:+.1f}%" if ret is not None else "    N/A"
                row += f"  {cell:>{col_w}}"

            avg = exp["summary"].get("avg_return", 0)
            worst_dd = exp["summary"].get("worst_dd", 0)
            score = exp.get("overfit_score") or 0
            row += f"  {avg:>+{col_w}.1f}%  {worst_dd:>{col_w}.1f}%  {score:>{8}.3f}"
            print(row)

        print(sep)
        print()
