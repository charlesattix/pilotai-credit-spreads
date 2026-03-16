"""
WalkForwardValidator — rolling walk-forward validation.

Refactors check_b_walkforward from scripts/validate_params.py as a
standalone class.  The original script is unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from validation.result_types import FoldResult, WalkForwardResult

# Default fold structure: growing train window, 1-year test
DEFAULT_FOLDS = [
    {"train": ["2020", "2021", "2022"],                      "test": "2023"},
    {"train": ["2020", "2021", "2022", "2023"],              "test": "2024"},
    {"train": ["2020", "2021", "2022", "2023", "2024"],      "test": "2025"},
]


class WalkForwardValidator:
    """Rolling walk-forward: check that each test year is ≥50% of train avg.

    Usage::

        from validation.walk_forward import WalkForwardValidator
        wfv = WalkForwardValidator()
        result = wfv.run(results_by_year)
        print(result['consistent'], result['pass_rate'])
    """

    def __init__(self, folds: List[dict] | None = None, pass_threshold: float = 0.50) -> None:
        """
        Args:
            folds: List of {train: [year_str, ...], test: year_str} dicts.
                   Defaults to the 3-fold structure matching validate_params.py.
            pass_threshold: Minimum ratio of test/train_avg to pass a fold.
        """
        self.folds = folds or DEFAULT_FOLDS
        self.pass_threshold = pass_threshold

    def run(self, results_by_year: Dict[str, dict]) -> WalkForwardResult:
        """Compute walk-forward result from pre-run year results.

        Args:
            results_by_year: {year_str: result_dict} — same format as
                             run_optimization.run_all_years() output.

        Returns:
            WalkForwardResult with fold details and pass_rate.
        """
        fold_results: List[FoldResult] = []

        for fold in self.folds:
            train_years = fold["train"]
            test_year = fold["test"]

            if test_year not in results_by_year or "error" in results_by_year.get(test_year, {}):
                continue

            train_rets = [
                results_by_year[y]["return_pct"]
                for y in train_years
                if y in results_by_year and "error" not in results_by_year[y]
            ]
            if not train_rets:
                continue

            train_avg = sum(train_rets) / len(train_rets)
            test_ret = results_by_year[test_year]["return_pct"]

            if train_avg <= 0:
                ratio = 1.0 if test_ret >= train_avg else 0.0
            else:
                ratio = min(1.0, max(0.0, test_ret / train_avg))

            passed = ratio >= self.pass_threshold

            fold_results.append(FoldResult(
                train_years=train_years,
                test_year=test_year,
                train_avg_return=round(train_avg, 2),
                test_return=round(test_ret, 2),
                ratio=round(ratio, 3),
                passed=passed,
            ))

        pass_count = sum(1 for f in fold_results if f["passed"])
        total = len(fold_results)
        pass_rate = pass_count / total if total > 0 else 0.0
        consistent = pass_rate >= (2 / 3)

        return WalkForwardResult(
            folds=fold_results,
            pass_rate=round(pass_rate, 3),
            consistent=consistent,
        )
