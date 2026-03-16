"""
TypedDicts for validation results — no logic, pure data shapes.
"""

from typing import Dict, List, Optional
try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict  # Python 3.7 fallback


class SeedResult(TypedDict):
    seed: int
    avg_return_pct: float
    worst_drawdown_pct: float
    total_trades: int
    profitable_years: int
    avg_sharpe: float
    per_year: Dict[str, dict]


class MCResult(TypedDict):
    run_id: str
    config: dict
    n_seeds: int
    years: List[int]
    mode: str                        # 'dte' or 'full'
    seeds: List[SeedResult]
    percentiles: Dict[str, Dict[str, float]]  # metric → {P5, P25, P50, P75, P95}
    per_year_p50: Dict[str, float]   # year_str → P50 return
    timestamp: str


class FoldResult(TypedDict):
    train_years: List[str]
    test_year: str
    train_avg_return: float
    test_return: float
    ratio: float
    passed: bool


class WalkForwardResult(TypedDict):
    folds: List[FoldResult]
    pass_rate: float       # fraction of folds that passed
    consistent: bool       # True if pass_rate >= 2/3


class RobustnessResult(TypedDict):
    overfit_score: float
    verdict: str           # ROBUST / SUSPECT / OVERFIT
    slippage_1x: float
    slippage_2x: float
    slippage_3x: float
    mc_p50_return: float
    mc_p5_return: float
    wf_pass_rate: float
    checks: dict           # raw check results from validate_params
