"""
DataProvider abstraction — pluggable market data for the portfolio backtester.

Two concrete implementations:
  PolygonDataProvider   — real fills from HistoricalOptionsData (SQLite cache)
  HeuristicDataProvider — Black-Scholes model prices (no Polygon required)

Both satisfy the DataProvider Protocol so they can be injected into
PortfolioBacktester and strategies without coupling to Polygon directly.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import List, NamedTuple, Optional, Protocol, runtime_checkable


class SpreadPrices(NamedTuple):
    short_price: float   # mid-price of short leg
    long_price: float    # mid-price of long leg
    net_credit: float    # short - long (positive = credit received)
    slippage: float      # estimated round-trip slippage
    valid: bool          # False if price data was unavailable


@runtime_checkable
class DataProvider(Protocol):
    """Protocol for option market data. Both implementations satisfy this interface."""

    def get_spread_prices(
        self,
        ticker: str,
        expiration: datetime,
        short_strike: float,
        long_strike: float,
        option_type: str,
        date: datetime,
    ) -> SpreadPrices: ...

    def get_available_strikes(
        self, ticker: str, expiration: str, as_of_date: str, option_type: str = "P"
    ) -> List[float]: ...

    def get_underlying_price(self, ticker: str, date: datetime) -> Optional[float]: ...

    def get_expirations(
        self, ticker: str, as_of_date: datetime, min_dte: int, max_dte: int
    ) -> List[str]: ...


class PolygonDataProvider:
    """Thin wrapper around HistoricalOptionsData implementing the DataProvider protocol."""

    def __init__(self, hist_data) -> None:
        """
        Args:
            hist_data: HistoricalOptionsData instance (already initialised).
        """
        self._hd = hist_data

    def get_spread_prices(
        self,
        ticker: str,
        expiration: datetime,
        short_strike: float,
        long_strike: float,
        option_type: str,
        date: datetime,
    ) -> SpreadPrices:
        date_str = date.strftime("%Y-%m-%d") if isinstance(date, datetime) else str(date)
        result = self._hd.get_spread_prices(
            ticker=ticker,
            expiration=expiration,
            short_strike=short_strike,
            long_strike=long_strike,
            option_type=option_type,
            date=date_str,
        )
        if result is None:
            return SpreadPrices(0.0, 0.0, 0.0, 0.0, False)

        short_price = result["short_close"]
        long_price = result["long_close"]
        net_credit = result["spread_value"]
        slippage = 0.05
        return SpreadPrices(short_price, long_price, net_credit, slippage, True)

    def get_available_strikes(
        self, ticker: str, expiration: str, as_of_date: str, option_type: str = "P"
    ) -> List[float]:
        return self._hd.get_available_strikes(ticker, expiration, as_of_date, option_type)

    def get_underlying_price(self, ticker: str, date: datetime) -> Optional[float]:
        # HistoricalOptionsData focuses on option contracts; underlying prices
        # come from yfinance in the portfolio backtester.
        return None

    def get_expirations(
        self, ticker: str, as_of_date: datetime, min_dte: int, max_dte: int
    ) -> List[str]:
        """Query option_contracts table for expirations within the DTE window."""
        cur = self._hd._conn.cursor()
        cur.execute(
            "SELECT DISTINCT expiration FROM option_contracts WHERE ticker = ?",
            (ticker,),
        )
        results = []
        for (exp_str,) in cur.fetchall():
            try:
                exp_dt = datetime.strptime(exp_str, "%Y-%m-%d")
                dte = (exp_dt - as_of_date).days
                if min_dte <= dte <= max_dte:
                    results.append(exp_str)
            except ValueError:
                continue
        return sorted(results)


def _bs_price(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> float:
    """Black-Scholes option price (no external deps)."""
    if T <= 0:
        return max(K - S, 0.0) if option_type == "P" else max(S - K, 0.0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    def N(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))

    if option_type == "C":
        return S * N(d1) - K * math.exp(-r * T) * N(d2)
    return K * math.exp(-r * T) * N(-d2) - S * N(-d1)


class HeuristicDataProvider:
    """Black-Scholes model pricing — fast, no Polygon required. For dev/testing."""

    def __init__(self, iv_estimate: float = 0.25, r: float = 0.045) -> None:
        self.iv_estimate = iv_estimate
        self.r = r

    def get_spread_prices(
        self,
        ticker: str,
        expiration: datetime,
        short_strike: float,
        long_strike: float,
        option_type: str,
        date: datetime,
    ) -> SpreadPrices:
        dte = max((expiration - date).days, 1)
        T = dte / 365.0
        ot = option_type[0].upper()

        # Use the midpoint of the two strikes as a rough underlying estimate.
        S = (short_strike + long_strike) / 2.0 * 1.03

        short_price = _bs_price(S, short_strike, T, self.r, self.iv_estimate, ot)
        long_price = _bs_price(S, long_strike, T, self.r, self.iv_estimate, ot)
        net_credit = short_price - long_price
        slippage = 0.05
        return SpreadPrices(short_price, long_price, net_credit, slippage, net_credit > 0)

    def get_available_strikes(
        self, ticker: str, expiration: str, as_of_date: str, option_type: str = "P"
    ) -> List[float]:
        # No data — callers fall back to OTM% strike calculation.
        return []

    def get_underlying_price(self, ticker: str, date: datetime) -> Optional[float]:
        return None

    def get_expirations(
        self, ticker: str, as_of_date: datetime, min_dte: int, max_dte: int
    ) -> List[str]:
        return []
