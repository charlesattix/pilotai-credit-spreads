"""
Optimizer — Parameter sampling, search algorithms, and scoring.

Pure Python + numpy. No scipy/optuna required.

Supports optimizing any strategy (or portfolio-level params) by sampling
from the ParamDef spaces defined in each strategy module.
"""

import random
from typing import Any, Dict, List, Optional

from strategies.base import ParamDef


class Optimizer:
    """Parameter optimizer using random search + Bayesian-lite exploitation.

    Args:
        strategy_name: If given, optimize that single strategy's params.
            If None, optimize portfolio-level params.
        param_space: Explicit param space. If None, loaded from strategy's
            get_param_space() classmethod.
        seed: Random seed for reproducibility.
    """

    def __init__(
        self,
        strategy_name: Optional[str] = None,
        param_space: Optional[List[ParamDef]] = None,
        seed: Optional[int] = None,
    ):
        self.strategy_name = strategy_name
        self._rng = random.Random(seed)

        if param_space is not None:
            self.param_space = param_space
        elif strategy_name is not None:
            from strategies import STRATEGY_REGISTRY
            cls = STRATEGY_REGISTRY[strategy_name]
            self.param_space = cls.get_param_space()
        else:
            self.param_space = []

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def sample_params(self, param_space: Optional[List[ParamDef]] = None) -> Dict[str, Any]:
        """Sample random params from the ParamDef space.

        Sampling logic per ParamDef type:
        - float: uniform in [low, high], snap to step
        - int:   randint in [low, high], snap to step
        - bool:  random choice True/False
        - choice: random choice from choices list
        """
        space = param_space or self.param_space
        params: Dict[str, Any] = {}

        for p in space:
            params[p.name] = self._sample_one(p)

        return params

    def _sample_one(self, p: ParamDef) -> Any:
        """Sample a single param value according to its type."""
        if p.param_type == "float":
            low = p.low if p.low is not None else p.default * 0.5
            high = p.high if p.high is not None else p.default * 2.0
            val = self._rng.uniform(low, high)
            if p.step:
                val = round(round(val / p.step) * p.step, 10)
            return round(val, 6)

        elif p.param_type == "int":
            low = int(p.low if p.low is not None else p.default * 0.5)
            high = int(p.high if p.high is not None else p.default * 2.0)
            val = self._rng.randint(low, high)
            if p.step and p.step > 1:
                val = round(val / p.step) * p.step
                val = max(low, min(high, val))
            return int(val)

        elif p.param_type == "bool":
            return self._rng.choice([True, False])

        elif p.param_type == "choice":
            if p.choices:
                return self._rng.choice(p.choices)
            return p.default

        # Fallback
        return p.default

    def sample_near_best(
        self,
        best_params: Dict[str, Any],
        param_space: Optional[List[ParamDef]] = None,
        noise: float = 0.15,
    ) -> Dict[str, Any]:
        """Bayesian-lite: perturb best known params by +/-noise fraction.

        Numeric params get Gaussian noise (clipped to valid range).
        Choice/bool params have a small chance of random flip.
        """
        space = param_space or self.param_space
        params: Dict[str, Any] = {}

        for p in space:
            base_val = best_params.get(p.name, p.default)

            if p.param_type == "float":
                low = p.low if p.low is not None else p.default * 0.5
                high = p.high if p.high is not None else p.default * 2.0
                if isinstance(base_val, (int, float)):
                    delta = abs(base_val) * noise if base_val != 0 else (high - low) * noise
                    val = base_val + self._rng.gauss(0, delta)
                    val = max(low, min(high, val))
                    if p.step:
                        val = round(round(val / p.step) * p.step, 10)
                    params[p.name] = round(val, 6)
                else:
                    params[p.name] = self._sample_one(p)

            elif p.param_type == "int":
                low = int(p.low if p.low is not None else p.default * 0.5)
                high = int(p.high if p.high is not None else p.default * 2.0)
                if isinstance(base_val, (int, float)):
                    delta = max(1, abs(base_val) * noise)
                    val = base_val + self._rng.gauss(0, delta)
                    val = max(low, min(high, int(round(val))))
                    if p.step and p.step > 1:
                        val = round(val / p.step) * p.step
                        val = max(low, min(high, val))
                    params[p.name] = int(val)
                else:
                    params[p.name] = self._sample_one(p)

            elif p.param_type == "bool":
                # 15% chance of flipping
                if self._rng.random() < 0.15:
                    params[p.name] = not base_val
                else:
                    params[p.name] = base_val

            elif p.param_type == "choice":
                # 15% chance of random choice
                if self._rng.random() < 0.15 and p.choices:
                    params[p.name] = self._rng.choice(p.choices)
                else:
                    params[p.name] = base_val

            else:
                params[p.name] = base_val

        return params

    def suggest(self, history: List[Dict]) -> Dict[str, Any]:
        """Pick next params to try based on history of (params, score) pairs.

        Strategy:
        - First 10 runs: pure random sampling (explore)
        - After 10: 70% perturb best, 30% random (exploit + explore)

        Each history entry should have keys: "params" (dict) and "score" (float).
        """
        if len(history) < 10:
            return self.sample_params()

        # Find best params so far
        best = max(history, key=lambda h: h.get("score", 0))
        best_params = best["params"]

        if self._rng.random() < 0.70:
            # Exploit: perturb best
            return self.sample_near_best(best_params)
        else:
            # Explore: random
            return self.sample_params()

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def compute_score(results: Dict) -> float:
        """MASTERPLAN composite: (return/200) * (15/max_dd) * consistency.

        Components:
        - return_component: yearly avg return / 200 (target is 200% annual)
        - drawdown_component: 15 / abs(max_drawdown) (target is -15% max DD)
        - consistency: fraction of years profitable

        All clipped to [0, 2] to prevent blow-up.

        Args:
            results: Output from PortfolioBacktester.run() — expects
                "combined" and "yearly" keys.

        Returns:
            Composite score (higher = better). Typical range: 0 to ~1.0.
        """
        combined = results.get("combined", {})
        yearly = results.get("yearly", {})

        # Return component
        return_pct = combined.get("return_pct", 0)
        num_years = len(yearly) if yearly else 1
        avg_annual_return = return_pct / max(1, num_years)
        return_component = min(2.0, max(0.0, avg_annual_return / 200.0))

        # Drawdown component
        max_dd = abs(combined.get("max_drawdown", -100))
        if max_dd < 0.01:
            max_dd = 0.01  # prevent division by zero
        dd_component = min(2.0, 15.0 / max_dd)

        # Consistency: fraction of years profitable
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
