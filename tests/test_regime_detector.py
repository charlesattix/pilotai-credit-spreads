"""Tests for RegimeDetector."""
import pandas as pd
import numpy as np
from datetime import datetime
from unittest.mock import patch, MagicMock

from ml.regime_detector import RegimeDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_market_df(periods=300, seed=42):
    """Create a synthetic market DataFrame mimicking SPY data."""
    np.random.seed(seed)
    dates = pd.date_range(end=datetime.now(), periods=periods, freq='B')
    close = 450.0 + np.cumsum(np.random.randn(periods) * 1.5)
    return pd.DataFrame({
        'Open': close - np.random.rand(periods),
        'High': close + np.abs(np.random.randn(periods)),
        'Low': close - np.abs(np.random.randn(periods)),
        'Close': close,
        'Volume': np.random.randint(1_000_000, 5_000_000, periods),
    }, index=dates)


_MOCK_SPY = _make_market_df()
_MOCK_VIX = pd.DataFrame({
    'Open': np.random.uniform(12, 22, 300),
    'High': np.random.uniform(12, 25, 300),
    'Low': np.random.uniform(10, 20, 300),
    'Close': np.random.uniform(12, 22, 300),
    'Volume': np.random.randint(100_000, 500_000, 300),
}, index=_MOCK_SPY.index)
_MOCK_TLT = _make_market_df(seed=99).set_index(_MOCK_SPY.index)


def _mock_download(ticker, **kwargs):
    """Drop-in replacement for yf.download."""
    if 'VIX' in str(ticker).upper():
        return _MOCK_VIX.copy()
    if 'TLT' in str(ticker).upper():
        return _MOCK_TLT.copy()
    return _MOCK_SPY.copy()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRegimeDetector:

    @patch('ml.regime_detector.yf.download', side_effect=_mock_download)
    def test_fit_returns_true(self, mock_dl):
        """fit() should return True after successful training."""
        detector = RegimeDetector(lookback_days=200)
        assert detector.fit() is True
        assert detector.trained is True

    @patch('ml.regime_detector.yf.download', side_effect=_mock_download)
    def test_detect_regime_returns_dict(self, mock_dl):
        """detect_regime should return a dict with 'regime' key."""
        detector = RegimeDetector(lookback_days=200)
        detector.fit()
        result = detector.detect_regime(ticker='SPY')
        assert isinstance(result, dict)
        assert 'regime' in result
        assert result['regime'] in ['low_vol_trending', 'high_vol_trending',
                                     'mean_reverting', 'crisis']

    @patch('ml.regime_detector.yf.download', side_effect=_mock_download)
    def test_confidence_in_range(self, mock_dl):
        """Confidence should be between 0 and 1."""
        detector = RegimeDetector(lookback_days=200)
        detector.fit()
        result = detector.detect_regime(ticker='SPY')
        assert 0.0 <= result['confidence'] <= 1.0

    @patch('ml.regime_detector.yf.download', return_value=pd.DataFrame())
    def test_fallback_on_empty_data(self, mock_dl):
        """Should return default regime when data is unavailable."""
        detector = RegimeDetector(lookback_days=200)
        result = detector.detect_regime(ticker='SPY')
        assert result.get('fallback') is True
        assert result['regime'] == 'mean_reverting'

    @patch('ml.regime_detector.yf.download', side_effect=_mock_download)
    def test_training_data_has_feature_columns(self, mock_dl):
        """_fetch_training_data should return a DataFrame with expected columns."""
        detector = RegimeDetector(lookback_days=200)
        df = detector._fetch_training_data()
        expected_cols = detector._get_feature_columns()
        for col in expected_cols:
            assert col in df.columns, f"Missing column: {col}"

    def test_data_cache_integration(self):
        """When data_cache is set, _download should use it."""
        mock_cache = MagicMock()
        mock_cache.get_history.return_value = _MOCK_SPY.copy()

        detector = RegimeDetector(lookback_days=200, data_cache=mock_cache)
        result = detector._download('SPY', period='3mo')

        mock_cache.get_history.assert_called_once_with('SPY', '3mo')
        assert not result.empty
