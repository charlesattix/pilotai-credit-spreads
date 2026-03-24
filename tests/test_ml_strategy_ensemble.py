"""
Tests for ensemble_mode integration in compass.ml_strategy.

Verifies:
  1. load_signal_model() returns SignalModel in default mode
  2. load_signal_model() returns EnsembleSignalModel in ensemble mode
  3. load_signal_model() returns None when model file is missing
  4. MLEnhancedStrategy works with EnsembleSignalModel (V1 gating)
  5. MLEnhancedStrategy works with EnsembleSignalModel (V2 sizing)
  6. RegimeModelRouter respects ensemble_mode flag
  7. Backward compatibility — default config still uses SignalModel
  8. ensemble_mode config flag is stored on the strategy instance
"""

import tempfile
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from compass.ml_strategy import (
    AnySignalModel,
    DEFAULT_CONFIDENCE_THRESHOLD,
    MLEnhancedStrategy,
    RegimeModelRouter,
    load_signal_model,
)
from compass.signal_model import SignalModel
from compass.ensemble_signal_model import EnsembleSignalModel
from strategies.base import (
    BaseStrategy,
    LegType,
    MarketSnapshot,
    ParamDef,
    PortfolioState,
    Position,
    PositionAction,
    Signal,
    TradeDirection,
    TradeLeg,
)


# ---------------------------------------------------------------------------
# Fixtures (reused from test_ml_strategy.py pattern)
# ---------------------------------------------------------------------------

def _make_signal(ticker: str = "SPY") -> Signal:
    exp = datetime(2026, 4, 18)
    return Signal(
        strategy_name="TestStrategy",
        ticker=ticker,
        direction=TradeDirection.SHORT,
        legs=[
            TradeLeg(LegType.SHORT_PUT, strike=440.0, expiration=exp, entry_price=2.50),
            TradeLeg(LegType.LONG_PUT, strike=428.0, expiration=exp, entry_price=0.80),
        ],
        net_credit=1.70,
        max_loss=10.30,
        max_profit=1.70,
        score=50.0,
        signal_date=datetime(2026, 3, 21),
        expiration=exp,
        dte=28,
        metadata={'spread_type': 'bull_put'},
    )


def _make_market_snapshot() -> MarketSnapshot:
    idx = pd.bdate_range("2026-01-02", periods=60)
    prices = pd.Series(range(440, 500), index=idx[:60], name="Close", dtype=float)
    df = pd.DataFrame({"Close": prices, "Open": prices, "High": prices + 1,
                        "Low": prices - 1, "Volume": [1_000_000] * 60})
    return MarketSnapshot(
        date=datetime(2026, 3, 21),
        price_data={"SPY": df},
        prices={"SPY": 480.0},
        vix=18.0,
        iv_rank={"SPY": 45.0},
        realized_vol={"SPY": 15.0},
        rsi={"SPY": 52.0},
        regime="bull",
    )


def _make_portfolio_state() -> PortfolioState:
    return PortfolioState(equity=100_000.0, starting_capital=100_000.0, cash=90_000.0)


class StubStrategy(BaseStrategy):
    def __init__(self, signals=None, action=PositionAction.HOLD, contracts=2):
        super().__init__({})
        self._signals = signals or []
        self._action = action
        self._contracts = contracts

    def generate_signals(self, market_data):
        return list(self._signals)

    def manage_position(self, position, market_data):
        return self._action

    def size_position(self, signal, portfolio_state):
        return self._contracts

    @classmethod
    def get_param_space(cls):
        return []


def _mock_model(model_class, prediction=None):
    """Create a mock with the given class spec and a canned prediction."""
    model = MagicMock(spec=model_class)
    model.trained = True
    model.feature_names = ['rsi_14', 'vix_level', 'iv_rank']
    if prediction is None:
        prediction = {
            'prediction': 1,
            'probability': 0.75,
            'confidence': 0.50,
            'signal': 'bullish',
            'signal_strength': 75.0,
            'timestamp': '2026-03-21T00:00:00+00:00',
        }
    model.predict.return_value = prediction
    model.predict_batch.return_value = np.array([prediction['probability']])
    return model


# ---------------------------------------------------------------------------
# Test load_signal_model factory
# ---------------------------------------------------------------------------

class TestLoadSignalModel:

    def test_default_mode_returns_signal_model(self):
        """ensemble_mode=False should instantiate SignalModel."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock model file
            model = SignalModel(model_dir=tmpdir)
            _train_and_save_dummy(model, tmpdir, "signal_model_20260321.joblib")

            loaded = load_signal_model(model_dir=tmpdir, ensemble_mode=False)
            assert loaded is not None
            assert isinstance(loaded, SignalModel)
            assert loaded.trained is True

    def test_ensemble_mode_returns_ensemble_model(self):
        """ensemble_mode=True should instantiate EnsembleSignalModel."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            _train_and_save_dummy_ensemble(model, tmpdir, "ensemble_model_20260321.joblib")

            loaded = load_signal_model(model_dir=tmpdir, ensemble_mode=True)
            assert loaded is not None
            assert isinstance(loaded, EnsembleSignalModel)
            assert loaded.trained is True

    def test_returns_none_on_missing_file(self):
        """Should return None when no model files exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = load_signal_model(model_dir=tmpdir, ensemble_mode=False)
            assert loaded is None

    def test_returns_none_on_missing_ensemble_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = load_signal_model(model_dir=tmpdir, ensemble_mode=True)
            assert loaded is None

    def test_explicit_filename(self):
        """Should load a specific file by name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model = SignalModel(model_dir=tmpdir)
            _train_and_save_dummy(model, tmpdir, "signal_model_custom.joblib")

            loaded = load_signal_model(
                model_dir=tmpdir,
                ensemble_mode=False,
                filename="signal_model_custom.joblib",
            )
            assert loaded is not None
            assert loaded.trained is True


# ---------------------------------------------------------------------------
# Test MLEnhancedStrategy with EnsembleSignalModel
# ---------------------------------------------------------------------------

class TestEnsembleModeV1Gating:
    """Ensemble model works with V1 binary gating."""

    def test_high_confidence_passes(self):
        model = _mock_model(EnsembleSignalModel, prediction={
            'prediction': 1, 'probability': 0.80, 'confidence': 0.60,
            'signal': 'bullish', 'signal_strength': 80.0,
            'timestamp': '2026-03-21T00:00:00+00:00',
        })
        base = StubStrategy(signals=[_make_signal()])
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
            ml_config={'confidence_threshold': 0.30, 'ensemble_mode': True},
        )
        snap = _make_market_snapshot()
        signals = ml_strat.generate_signals(snap)
        assert len(signals) == 1
        assert signals[0].metadata['ml_confidence'] == 0.60

    def test_low_confidence_filtered(self):
        model = _mock_model(EnsembleSignalModel, prediction={
            'prediction': 0, 'probability': 0.52, 'confidence': 0.04,
            'signal': 'neutral', 'signal_strength': 52.0,
            'timestamp': '2026-03-21T00:00:00+00:00',
        })
        base = StubStrategy(signals=[_make_signal()])
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
            ml_config={'confidence_threshold': 0.30, 'ensemble_mode': True},
        )
        snap = _make_market_snapshot()
        signals = ml_strat.generate_signals(snap)
        assert len(signals) == 0

    def test_fallback_passes(self):
        model = _mock_model(EnsembleSignalModel, prediction={
            'prediction': 0, 'probability': 0.5, 'confidence': 0.0,
            'signal': 'neutral', 'signal_strength': 50.0,
            'timestamp': '2026-03-21T00:00:00+00:00',
            'fallback': True,
        })
        base = StubStrategy(signals=[_make_signal()])
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
            ml_config={'confidence_threshold': 0.50, 'ensemble_mode': True},
        )
        snap = _make_market_snapshot()
        signals = ml_strat.generate_signals(snap)
        assert len(signals) == 1
        assert signals[0].metadata['ml_gated'] is False


class TestEnsembleModeV2Sizing:
    """Ensemble model works with V2 confidence sizing."""

    def test_v2_never_drops_signals(self):
        model = _mock_model(EnsembleSignalModel, prediction={
            'prediction': 0, 'probability': 0.51, 'confidence': 0.02,
            'signal': 'neutral', 'signal_strength': 51.0,
            'timestamp': '2026-03-21T00:00:00+00:00',
        })
        base = StubStrategy(signals=[_make_signal()])
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
            ml_config={
                'ml_sizing': True,
                'ensemble_mode': True,
            },
        )
        snap = _make_market_snapshot()
        signals = ml_strat.generate_signals(snap)
        assert len(signals) == 1
        assert 'ml_size_multiplier' in signals[0].metadata

    def test_v2_multiplier_scales_contracts(self):
        model = _mock_model(EnsembleSignalModel, prediction={
            'prediction': 1, 'probability': 0.90, 'confidence': 0.80,
            'signal': 'bullish', 'signal_strength': 90.0,
            'timestamp': '2026-03-21T00:00:00+00:00',
        })
        base = StubStrategy(signals=[_make_signal()], contracts=4)
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
            ml_config={'ml_sizing': True, 'ensemble_mode': True},
        )
        snap = _make_market_snapshot()
        signals = ml_strat.generate_signals(snap)
        assert len(signals) == 1
        ps = _make_portfolio_state()
        contracts = ml_strat.size_position(signals[0], ps)
        # multiplier > 1.0 for confidence=0.80, base=4 → contracts >= 4
        assert contracts >= 4


# ---------------------------------------------------------------------------
# Test ensemble_mode flag propagation
# ---------------------------------------------------------------------------

class TestEnsembleModeConfig:

    def test_ensemble_mode_stored_on_strategy(self):
        model = _mock_model(SignalModel)
        base = StubStrategy()
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
            ml_config={'ensemble_mode': True},
        )
        assert ml_strat.ensemble_mode is True

    def test_default_is_not_ensemble(self):
        model = _mock_model(SignalModel)
        base = StubStrategy()
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
        )
        assert ml_strat.ensemble_mode is False

    def test_name_prefix_unchanged(self):
        """Wrapped name should still start with ML_ regardless of model type."""
        for cls in [SignalModel, EnsembleSignalModel]:
            model = _mock_model(cls)
            base = StubStrategy()
            ml_strat = MLEnhancedStrategy(
                base_strategy=base,
                signal_model=model,
            )
            assert ml_strat.name.startswith("ML_")


# ---------------------------------------------------------------------------
# Test RegimeModelRouter with ensemble_mode
# ---------------------------------------------------------------------------

class TestRegimeModelRouterEnsemble:

    def test_ensemble_mode_passed_to_router(self):
        """When ml_sizing=True + ensemble_mode=True, router gets ensemble flag."""
        model = _mock_model(EnsembleSignalModel)
        base = StubStrategy(signals=[_make_signal()])
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
            ml_config={
                'ml_sizing': True,
                'ensemble_mode': True,
            },
        )
        assert ml_strat.regime_router is not None
        assert ml_strat.ensemble_mode is True

    def test_router_predict_delegates_to_default(self):
        """With no regime models loaded, router uses default."""
        model = _mock_model(EnsembleSignalModel)
        router = RegimeModelRouter(default_model=model, ensemble_mode=True)
        result = router.predict({'rsi_14': 50.0}, regime="bull")
        assert result['probability'] == 0.75
        model.predict.assert_called_once()


# ---------------------------------------------------------------------------
# Test backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:

    def test_existing_xgboost_workflow_unchanged(self):
        """MLEnhancedStrategy with SignalModel (no ensemble_mode) works as before."""
        prediction = {
            'prediction': 1, 'probability': 0.72, 'confidence': 0.44,
            'signal': 'bullish', 'signal_strength': 72.0,
            'timestamp': '2026-03-21T00:00:00+00:00',
        }
        model = _mock_model(SignalModel, prediction)
        base = StubStrategy(signals=[_make_signal()])
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
            ml_config={'confidence_threshold': 0.30},
        )
        snap = _make_market_snapshot()
        signals = ml_strat.generate_signals(snap)
        assert len(signals) == 1
        assert signals[0].metadata['ml_confidence'] == 0.44
        assert ml_strat.ensemble_mode is False

    def test_default_config_still_uses_xgboost(self):
        """Empty ml_config defaults to ensemble_mode=False."""
        model = _mock_model(SignalModel)
        base = StubStrategy()
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
        )
        assert ml_strat.ensemble_mode is False

    def test_stats_tracking_works_with_ensemble(self):
        """Stats tracking still works when using ensemble model."""
        model = _mock_model(EnsembleSignalModel)
        model.predict.side_effect = [
            {'prediction': 1, 'probability': 0.80, 'confidence': 0.60,
             'signal': 'bullish', 'signal_strength': 80.0,
             'timestamp': '2026-03-21T00:00:00+00:00'},
            {'prediction': 0, 'probability': 0.52, 'confidence': 0.04,
             'signal': 'neutral', 'signal_strength': 52.0,
             'timestamp': '2026-03-21T00:00:00+00:00'},
        ]
        base = StubStrategy(signals=[_make_signal(), _make_signal()])
        ml_strat = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=model,
            ml_config={'confidence_threshold': 0.30, 'ensemble_mode': True},
        )
        snap = _make_market_snapshot()
        ml_strat.generate_signals(snap)
        stats = ml_strat.get_ml_stats()
        assert stats['total_signals'] == 2
        assert stats['passed_signals'] == 1
        assert stats['filtered_signals'] == 1


# ---------------------------------------------------------------------------
# Helpers for real model save/load tests
# ---------------------------------------------------------------------------

def _train_and_save_dummy(model: SignalModel, tmpdir: str, filename: str):
    """Train a minimal SignalModel and save it."""
    rng = np.random.RandomState(42)
    features = pd.DataFrame({
        'f1': rng.randn(200),
        'f2': rng.randn(200),
        'f3': rng.randn(200),
    })
    labels = (features['f1'] > 0).astype(int).values
    model.train(features, labels, calibrate=False, save_model=False)
    model.save(filename)


def _train_and_save_dummy_ensemble(model: EnsembleSignalModel, tmpdir: str, filename: str):
    """Train a minimal EnsembleSignalModel and save it."""
    rng = np.random.RandomState(42)
    features = pd.DataFrame({
        'f1': rng.randn(200),
        'f2': rng.randn(200),
        'f3': rng.randn(200),
    })
    labels = (features['f1'] > 0).astype(int).values
    model.train(features, labels, calibrate=True, save_model=False)
    model.save(filename)
