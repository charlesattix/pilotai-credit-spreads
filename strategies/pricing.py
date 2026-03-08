"""
Shared Black-Scholes pricing helpers for all strategy modules.

Wraps shared/strike_selector.py functions and adds spread-level helpers.
No external dependencies beyond math.
"""

import math
from datetime import datetime, timedelta
from typing import List

from shared.strike_selector import _norm_cdf, bs_delta  # noqa: F401
from shared.constants import DEFAULT_RISK_FREE_RATE

from strategies.base import LegType, Position


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str,
) -> float:
    """Black-Scholes European option price.

    Args:
        S: Underlying price.
        K: Strike price.
        T: Time to expiration in years (clamped to >= 1/365).
        r: Risk-free rate (annualised).
        sigma: Implied volatility (annualised, clamped to >= 0.05).
        option_type: 'C' or 'P'.

    Returns:
        Option price (>= 0).
    """
    T = max(T, 1 / 365)
    sigma = max(sigma, 0.05)

    if S <= 0 or K <= 0:
        return 0.0

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type[0].upper() == "C":
        price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)

    return max(price, 0.0)


def estimate_spread_value(
    position: Position,
    underlying_price: float,
    iv: float,
    current_date: datetime,
    r: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """Estimate current net value of a multi-leg position via BS pricing.

    Returns the net value from the position holder's perspective:
    - For credit spreads (short positions): the cost to buy back.
      Positive means you'd pay to close; negative means you'd receive.
    - For debit positions: the proceeds from selling.
    """
    total = 0.0
    for leg in position.legs:
        if leg.leg_type in (LegType.LONG_STOCK, LegType.SHORT_STOCK):
            # Equity leg — value is just the price difference
            if leg.leg_type == LegType.LONG_STOCK:
                total += underlying_price
            else:
                total -= underlying_price
            continue

        dte = max((leg.expiration - current_date).days, 0)
        T = dte / 365.0
        opt_type = "C" if "call" in leg.leg_type.value else "P"
        price = bs_price(underlying_price, leg.strike, T, r, iv, opt_type)

        if "long" in leg.leg_type.value:
            total += price
        else:
            total -= price

    return total


def nearest_friday_expiration(
    date: datetime, target_dte: int = 35, min_dte: int = 25,
) -> datetime:
    """Return the nearest Friday options expiration around target_dte.

    Options expire on Fridays. This snaps the target to the closest Friday
    while ensuring at least min_dte days remain.

    Ported from backtest/backtester.py.
    """
    target = date + timedelta(days=target_dte)
    days_since_friday = (target.weekday() - 4) % 7
    friday_before = target - timedelta(days=days_since_friday)
    friday_after = friday_before + timedelta(days=7)

    min_exp = date + timedelta(days=min_dte)

    if days_since_friday <= 3 and friday_before >= min_exp:
        return friday_before
    return friday_after


def calculate_rsi(closes: List[float], period: int = 14) -> float:
    """Calculate RSI from a list of close prices.

    Returns 50.0 if not enough data.
    """
    if len(closes) < period + 1:
        return 50.0

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-(period):]

    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]

    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> float:
    """Calculate ADX (Average Directional Index).

    Returns 0.0 if not enough data.
    """
    n = len(closes)
    if n < period + 1:
        return 0.0

    plus_dm_list = []
    minus_dm_list = []
    tr_list = []

    for i in range(1, n):
        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]

        plus_dm = high_diff if high_diff > low_diff and high_diff > 0 else 0.0
        minus_dm = low_diff if low_diff > high_diff and low_diff > 0 else 0.0

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
        tr_list.append(tr)

    if len(tr_list) < period:
        return 0.0

    # Wilder smoothing
    atr = sum(tr_list[:period]) / period
    plus_di_smooth = sum(plus_dm_list[:period]) / period
    minus_di_smooth = sum(minus_dm_list[:period]) / period

    dx_list = []
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        plus_di_smooth = (plus_di_smooth * (period - 1) + plus_dm_list[i]) / period
        minus_di_smooth = (minus_di_smooth * (period - 1) + minus_dm_list[i]) / period

        if atr == 0:
            continue
        plus_di = 100 * plus_di_smooth / atr
        minus_di = 100 * minus_di_smooth / atr

        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue
        dx = 100 * abs(plus_di - minus_di) / di_sum
        dx_list.append(dx)

    if not dx_list:
        return 0.0

    adx = sum(dx_list[-period:]) / min(period, len(dx_list))
    return adx
