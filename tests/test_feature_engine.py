"""Tests for FeatureEngine."""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from ml.feature_engine import FeatureEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_price_df(periods=130, seed=42):
    """Create a synthetic price DataFrame that mimics yf.download output."""
    np.random.seed(seed)
    dates = pd.date_range('2025-06-01', periods=periods, freq='B')
    close = 450.0 + np.cumsum(np.random.randn(periods) * 2)
    return pd.DataFrame({
        'Open': close - np.random.rand(periods),
        'High': close + np.abs(np.random.randn(periods)),
        'Low': close - np.abs(np.random.randn(periods)),
        'Close': close,
        'Volume': np.random.randint(1_000_000, 5_000_000, periods),
    }, index=dates)


def _make_options_df():
    exp_date = datetime.now() + timedelta(days=35)
    return pd.DataFrame({
        'strike': [100.0, 105.0],
        'bid': [2.0, 3.0],
        'ask': [2.5, 3.5],
        'type': ['put', 'call'],
        'expiration': [exp_date, exp_date],
        'iv': [0.25, 0.30],
    })


_MOCK_PRICE_DF = _make_price_df()


def _mock_download(ticker, period='6mo', progress=False):
    """A drop-in replacement for yf.download used in tests."""
    return _MOCK_PRICE_DF.copy()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildFeatures:

    @patch('ml.feature_engine.yf.download', side_effect=_mock_download)
    @patch('ml.feature_engine.yf.Ticker')
    def test_returns_dict_with_ticker(self, mock_ticker_cls, mock_dl):
        """build_features should return a dict containing the ticker key."""
        mock_ticker = MagicMock()
        mock_ticker.calendar = None
        mock_ticker_cls.return_value = mock_ticker

        engine = FeatureEngine()
        result = engine.build_features(
            ticker='SPY',
            current_price=450.0,
            options_chain=_make_options_df(),
        )
        assert result['ticker'] == 'SPY'

    @patch('ml.feature_engine.yf.download', side_effect=_mock_download)
    @patch('ml.feature_engine.yf.Ticker')
    def test_contains_technical_features(self, mock_ticker_cls, mock_dl):
        """build_features should include technical features like rsi_14."""
        mock_ticker = MagicMock()
        mock_ticker.calendar = None
        mock_ticker_cls.return_value = mock_ticker

        engine = FeatureEngine()
        result = engine.build_features(
            ticker='SPY',
            current_price=450.0,
            options_chain=_make_options_df(),
        )
        assert 'rsi_14' in result
        assert 'macd' in result


class TestComputeTechnicalFeatures:

    @patch('ml.feature_engine.yf.download', side_effect=_mock_download)
    def test_rsi_in_range(self, mock_dl):
        """RSI should be between 0 and 100."""
        engine = FeatureEngine()
        features = engine._compute_technical_features('SPY', 450.0)
        assert 0 <= features['rsi_14'] <= 100

    @patch('ml.feature_engine.yf.download', side_effect=_mock_download)
    def test_atr_pct_positive(self, mock_dl):
        """ATR percentage should be positive."""
        engine = FeatureEngine()
        features = engine._compute_technical_features('SPY', 450.0)
        assert features['atr_pct'] > 0

    @patch('ml.feature_engine.yf.download', return_value=pd.DataFrame())
    def test_returns_defaults_on_empty_data(self, mock_dl):
        """Should return default features when download returns empty data."""
        engine = FeatureEngine()
        features = engine._compute_technical_features('BAD', 100.0)
        assert features['rsi_14'] == 50.0


class TestComputeVolatilityFeatures:

    @patch('ml.feature_engine.yf.download', side_effect=_mock_download)
    def test_realized_vol_positive(self, mock_dl):
        """Realized volatility values should be positive."""
        engine = FeatureEngine()
        features = engine._compute_volatility_features(
            'SPY', _make_options_df(), None
        )
        assert features['realized_vol_10d'] > 0
        assert features['realized_vol_20d'] > 0

    @patch('ml.feature_engine.yf.download', side_effect=_mock_download)
    def test_iv_from_analysis(self, mock_dl):
        """When iv_analysis is provided, use its values."""
        engine = FeatureEngine()
        iv_analysis = {
            'iv_rank_percentile': {
                'available': True,
                'iv_rank': 75.0,
                'iv_percentile': 80.0,
                'current_iv': 30.0,
            },
            'skew': {'available': False},
        }
        features = engine._compute_volatility_features(
            'SPY', _make_options_df(), iv_analysis
        )
        assert features['iv_rank'] == 75.0


class TestComputeMarketFeatures:

    @patch('ml.feature_engine.yf.download', side_effect=_mock_download)
    def test_returns_vix_level(self, mock_dl):
        """Market features should contain vix_level."""
        engine = FeatureEngine()
        features = engine.compute_market_features()
        assert 'vix_level' in features

    @patch('ml.feature_engine.yf.download', return_value=pd.DataFrame())
    def test_returns_defaults_on_empty(self, mock_dl):
        """Should return safe defaults when downloads fail."""
        engine = FeatureEngine()
        features = engine.compute_market_features()
        assert features['vix_level'] == 15.0


class TestDataCacheBehavior:

    def test_uses_data_cache_when_provided(self):
        """When data_cache is set, _download should call data_cache.get_history."""
        mock_cache = MagicMock()
        mock_cache.get_history.return_value = _MOCK_PRICE_DF.copy()

        engine = FeatureEngine(data_cache=mock_cache)
        result = engine._download('SPY', period='6mo')

        mock_cache.get_history.assert_called_once_with('SPY', '6mo')
        assert not result.empty

    @patch('ml.feature_engine.yf.download', side_effect=_mock_download)
    def test_falls_back_to_yf_without_cache(self, mock_dl):
        """Without data_cache, _download should call yf.download."""
        engine = FeatureEngine()
        result = engine._download('SPY', period='6mo')
        mock_dl.assert_called_once_with('SPY', period='6mo', progress=False)


class TestGetFeatureNames:

    def test_returns_list(self):
        """get_feature_names should return a non-empty list of strings."""
        engine = FeatureEngine()
        names = engine.get_feature_names()
        assert isinstance(names, list)
        assert len(names) > 20
        assert all(isinstance(n, str) for n in names)


class TestDerivedFeatures:

    def test_rsi_oversold_flag(self):
        """rsi_oversold should be 1.0 when RSI < 30."""
        engine = FeatureEngine()
        features = {'rsi_14': 25.0, 'iv_rank': 50.0, 'realized_vol_20d': 20.0,
                     'current_iv': 25.0, 'atr_pct': 2.0, 'return_20d': 5.0}
        derived = engine._compute_derived_features(features)
        assert derived['rsi_oversold'] == 1.0
        assert derived['rsi_overbought'] == 0.0

    def test_vol_premium_calculation(self):
        """vol_premium should be current_iv - realized_vol_20d."""
        engine = FeatureEngine()
        features = {'rsi_14': 50.0, 'iv_rank': 50.0, 'realized_vol_20d': 15.0,
                     'current_iv': 25.0, 'atr_pct': 2.0, 'return_20d': 5.0}
        derived = engine._compute_derived_features(features)
        assert derived['vol_premium'] == pytest.approx(10.0)
