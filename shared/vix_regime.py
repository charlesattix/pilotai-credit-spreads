"""
VIX regime filter — adjusts position sizing based on VIX level and term structure.

Stateless, pure-function module.  Two public functions:

* ``compute_vrp(vix, realized_vol)`` — Volatility Risk Premium
* ``vix_sizing_factor(vix, realized_vol, vix_history)`` — sizing multiplier

Reference: 100% Returns Research §8.3 Step 1.2.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class VixSizingResult:
    """Sizing output from the VIX regime filter."""
    factor: float       # 0.25 – 1.5
    regime: str         # "low_vol" | "normal" | "elevated" | "high_vol" | "crisis"
    vrp: float          # computed VRP
    term_slope: float   # vix_20d_ma - vix (positive = contango = normal)


def compute_vrp(vix: float, realized_vol: float) -> float:
    """Volatility Risk Premium = VIX - (realized_vol × 100).

    Positive VRP → options overpriced → favorable for premium selling.
    """
    return vix - (realized_vol * 100.0)


def vix_sizing_factor(
    vix: float,
    realized_vol: float,
    vix_history: Optional[pd.Series] = None,
) -> VixSizingResult:
    """Compute a position-sizing multiplier based on VIX regime.

    Parameters
    ----------
    vix : float
        Current VIX level.
    realized_vol : float
        Realized (historical) volatility as a decimal (e.g. 0.20 = 20%).
    vix_history : pd.Series, optional
        Recent VIX daily closes.  Used to approximate term structure via
        20-day MA vs spot VIX.

    Returns
    -------
    VixSizingResult
        factor clamped to [0.25, 1.5], regime label, VRP, and term slope.
    """
    vrp = compute_vrp(vix, realized_vol)

    # --- Regime classification & base factor ---
    if vix > 40:
        regime = "crisis"
        factor = 0.25
    elif vix >= 35:
        regime = "high_vol"
        factor = 0.50
    elif vix >= 25:
        regime = "elevated"
        factor = 1.00 if vrp > 4 else 0.65
    elif vix >= 15:
        regime = "normal"
        factor = 1.25 if vrp > 4 else 1.00
    else:
        regime = "low_vol"
        factor = 0.80

    # --- Term structure adjustment (approximated from VIX history) ---
    term_slope = 0.0
    if vix_history is not None and len(vix_history) >= 20:
        vix_20d_ma = float(vix_history.iloc[-20:].mean())
        term_slope = vix_20d_ma - vix

        if term_slope < -3:
            # Backwardation — stress signal, reduce size
            factor *= 0.85
        elif term_slope > 5:
            # Steep contango — normal/favorable, slight boost
            factor *= 1.10

    # Clamp
    factor = max(0.25, min(1.5, factor))

    return VixSizingResult(
        factor=round(factor, 4),
        regime=regime,
        vrp=round(vrp, 4),
        term_slope=round(term_slope, 4),
    )
