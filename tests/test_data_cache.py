"""Tests for DataCache."""
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from shared.data_cache import DataCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_price_df(periods=100, seed=42):
    np.random.seed(seed)
    dates = pd.date_range('2025-01-01', periods=periods, freq='B')
    close = 450.0 + np.cumsum(np.random.randn(periods) * 2)
    return pd.DataFrame({
        'Open': close - 0.5,
        'High': close + 1.0,
        'Low': close - 1.0,
        'Close': close,
        'Volume': np.random.randint(1_000_000, 5_000_000, periods),
    }, index=dates)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDataCache:

    @patch('shared.data_cache.yf.download')
    def test_get_history_caches(self, mock_dl):
        """Second call should use cached data, not download again."""
        mock_dl.return_value = _make_price_df()
        cache = DataCache(ttl_seconds=60)

        result1 = cache.get_history('SPY')
        result2 = cache.get_history('SPY')

        assert mock_dl.call_count == 1
        assert len(result1) == len(result2)

    @patch('shared.data_cache.yf.download')
    def test_get_history_returns_copy(self, mock_dl):
        """Each call should return a copy, not a reference to cached data."""
        mock_dl.return_value = _make_price_df()
        cache = DataCache(ttl_seconds=60)

        result1 = cache.get_history('SPY')
        result2 = cache.get_history('SPY')

        # Modifying one should not affect the other
        result1.iloc[0, 0] = -9999
        assert result2.iloc[0, 0] != -9999

    @patch('shared.data_cache.yf.download')
    def test_different_tickers_download_separately(self, mock_dl):
        """Different tickers should each trigger their own download."""
        mock_dl.return_value = _make_price_df()
        cache = DataCache(ttl_seconds=60)

        cache.get_history('SPY')
        cache.get_history('QQQ')

        assert mock_dl.call_count == 2

    @patch('shared.data_cache.yf.download')
    def test_clear_resets_cache(self, mock_dl):
        """After clear(), next call should download again."""
        mock_dl.return_value = _make_price_df()
        cache = DataCache(ttl_seconds=60)

        cache.get_history('SPY')
        cache.clear()
        cache.get_history('SPY')

        assert mock_dl.call_count == 2

    def test_get_ticker_obj(self):
        """get_ticker_obj should return a yf.Ticker object."""
        cache = DataCache()
        ticker = cache.get_ticker_obj('SPY')
        assert ticker is not None
