"""
Regime classifier — tags each trading day with a market regime.

Uses VIX levels + SPY price trends per MASTERPLAN spec:
  - BULL:         SPY trending up, VIX < 20
  - BEAR:         SPY trending down, VIX > 25
  - HIGH_VOL:     VIX > 30 (any direction)
  - LOW_VOL:      VIX < 15, no strong trend
  - CRASH:        VIX > 40, sharp decline

Designed to work with pre-loaded price data (no network calls),
so it can be used inside the portfolio backtester's day loop.
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class Regime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    CRASH = "crash"


# Strategy recommendations per regime (for logging / allocation hints)
REGIME_INFO = {
    Regime.BULL: {
        "label": "Bull",
        "strategies": ["credit_spread", "momentum_swing", "debit_spread"],
        "risk": "medium",
    },
    Regime.BEAR: {
        "label": "Bear",
        "strategies": ["credit_spread", "gamma_lotto", "debit_spread"],
        "risk": "high",
    },
    Regime.HIGH_VOL: {
        "label": "High Volatility",
        "strategies": ["iron_condor", "straddle_strangle", "credit_spread"],
        "risk": "medium-high",
    },
    Regime.LOW_VOL: {
        "label": "Low Vol Sideways",
        "strategies": ["calendar_spread", "iron_condor", "gamma_lotto"],
        "risk": "low",
    },
    Regime.CRASH: {
        "label": "Crash",
        "strategies": ["gamma_lotto"],
        "risk": "extreme",
    },
}


class RegimeClassifier:
    """Rule-based regime classifier using VIX + price trend.

    All methods work on pre-loaded data (no yfinance calls), so they
    can be called inside the backtester day loop without network overhead.

    Args:
        trend_window: Number of days for the trend moving average.
        trend_threshold: Minimum slope (annualized %) to consider trending.
    """

    def __init__(self, trend_window: int = 50, trend_threshold: float = 5.0):
        self.trend_window = trend_window
        self.trend_threshold = trend_threshold  # annualized % slope

    def classify(
        self,
        vix: float,
        spy_prices: pd.Series,
        date: pd.Timestamp,
    ) -> Regime:
        """Classify the regime for a single trading day.

        Args:
            vix: Current VIX close value.
            spy_prices: SPY close series up to (and including) this date.
            date: Current date (for debugging; not used in logic).

        Returns:
            Regime enum value.
        """
        # Crash takes highest priority — VIX > 40 + sharp decline
        if vix > 40:
            if self._is_declining(spy_prices):
                return Regime.CRASH
            # VIX > 40 but no sharp decline → still high vol
            return Regime.HIGH_VOL

        # High vol — VIX > 30 (any direction)
        if vix > 30:
            return Regime.HIGH_VOL

        # Determine trend direction
        trend = self._trend_direction(spy_prices)

        # Bear — VIX > 25, SPY trending down
        if vix > 25 and trend < 0:
            return Regime.BEAR

        # Bull — VIX < 20, SPY trending up
        if vix < 20 and trend > 0:
            return Regime.BULL

        # Low vol sideways — VIX < 15, no strong trend
        if vix < 15 and abs(trend) == 0:
            return Regime.LOW_VOL

        # Ambiguous zones: use trend + VIX together
        if trend > 0:
            return Regime.BULL
        elif trend < 0:
            if vix > 22:
                return Regime.BEAR
            return Regime.BULL  # mild pullback, low VIX → still constructive
        else:
            # No trend
            if vix < 18:
                return Regime.LOW_VOL
            return Regime.BULL  # neutral → default to constructive

    def classify_series(
        self,
        spy_data: pd.DataFrame,
        vix_series: pd.Series,
    ) -> pd.Series:
        """Tag every trading day with a regime.

        Args:
            spy_data: SPY OHLCV DataFrame with DatetimeIndex.
            vix_series: VIX close Series with DatetimeIndex.

        Returns:
            pd.Series of Regime values indexed by date.
        """
        close = spy_data["Close"]
        regimes: Dict[pd.Timestamp, Regime] = {}

        for date in close.index:
            vix_val = vix_series.get(date, 20.0)
            if isinstance(vix_val, pd.Series):
                vix_val = float(vix_val.iloc[0]) if len(vix_val) > 0 else 20.0
            else:
                vix_val = float(vix_val)

            prices_to_date = close.loc[:date]
            regimes[date] = self.classify(vix_val, prices_to_date, date)

        return pd.Series(regimes, name="regime")

    # ------------------------------------------------------------------
    # Trend helpers
    # ------------------------------------------------------------------

    def _trend_direction(self, prices: pd.Series) -> int:
        """Determine trend direction: +1 up, -1 down, 0 flat.

        Uses slope of the `trend_window`-day moving average, annualized.
        """
        if len(prices) < self.trend_window:
            # Not enough data — use shorter window
            window = max(10, len(prices))
        else:
            window = self.trend_window

        ma = prices.rolling(window, min_periods=max(5, window // 2)).mean()
        if len(ma.dropna()) < 2:
            return 0

        # Slope over last 20 days (annualized as %)
        lookback = min(20, len(ma.dropna()))
        recent_ma = ma.dropna().iloc[-lookback:]
        if len(recent_ma) < 2 or recent_ma.iloc[0] == 0:
            return 0

        pct_change = (recent_ma.iloc[-1] / recent_ma.iloc[0] - 1) * 100
        annualized = pct_change * (252 / lookback)

        if annualized > self.trend_threshold:
            return 1
        elif annualized < -self.trend_threshold:
            return -1
        return 0

    def _is_declining(self, prices: pd.Series) -> bool:
        """Check for sharp decline (>5% drop over last 10 trading days)."""
        if len(prices) < 10:
            return False
        recent = prices.iloc[-10:]
        pct_change = (recent.iloc[-1] / recent.iloc[0] - 1) * 100
        return pct_change < -5.0

    # ------------------------------------------------------------------
    # Summary stats
    # ------------------------------------------------------------------

    @staticmethod
    def summarize(regime_series: pd.Series) -> Dict:
        """Compute regime distribution summary.

        Returns:
            Dict with counts, percentages, and regime transitions.
        """
        counts = regime_series.value_counts()
        total = len(regime_series)

        distribution = {}
        for regime in Regime:
            n = int(counts.get(regime, 0))
            distribution[regime.value] = {
                "days": n,
                "pct": round(n / total * 100, 1) if total else 0,
            }

        # Count transitions
        transitions = 0
        prev = None
        for r in regime_series:
            if prev is not None and r != prev:
                transitions += 1
            prev = r

        return {
            "total_days": total,
            "distribution": distribution,
            "transitions": transitions,
            "avg_regime_duration": round(total / max(1, transitions), 1),
        }
