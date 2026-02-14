"""Canonical implementations of technical indicators used across the system."""

import pandas as pd
import numpy as np


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate RSI (Relative Strength Index).

    Uses the standard Wilder smoothing method (simple moving average of gains/losses).

    Args:
        prices: Series of closing prices.
        period: Lookback period (default 14).

    Returns:
        Series of RSI values (0-100).
    """
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_iv_rank(hv_values: pd.Series, current_iv: float) -> dict:
    """
    Calculate IV rank and IV percentile from a series of historical volatility values.

    IV Rank  = (current - min) / (max - min) * 100
    IV %ile  = fraction of observations below current_iv * 100

    Args:
        hv_values: Historical volatility observations (e.g. 20-day rolling HV).
        current_iv: The current implied (or realized) volatility value to rank.

    Returns:
        Dictionary with iv_rank, iv_percentile, iv_min, iv_max.
    """
    hv_clean = hv_values.dropna()

    if len(hv_clean) == 0:
        return {
            'iv_rank': 0.0,
            'iv_percentile': 0.0,
            'iv_min': 0.0,
            'iv_max': 0.0,
        }

    iv_min = float(hv_clean.min())
    iv_max = float(hv_clean.max())

    if iv_max > iv_min:
        iv_rank = ((current_iv - iv_min) / (iv_max - iv_min)) * 100
    else:
        iv_rank = 50.0

    iv_percentile = float((hv_clean < current_iv).sum() / len(hv_clean) * 100)

    return {
        'iv_rank': round(iv_rank, 2),
        'iv_percentile': round(iv_percentile, 2),
        'iv_min': round(iv_min, 2),
        'iv_max': round(iv_max, 2),
    }
