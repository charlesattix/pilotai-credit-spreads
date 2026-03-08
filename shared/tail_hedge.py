"""Systematic tail hedge module — pure functions for OTM put protection.

Buys OTM put protection when VIX is cheap (below historical median).
Budget: 2-3% of portfolio monthly.
Expected impact: -5-8% max DD reduction, portfolio insurance during crashes.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import List

from strategies.pricing import nearest_friday_expiration


@dataclass(frozen=True)
class HedgeRecommendation:
    """Output of the tail hedge decision pipeline."""
    should_hedge: bool
    strike: float           # OTM put strike
    expiration: datetime    # target expiry
    dte: int
    estimated_cost: float   # per-contract cost (premium)
    contracts: int          # budget-sized
    protection_ratio: float # notional protected per dollar spent
    vix_percentile: float   # where current VIX sits vs history


def should_buy_hedge(vix: float, vix_history: List[float]) -> bool:
    """Return True when VIX is below 252-day median (hedges are cheap).

    Returns False if:
    - Fewer than 60 days of VIX history (insufficient data)
    - VIX > 30 (hedges too expensive; already protected via reduced sizing)
    """
    if len(vix_history) < 60:
        return False
    if vix > 30:
        return False
    last_252 = vix_history[-252:] if len(vix_history) >= 252 else vix_history
    median = sorted(last_252)[len(last_252) // 2]
    return vix < median


def optimal_put_strike(price: float, vix: float, target_dte: int = 45) -> float:
    """Compute OTM put strike that maximizes gamma per dollar.

    OTM percentage scales with VIX:
    - Low VIX (<15): 5% OTM (cheap, buy closer protection)
    - Normal VIX (15-20): 7% OTM (balance cost/protection)
    - Elevated VIX (20-30): 10% OTM (further OTM to stay cheap)
    """
    if vix < 15:
        otm_pct = 0.05
    elif vix <= 20:
        otm_pct = 0.07
    else:
        otm_pct = 0.10
    strike = price * (1 - otm_pct)
    return round(strike)


def hedge_budget(
    equity: float,
    monthly_budget_pct: float = 0.025,
    days_since_last_hedge: int = 30,
) -> float:
    """Compute budget for tail hedge purchases.

    - Monthly budget: equity * monthly_budget_pct (default 2.5%)
    - Pro-rate if hedging mid-month
    - Returns 0 if hedged within last 7 days (cooldown)
    """
    if equity <= 0:
        return 0.0
    if days_since_last_hedge < 7:
        return 0.0
    monthly = equity * monthly_budget_pct
    prorate = min(1.0, days_since_last_hedge / 30)
    return monthly * prorate


def select_hedge_expiry(
    date: datetime,
    min_dte: int = 30,
    max_dte: int = 60,
) -> datetime:
    """Select optimal expiration for tail hedge (30-60 DTE).

    Uses nearest_friday_expiration with target_dte=45 for best
    theta decay profile.
    """
    return nearest_friday_expiration(date, target_dte=45, min_dte=min_dte)


def size_hedge(budget: float, put_price: float, max_contracts: int = 10) -> int:
    """Determine number of put contracts to buy within budget.

    Returns 0 if can't afford even 1 contract.
    """
    if put_price <= 0 or budget <= 0:
        return 0
    cost_per_contract = put_price * 100
    if cost_per_contract > budget:
        return 0
    contracts = math.floor(budget / cost_per_contract)
    return min(contracts, max_contracts)


def compute_protection_ratio(price: float, strike: float, put_price: float) -> float:
    """Compute notional protected per dollar spent.

    Higher ratio = better value for the hedge.
    """
    if put_price <= 0 or price <= strike:
        return 0.0
    notional = (price - strike) * 100
    cost = put_price * 100
    return notional / cost


def vix_percentile(vix: float, vix_history: List[float]) -> float:
    """Compute percentile rank of current VIX vs history (0-100)."""
    if not vix_history:
        return 50.0
    below = sum(1 for v in vix_history if v <= vix)
    return (below / len(vix_history)) * 100
