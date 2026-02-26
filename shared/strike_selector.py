"""
Delta-based strike selection for credit spreads.

Pure functions — no I/O dependencies, no external packages.
Works in both live scanner (real Polygon greeks) and backtester
(Black-Scholes approximated delta from historical_data).
"""

import math
from typing import Dict, List, Optional


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erf — no scipy required."""
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0


def bs_delta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str,
) -> float:
    """Black-Scholes delta for a European option.

    Args:
        S: Underlying price.
        K: Strike price.
        T: Time to expiration in years (must be > 0 for meaningful result).
        r: Risk-free rate, annualised (e.g. 0.045 for 4.5%).
        sigma: Implied volatility, annualised (e.g. 0.20 for 20%).
        option_type: 'P' or 'C' (case-insensitive).

    Returns:
        Delta — negative for puts (range [−1, 0]),
                positive for calls (range [0, 1]).
        Returns boundary values at expiry or for degenerate inputs.
    """
    ot = option_type[0].upper()

    # Boundary / degenerate cases
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        if ot == "P":
            return -1.0 if S < K else 0.0
        return 1.0 if S > K else 0.0

    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    except (ValueError, ZeroDivisionError):
        return 0.0

    if ot == "P":
        return _norm_cdf(d1) - 1.0  # negative for puts
    return _norm_cdf(d1)            # positive for calls


def select_delta_strike(
    chain_rows: List[Dict],
    option_type: str,
    target_delta: float = 0.12,
) -> Optional[float]:
    """Return the strike whose |delta| is closest to target_delta.

    Args:
        chain_rows: List of dicts, each with at minimum 'strike' (float)
                    and 'delta' (float, signed) keys.
                    Put deltas are negative; call deltas are positive.
        option_type: 'P' or 'C' — informational only; caller must supply
                     appropriately-signed deltas.
        target_delta: Absolute delta to target (default 0.12 = 12-delta).
                      Comparison is done on abs(delta), so sign is irrelevant.

    Returns:
        The best matching strike price, or None if chain_rows is empty.
    """
    if not chain_rows:
        return None

    best = min(
        chain_rows,
        key=lambda r: abs(abs(r["delta"]) - target_delta),
    )
    return best["strike"]
