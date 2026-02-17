"""Protocol definition for market data providers.

Captures the shared contract between TradierProvider and PolygonProvider.
AlpacaProvider is an order-execution provider and does not implement this
protocol.
"""

from typing import Dict, List, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class DataProvider(Protocol):
    """Contract that all market-data providers must satisfy."""

    def get_options_chain(self, ticker: str, expiration: str) -> pd.DataFrame:
        """Fetch the options chain for a ticker and single expiration date.

        Args:
            ticker: Stock symbol (e.g. ``"SPY"``).
            expiration: Date string in ``YYYY-MM-DD`` format.

        Returns:
            DataFrame with at minimum the columns: strike, type, bid, ask,
            last, volume, open_interest, iv, delta, gamma, theta, vega, mid,
            expiration.
        """
        ...

    def get_expirations(self, ticker: str) -> List[str]:
        """Return available option expiration dates for *ticker*.

        Returns:
            Sorted list of date strings in ``YYYY-MM-DD`` format.
        """
        ...

    def get_full_chain(
        self, ticker: str, min_dte: int = 25, max_dte: int = 50
    ) -> pd.DataFrame:
        """Fetch the full options chain across expirations within a DTE range.

        Args:
            ticker: Stock symbol.
            min_dte: Minimum days to expiration (inclusive).
            max_dte: Maximum days to expiration (inclusive).

        Returns:
            Combined DataFrame of all relevant expirations, with an extra
            ``dte`` column.
        """
        ...

    def get_quote(self, ticker: str) -> Dict:
        """Get a real-time (or near-real-time) quote for *ticker*.

        Returns:
            Dict with at least ``symbol`` and ``last`` keys.
        """
        ...
