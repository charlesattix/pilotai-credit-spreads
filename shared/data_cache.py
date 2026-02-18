"""Thread-safe TTL cache for yfinance data."""
import threading
import time
import logging
import yfinance as yf
import pandas as pd
from typing import List
from shared.exceptions import DataFetchError
from shared.metrics import metrics

logger = logging.getLogger(__name__)

# Mapping of period strings to approximate trading days
_PERIOD_DAYS = {
    '5d': 5,
    '1mo': 21,
    '3mo': 63,
    '6mo': 126,
    '1y': 252,
}

class DataCache:
    """Download each ticker's data once (1y period), slice to requested period."""

    def __init__(self, ttl_seconds: int = 900):
        self._cache: dict = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def get_history(self, ticker: str, period: str = '1y') -> pd.DataFrame:
        """Get historical data, using cache if fresh.

        Always downloads the full 1y period and caches by ticker only.
        Shorter periods are sliced locally to avoid redundant downloads.
        """
        key = ticker.upper()
        cached = None
        with self._lock:
            if key in self._cache:
                data, ts = self._cache[key]
                if time.time() - ts < self._ttl:
                    logger.debug(f"Cache hit for {key}")
                    metrics.inc('cache_hits')
                    cached = data

        if cached is not None:
            return self._slice_to_period(cached, period).copy()

        metrics.inc('cache_misses')

        # Download full 1y outside lock
        try:
            data = yf.download(ticker, period='1y', progress=False)
            if hasattr(data.columns, 'nlevels') and data.columns.nlevels > 1:
                data.columns = data.columns.get_level_values(0)
            with self._lock:
                self._cache[key] = (data, time.time())
            return self._slice_to_period(data, period).copy()
        except Exception as e:
            logger.error(f"Failed to download {ticker}: {e}", exc_info=True)
            raise DataFetchError(f"Failed to download data for {ticker}: {e}") from e

    @staticmethod
    def _slice_to_period(data: pd.DataFrame, period: str) -> pd.DataFrame:
        """Slice a full-year DataFrame to the requested period."""
        days = _PERIOD_DAYS.get(period)
        if days is None or days >= len(data):
            return data
        return data.iloc[-days:]

    def pre_warm(self, tickers: List[str]) -> None:
        """Pre-populate the cache for a list of tickers.

        Errors are logged but do not propagate so that a single failed
        ticker does not prevent the rest of the cache from being warmed.
        """
        for ticker in tickers:
            try:
                self.get_history(ticker)
                logger.info(f"Pre-warmed cache for {ticker}")
            except Exception as e:
                logger.warning(f"Pre-warm failed for {ticker}: {e}")

    def get_ticker_obj(self, ticker: str) -> yf.Ticker:
        """Get a yfinance Ticker object (not cached, used for options chains)."""
        try:
            return yf.Ticker(ticker)
        except Exception as e:
            logger.error(f"Failed to create Ticker object for {ticker}: {e}", exc_info=True)
            raise DataFetchError(f"Failed to create Ticker object for {ticker}: {e}") from e

    def clear(self):
        """Clear all cached data."""
        with self._lock:
            self._cache.clear()
