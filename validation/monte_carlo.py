"""
MonteCarloValidator — importable wrapper around run_monte_carlo.py logic.

Refactors the per-seed loop and percentile computation into a class so that
other code (CLI, robustness scorer) can call it programmatically.  The
original script is unchanged and continues to work standalone.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from validation.result_types import MCResult, SeedResult


def _percentile(data: list, p: float) -> float:
    """Simple percentile without numpy."""
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


class MonteCarloValidator:
    """Run a Monte Carlo robustness test over multiple seeds.

    Extracts the core logic from scripts/run_monte_carlo.py as a reusable
    class.  The script itself is unchanged.

    Usage::

        from validation.monte_carlo import MonteCarloValidator
        mc = MonteCarloValidator(n_seeds=20, mode='dte', dte_lo=28, dte_hi=42)
        result = mc.run(params, years=[2020, 2021, 2022, 2023, 2024, 2025])
        print(result['percentiles']['avg_return_pct']['P50'])
    """

    def __init__(
        self,
        n_seeds: int = 100,
        mode: str = "dte",
        dte_lo: int = 28,
        dte_hi: int = 42,
        use_real_data: bool = True,
        slippage_jitter: float = 0.50,
        entry_day_jitter: int = 2,
        trade_skip_pct: float = 0.15,
        credit_jitter: float = 0.10,
        run_id: Optional[str] = None,
    ) -> None:
        self.n_seeds = n_seeds
        self.mode = mode
        self.dte_lo = dte_lo
        self.dte_hi = dte_hi
        self.use_real_data = use_real_data
        self.slippage_jitter = slippage_jitter
        self.entry_day_jitter = entry_day_jitter
        self.trade_skip_pct = trade_skip_pct
        self.credit_jitter = credit_jitter
        self.run_id = run_id or f"mc_{mode}_{datetime.now().strftime('%H%M%S')}"

    def run(self, params: dict, years: List[int]) -> MCResult:
        """Run MC across all seeds and return aggregated result.

        Args:
            params: Config dict (same format as run_optimization.py params).
            years:  List of years to backtest per seed.

        Returns:
            MCResult with per-seed results + percentile distributions.
        """
        import copy

        p = copy.deepcopy(params)
        if "monte_carlo" not in p:
            p["monte_carlo"] = {}
        p["monte_carlo"]["dte_lo"] = self.dte_lo
        p["monte_carlo"]["dte_hi"] = self.dte_hi
        p["monte_carlo"]["mode"] = self.mode
        if self.mode == "full":
            p["monte_carlo"]["slippage_jitter_pct"] = self.slippage_jitter
            p["monte_carlo"]["entry_day_jitter"] = self.entry_day_jitter
            p["monte_carlo"]["trade_skip_pct"] = self.trade_skip_pct
            p["monte_carlo"]["credit_jitter"] = self.credit_jitter

        from scripts.run_optimization import run_year

        all_seeds: List[SeedResult] = []
        for seed in range(self.n_seeds):
            per_year = {}
            for year in years:
                result = run_year(
                    ticker="SPY",
                    year=year,
                    params=p,
                    use_real_data=self.use_real_data,
                    seed=seed,
                )
                per_year[year] = result

            returns = [per_year[y].get("return_pct", 0.0) for y in years]
            max_dds = [per_year[y].get("max_drawdown", 0.0) for y in years]
            trade_counts = [per_year[y].get("total_trades", 0) for y in years]
            sharpes = [per_year[y].get("sharpe_ratio", 0.0) for y in years]

            all_seeds.append(SeedResult(
                seed=seed,
                avg_return_pct=sum(returns) / len(returns) if returns else 0.0,
                worst_drawdown_pct=min(max_dds) if max_dds else 0.0,
                total_trades=sum(trade_counts),
                profitable_years=sum(1 for r in returns if r > 0),
                avg_sharpe=sum(sharpes) / len(sharpes) if sharpes else 0.0,
                per_year={str(y): per_year[y] for y in years},
            ))

        percentiles = self._compute_percentiles(all_seeds, years)

        return MCResult(
            run_id=self.run_id,
            config=params,
            n_seeds=self.n_seeds,
            years=years,
            mode=self.mode,
            seeds=all_seeds,
            percentiles=percentiles,
            per_year_p50={str(y): percentiles.get(f"year_{y}", {}).get("P50", 0.0) for y in years},
            timestamp=datetime.now().isoformat(),
        )

    @staticmethod
    def _compute_percentiles(seeds: List[SeedResult], years: List[int]) -> dict:
        pcts = [5, 25, 50, 75, 95]

        def dist(key):
            vals = [s[key] for s in seeds]
            return {f"P{p}": round(_percentile(vals, p), 2) for p in pcts}

        result = {
            "avg_return_pct": dist("avg_return_pct"),
            "worst_drawdown_pct": dist("worst_drawdown_pct"),
            "total_trades": dist("total_trades"),
            "avg_sharpe": dist("avg_sharpe"),
        }

        for y in years:
            y_returns = [s["per_year"][str(y)].get("return_pct", 0.0) for s in seeds]
            result[f"year_{y}"] = {f"P{p}": round(_percentile(y_returns, p), 2) for p in pcts}

        return result
