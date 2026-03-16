"""
RobustnessScorer — aggregate overfit score + slippage + walk-forward checks.

Wraps validate_params.py's check functions plus the WalkForwardValidator and
(optionally) a quick MonteCarloValidator run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from validation.result_types import RobustnessResult
from validation.walk_forward import WalkForwardValidator


class RobustnessScorer:
    """Compute an overfit score and slippage sensitivity for a completed backtest.

    Usage::

        from validation.robustness import RobustnessScorer
        scorer = RobustnessScorer()
        result = scorer.compute(params, results_by_year, years, use_real_data=True)
        print(result['overfit_score'], result['verdict'])
    """

    def __init__(
        self,
        run_mc: bool = False,
        mc_seeds: int = 20,
        ticker: str = "SPY",
    ) -> None:
        """
        Args:
            run_mc:    Whether to run a quick Monte Carlo for mc_p50_return.
            mc_seeds:  Number of MC seeds (only used when run_mc=True).
            ticker:    Underlying ticker for slippage re-runs.
        """
        self.run_mc = run_mc
        self.mc_seeds = mc_seeds
        self.ticker = ticker

    def compute(
        self,
        params: dict,
        results_by_year: Dict[str, dict],
        years: List[int],
        use_real_data: bool = True,
    ) -> RobustnessResult:
        """Run all checks and return a RobustnessResult.

        Args:
            params:          Config params dict.
            results_by_year: Pre-run year results {year_str: result_dict}.
            years:           List of years that were run.
            use_real_data:   Whether to use real Polygon data for slippage re-runs.

        Returns:
            RobustnessResult with overfit_score, verdict, and individual metrics.
        """
        from scripts.validate_params import validate_params

        vp = validate_params(
            params=params,
            results_by_year=results_by_year,
            years=[str(y) for y in years],
            use_real=use_real_data,
            ticker=self.ticker,
        )

        overfit_score = vp.get("overfit_score", 0.0)
        verdict = vp.get("verdict", "UNKNOWN")

        # Walk-forward (already computed inside validate_params but we surface it)
        wfv = WalkForwardValidator()
        wf_result = wfv.run(results_by_year)

        # Slippage sensitivity — extract from validate_params check_c results
        slippage_1x = _avg_return(results_by_year)
        slippage_2x = _extract_slippage_return(vp, "slippage_2x")
        slippage_3x = _extract_slippage_return(vp, "slippage_3x")

        # Optional quick Monte Carlo
        mc_p50 = 0.0
        mc_p5 = 0.0
        if self.run_mc:
            from validation.monte_carlo import MonteCarloValidator
            mc = MonteCarloValidator(n_seeds=self.mc_seeds, mode="dte", use_real_data=use_real_data)
            mc_result = mc.run(params, years)
            mc_p50 = mc_result["percentiles"]["avg_return_pct"].get("P50", 0.0)
            mc_p5 = mc_result["percentiles"]["avg_return_pct"].get("P5", 0.0)

        return RobustnessResult(
            overfit_score=overfit_score,
            verdict=verdict,
            slippage_1x=round(slippage_1x, 2),
            slippage_2x=round(slippage_2x, 2),
            slippage_3x=round(slippage_3x, 2),
            mc_p50_return=round(mc_p50, 2),
            mc_p5_return=round(mc_p5, 2),
            wf_pass_rate=wf_result["pass_rate"],
            checks=vp,
        )


def _avg_return(results_by_year: Dict[str, dict]) -> float:
    rets = [r.get("return_pct", 0.0) for r in results_by_year.values() if "error" not in r]
    return sum(rets) / len(rets) if rets else 0.0


def _extract_slippage_return(vp: dict, key: str) -> float:
    """Extract slippage sensitivity return from validate_params output."""
    checks = vp.get("checks", {})
    if "C_sensitivity" in checks:
        return checks["C_sensitivity"].get(key, 0.0)
    return 0.0
