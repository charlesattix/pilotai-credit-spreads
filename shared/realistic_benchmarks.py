"""
Reference benchmarks for credit spread strategy realism checks.

Sources:
- Published credit spread strategy returns: CBOE BuyWrite/PutWrite indices, academic studies
- Iron condor benchmarks: industry practitioner research (tastytrade, CBOE)
- Sharpe ratio ceiling: options selling theory (Harvey & Siddique, Deng 2020)
- Leverage: Reg T margin rules for defined-risk spreads at US brokers
"""

from dataclasses import dataclass
from typing import List

# ---------------------------------------------------------------------------
# Published benchmark ranges
# ---------------------------------------------------------------------------

# Annual return range for mechanical credit spread strategies (no leverage, $5-wide, SPY)
CREDIT_SPREAD_ANNUAL_RETURN_PCT = (8.0, 35.0)   # (pessimistic, optimistic) %

# Annual return range for mechanical iron condor strategies
IRON_CONDOR_ANNUAL_RETURN_PCT = (12.0, 45.0)   # (pessimistic, optimistic) %

# Realistic Sharpe ratio ceiling for options-selling strategies
# Options premium selling has positive expected value but fat-tail risk.
# Sharpe > 2.0 over many years is extraordinary; > 3.0 is almost certainly overfit or bugged.
SHARPE_RATIO_REALISTIC_MAX = 2.0
SHARPE_RATIO_FANTASY_THRESHOLD = 3.5

# Default commission per contract (matches run_optimization.py hardcoded value)
COMMISSION_PER_CONTRACT_DEFAULT = 0.65

# Leverage ceilings (max_loss_exposure / starting_capital)
LEVERAGE_REALISTIC_MAX = 3.0    # 3x: aggressive but defensible
LEVERAGE_WARNING_THRESHOLD = 1.5  # 1.5x: typical for a managed account

# Win rate ceiling for a mechanical strategy (not 1-DTE scalping)
WIN_RATE_REALISTIC_MAX_PCT = 90.0  # 90%+ is suspicious unless very tight strikes
WIN_RATE_FANTASY_THRESHOLD_PCT = 98.0  # 98%+ in real mode = data error

# Volume feasibility: typical daily open interest for 3% OTM SPY puts (single expiry)
# This is conservative — liquid strikes can do 5,000–10,000 contracts/day
SPY_OTM_DAILY_VOLUME_CONSERVATIVE = 200
SPY_OTM_DAILY_VOLUME_TYPICAL = 2000

# Max contracts before meaningful market impact (~5-10% of daily volume)
CONTRACTS_MARKET_IMPACT_THRESHOLD = 100  # above this, slippage model breaks down
CONTRACTS_VOLUME_INFEASIBLE = 500        # above this, fills are almost certainly impossible


# ---------------------------------------------------------------------------
# Grade thresholds (based on deviation from realistic benchmarks)
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkResult:
    grade: str           # "REALISTIC", "OPTIMISTIC", "FANTASY"
    avg_return_pct: float
    benchmark_ceiling: float
    deviation_factor: float   # avg_return / benchmark_ceiling
    message: str
    checks: List[str]


def grade_annual_returns(avg_return_pct: float, has_iron_condors: bool = False) -> BenchmarkResult:
    """Grade an average annual return against published benchmarks.

    Returns REALISTIC / OPTIMISTIC / FANTASY with deviation factor and message.
    """
    ceiling = IRON_CONDOR_ANNUAL_RETURN_PCT[1] if has_iron_condors else CREDIT_SPREAD_ANNUAL_RETURN_PCT[1]
    floor = IRON_CONDOR_ANNUAL_RETURN_PCT[0] if has_iron_condors else CREDIT_SPREAD_ANNUAL_RETURN_PCT[0]
    strat_name = "iron condor" if has_iron_condors else "credit spread"

    deviation = avg_return_pct / ceiling if ceiling != 0 else 999.0

    checks = [
        f"Benchmark for {strat_name} strategy: {floor}–{ceiling}% annual",
        f"Backtest average: {avg_return_pct:.1f}%",
        f"Deviation factor vs ceiling: {deviation:.1f}x",
    ]

    if avg_return_pct <= ceiling:
        grade = "REALISTIC"
        message = f"Average return {avg_return_pct:.1f}% is within published {strat_name} benchmark range."
    elif avg_return_pct <= ceiling * 3:
        grade = "OPTIMISTIC"
        message = (
            f"Average return {avg_return_pct:.1f}% is {deviation:.1f}x the benchmark ceiling. "
            f"Possible with favorable conditions but requires verification."
        )
    else:
        grade = "FANTASY"
        message = (
            f"Average return {avg_return_pct:.1f}% is {deviation:.1f}x the benchmark ceiling. "
            f"This is NOT achievable with a real credit spread strategy at any broker. "
            f"Commission bug, margin bug, or leverage error is almost certainly present."
        )

    return BenchmarkResult(
        grade=grade,
        avg_return_pct=avg_return_pct,
        benchmark_ceiling=ceiling,
        deviation_factor=deviation,
        message=message,
        checks=checks,
    )


def compute_leverage_ratio(
    max_positions: int,
    max_contracts: int,
    spread_width: float,
    starting_capital: float,
) -> float:
    """Compute worst-case leverage ratio: (max total margin required) / starting_capital.

    For defined-risk spreads, margin = spread_width × 100 × contracts per position.
    """
    if starting_capital <= 0:
        return float("inf")
    max_margin = max_positions * max_contracts * spread_width * 100
    return max_margin / starting_capital


def is_leverage_realistic(leverage: float) -> tuple:
    """Return (pass: bool, label: str) for a leverage ratio."""
    if leverage <= LEVERAGE_WARNING_THRESHOLD:
        return True, "OK"
    elif leverage <= LEVERAGE_REALISTIC_MAX:
        return True, "WARN"
    else:
        return False, "FAIL"


def is_volume_feasible(contracts_per_trade: int) -> tuple:
    """Return (pass: bool, label: str, message: str) for a contract size."""
    if contracts_per_trade <= CONTRACTS_MARKET_IMPACT_THRESHOLD:
        return True, "OK", f"{contracts_per_trade} contracts: within market impact threshold."
    elif contracts_per_trade <= CONTRACTS_VOLUME_INFEASIBLE:
        return True, "WARN", (
            f"{contracts_per_trade} contracts: exceeds market impact threshold ({CONTRACTS_MARKET_IMPACT_THRESHOLD}). "
            f"Slippage model underestimates real fills."
        )
    else:
        return False, "FAIL", (
            f"{contracts_per_trade} contracts: exceeds volume feasibility threshold ({CONTRACTS_VOLUME_INFEASIBLE}). "
            f"Cannot fill this many OTM contracts at a single price in real markets."
        )
