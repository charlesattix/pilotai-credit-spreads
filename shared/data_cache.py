"""Thread-safe TTL cache for yfinance data."""
import threading
import time
import logging
import yfinance as yf
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)

class DataCache:
    """Download each ticker's data once (1y period), slice to requested period."""

    def __init__(self, ttl_seconds: int = 900):
        self._cache: dict = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def get_history(self, ticker: str, period: str = '1y') -> pd.DataFrame:
        """Get historical data, using cache if fresh."""
        with self._lock:
            key = ticker.upper()
            now = time.time()
            if key in self._cache:
                data, ts = self._cache[key]
                if now - ts < self._ttl:
                    logger.debug(f"Cache hit for {key}")
                    return data.copy()

        # Download outside lock
        try:
            data = yf.download(ticker, period='1y', progress=False)
            if hasattr(data.columns, 'nlevels') and data.columns.nlevels > 1:
                data.columns = data.columns.get_level_values(0)
            with self._lock:
                self._cache[ticker.upper()] = (data, time.time())
            return data.copy()
        except Exception as e:
            logger.error(f"Failed to download {ticker}: {e}")
            return pd.DataFrame()

    def get_ticker_obj(self, ticker: str) -> yf.Ticker:
        """Get a yfinance Ticker object (not cached, used for options chains)."""
        return yf.Ticker(ticker)

    def clear(self):
        """Clear all cached data."""
        with self._lock:
            self._cache.clear()
