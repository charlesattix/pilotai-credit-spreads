"""Tests for MLPipeline orchestrator."""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from ml.ml_pipeline import MLPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODULE = "ml.ml_pipeline"


def _mock_ml_prediction(probability=0.72, confidence=0.85, signal="buy"):
    return {
        "probability": probability,
        "confidence": confidence,
        "signal": signal,
    }


def _mock_event_scan(risk_score=0.1, events=None, recommendation="proceed"):
    return {
        "event_risk_score": risk_score,
        "events": events or [],
        "recommendation": recommendation,
    }


def _mock_iv_analysis(
    bull_put_favorable=True,
    bear_call_favorable=False,
    overall_signal="favorable_both",
    iv_rank_percentile=65,
):
    return {
        "signals": {
            "bull_put_favorable": bull_put_favorable,
            "bear_call_favorable": bear_call_favorable,
            "overall_signal": overall_signal,
        },
        "iv_rank_percentile": iv_rank_percentile,
    }


def _mock_regime(regime="low_vol_trending", confidence=0.80):
    return {"regime": regime, "confidence": confidence}


def _mock_features(iv_rank=60, vol_premium=0.02):
    return {"iv_rank": iv_rank, "vol_premium": vol_premium}


def _mock_position_sizing(recommended_size=0.05):
    return {"recommended_size": recommended_size}


def _make_options_chain():
    """Minimal options chain DataFrame for testing."""
    return pd.DataFrame(
        {
            "strike": [440, 445, 450, 455, 460],
            "type": ["put"] * 5,
            "bid": [1.0, 1.5, 2.0, 2.5, 3.0],
            "ask": [1.1, 1.6, 2.1, 2.6, 3.1],
            "delta": [-0.10, -0.12, -0.15, -0.20, -0.25],
            "iv": [0.18, 0.19, 0.20, 0.21, 0.22],
        }
    )


# ---------------------------------------------------------------------------
# Shared patch decorator for the six sub-components
# ---------------------------------------------------------------------------

def _patch_all_components():
    """Return a tuple of six patch decorators for all ML sub-components."""
    return (
        patch(f"{MODULE}.SentimentScanner"),
        patch(f"{MODULE}.PositionSizer"),
        patch(f"{MODULE}.SignalModel"),
        patch(f"{MODULE}.FeatureEngine"),
        patch(f"{MODULE}.IVAnalyzer"),
        patch(f"{MODULE}.RegimeDetector"),
    )


# When stacked, decorators inject mocks bottom-up so the parameter order is:
# RegimeDetector, IVAnalyzer, FeatureEngine, SignalModel, PositionSizer, SentimentScanner


def _build_pipeline(
    MockRegime,
    MockIV,
    MockFeature,
    MockSignal,
    MockSizer,
    MockSentiment,
    *,
    regime=None,
    iv_analysis=None,
    features=None,
    ml_prediction=None,
    event_scan=None,
    position_sizing=None,
    signal_trained=False,
    signal_load_returns=False,
    regime_trained=False,
):
    """Instantiate an MLPipeline with pre-configured mock returns."""

    # Regime detector
    regime_inst = MockRegime.return_value
    regime_inst.trained = regime_trained
    regime_inst.fit.return_value = True
    regime_inst.detect_regime.return_value = regime or _mock_regime()

    # IV analyzer
    iv_inst = MockIV.return_value
    iv_inst.analyze_surface.return_value = iv_analysis or _mock_iv_analysis()

    # Feature engine
    fe_inst = MockFeature.return_value
    fe_inst.build_features.return_value = features or _mock_features()
    fe_inst.compute_market_features.return_value = {}

    # Signal model
    sm_inst = MockSignal.return_value
    sm_inst.trained = signal_trained
    sm_inst.load.return_value = signal_load_returns
    sm_inst.predict.return_value = ml_prediction or _mock_ml_prediction()
    sm_inst.generate_synthetic_training_data.return_value = (
        pd.DataFrame({"a": [1, 2], "b": [3, 4]}),
        [1, 0],
    )
    sm_inst.train.return_value = {"test_accuracy": 0.70}

    # Position sizer
    ps_inst = MockSizer.return_value
    ps_inst.calculate_position_size.return_value = (
        position_sizing or _mock_position_sizing()
    )

    # Sentiment scanner
    ss_inst = MockSentiment.return_value
    ss_inst.scan.return_value = event_scan or _mock_event_scan()
    ss_inst.adjust_position_for_events.return_value = 0.04

    pipeline = MLPipeline(config={})
    return pipeline


# ---------------------------------------------------------------------------
# TestInitialize
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.SentimentScanner")
@patch(f"{MODULE}.PositionSizer")
@patch(f"{MODULE}.SignalModel")
@patch(f"{MODULE}.FeatureEngine")
@patch(f"{MODULE}.IVAnalyzer")
@patch(f"{MODULE}.RegimeDetector")
class TestInitialize:
    """Tests for MLPipeline.initialize()."""

    def test_trains_on_synthetic_when_no_saved_model(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """When signal_model.load() returns False, pipeline should train on synthetic data."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
            signal_trained=False,
            signal_load_returns=False,
            regime_trained=False,
        )

        result = pipeline.initialize()

        assert result is True
        assert pipeline.initialized is True

        sm = MockSignal.return_value
        sm.load.assert_called_once()
        sm.generate_synthetic_training_data.assert_called_once_with(
            n_samples=2000, win_rate=0.65
        )
        sm.train.assert_called_once()

        # Regime detector should also have been fitted
        MockRegime.return_value.fit.assert_called_once_with(force_retrain=False)

    def test_loads_existing_model(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """When signal_model.load() succeeds, no synthetic training should occur."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
            signal_trained=False,
            signal_load_returns=True,
            regime_trained=False,
        )

        result = pipeline.initialize()

        assert result is True
        assert pipeline.initialized is True

        sm = MockSignal.return_value
        sm.load.assert_called_once()
        sm.generate_synthetic_training_data.assert_not_called()
        sm.train.assert_not_called()

    def test_skips_regime_training_when_already_trained(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """If regime_detector.trained is True, fit() should not be called."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
            signal_trained=True,
            regime_trained=True,
        )

        pipeline.initialize()

        MockRegime.return_value.fit.assert_not_called()

    def test_force_retrain_retrains_regime(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """force_retrain=True should retrain regime even if already trained."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
            signal_trained=True,
            regime_trained=True,
        )

        pipeline.initialize(force_retrain=True)

        MockRegime.return_value.fit.assert_called_once_with(force_retrain=True)


# ---------------------------------------------------------------------------
# TestAnalyzeTrade
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.SentimentScanner")
@patch(f"{MODULE}.PositionSizer")
@patch(f"{MODULE}.SignalModel")
@patch(f"{MODULE}.FeatureEngine")
@patch(f"{MODULE}.IVAnalyzer")
@patch(f"{MODULE}.RegimeDetector")
class TestAnalyzeTrade:
    """Tests for MLPipeline.analyze_trade()."""

    def test_returns_complete_analysis(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """analyze_trade should return a dict with all expected top-level keys."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )
        pipeline.initialized = True

        result = pipeline.analyze_trade(
            ticker="SPY",
            current_price=450.0,
            options_chain=_make_options_chain(),
            spread_type="bull_put",
            expiration_date=datetime(2025, 7, 18, tzinfo=timezone.utc),
        )

        expected_keys = {
            "ticker",
            "spread_type",
            "timestamp",
            "regime",
            "iv_analysis",
            "features",
            "ml_prediction",
            "event_risk",
            "position_sizing",
            "enhanced_score",
            "recommendation",
        }
        assert expected_keys.issubset(result.keys())
        assert result["ticker"] == "SPY"
        assert result["spread_type"] == "bull_put"

    def test_uses_precomputed_regime(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """When regime= is provided, detect_regime() should NOT be called."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )
        pipeline.initialized = True

        precomputed = _mock_regime(regime="crisis", confidence=0.90)
        result = pipeline.analyze_trade(
            ticker="QQQ",
            current_price=380.0,
            options_chain=_make_options_chain(),
            spread_type="bear_call",
            regime=precomputed,
        )

        MockRegime.return_value.detect_regime.assert_not_called()
        assert result["regime"]["regime"] == "crisis"

    def test_fallback_on_exception(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """If an internal exception occurs, _get_default_analysis is returned."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )
        pipeline.initialized = True

        # Make IV analyzer raise
        MockIV.return_value.analyze_surface.side_effect = RuntimeError("boom")

        result = pipeline.analyze_trade(
            ticker="AAPL",
            current_price=175.0,
            options_chain=_make_options_chain(),
            spread_type="bull_put",
        )

        assert result["error"] is True
        assert result["ticker"] == "AAPL"
        assert result["spread_type"] == "bull_put"
        assert result["recommendation"]["action"] == "pass"
        assert result["enhanced_score"] == 50.0

    def test_calls_all_subcomponents(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """All sub-components should be called during a normal analysis."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )
        pipeline.initialized = True

        pipeline.analyze_trade(
            ticker="IWM",
            current_price=200.0,
            options_chain=_make_options_chain(),
            spread_type="bull_put",
            expiration_date=datetime(2025, 8, 15, tzinfo=timezone.utc),
            technical_signals={"trend": "up"},
            current_positions=[],
        )

        MockRegime.return_value.detect_regime.assert_called_once()
        MockIV.return_value.analyze_surface.assert_called_once()
        MockFeature.return_value.build_features.assert_called_once()
        MockSignal.return_value.predict.assert_called_once()
        MockSentiment.return_value.scan.assert_called_once()
        MockSizer.return_value.calculate_position_size.assert_called_once()
        MockSentiment.return_value.adjust_position_for_events.assert_called_once()

    def test_auto_initializes_when_not_initialized(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """If pipeline.initialized is False, analyze_trade should call initialize()."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
            signal_trained=False,
            signal_load_returns=True,
            regime_trained=True,
        )
        assert pipeline.initialized is False

        result = pipeline.analyze_trade(
            ticker="SPY",
            current_price=450.0,
            options_chain=_make_options_chain(),
            spread_type="bull_put",
        )

        # After auto-init, the pipeline should be initialized
        assert pipeline.initialized is True
        assert "ticker" in result


# ---------------------------------------------------------------------------
# TestBatchAnalyze
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.SentimentScanner")
@patch(f"{MODULE}.PositionSizer")
@patch(f"{MODULE}.SignalModel")
@patch(f"{MODULE}.FeatureEngine")
@patch(f"{MODULE}.IVAnalyzer")
@patch(f"{MODULE}.RegimeDetector")
class TestBatchAnalyze:
    """Tests for MLPipeline.batch_analyze()."""

    def test_empty_input_returns_empty_list(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Passing an empty list should return an empty list."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )
        pipeline.initialized = True

        result = pipeline.batch_analyze([], current_positions=[])
        assert result == []

    def test_regime_computed_once(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Regime detection should be called exactly once for batch, not per opportunity."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )
        pipeline.initialized = True

        opps = [
            {
                "ticker": "SPY",
                "current_price": 450.0,
                "options_chain": _make_options_chain(),
                "type": "bull_put",
            },
            {
                "ticker": "QQQ",
                "current_price": 380.0,
                "options_chain": _make_options_chain(),
                "type": "bear_call",
            },
            {
                "ticker": "IWM",
                "current_price": 200.0,
                "options_chain": _make_options_chain(),
                "type": "bull_put",
            },
        ]

        pipeline.batch_analyze(opps, current_positions=[])

        # detect_regime is called once at the batch level, then the pre-computed
        # regime is passed into each analyze_trade call.  analyze_trade itself
        # should NOT call detect_regime because `regime=` is provided.
        # However the total call count is 1 (batch) + 0 (per-trade) = 1.
        # The per-trade calls use the passed-in regime, but we still need to
        # account that analyze_trade *may* add calls if regime is not passed.
        # Since batch_analyze passes `regime=regime_data`, per-trade calls skip
        # detect_regime. So the total should be exactly 1.
        assert MockRegime.return_value.detect_regime.call_count == 1

    def test_results_sorted_by_enhanced_score_desc(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Batch results should be sorted by enhanced_score descending."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )
        pipeline.initialized = True

        opps = [
            {
                "ticker": "SPY",
                "current_price": 450.0,
                "options_chain": _make_options_chain(),
                "type": "bull_put",
            },
            {
                "ticker": "QQQ",
                "current_price": 380.0,
                "options_chain": _make_options_chain(),
                "type": "bull_put",
            },
        ]

        results = pipeline.batch_analyze(opps, current_positions=[])

        scores = [r.get("enhanced_score", 0) for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_batch_analyze_returns_enhanced_opportunities(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Each returned opportunity should have analysis keys merged in."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )
        pipeline.initialized = True

        opps = [
            {
                "ticker": "SPY",
                "current_price": 450.0,
                "options_chain": _make_options_chain(),
                "type": "bull_put",
            },
        ]

        results = pipeline.batch_analyze(opps, current_positions=[])

        assert len(results) == 1
        r = results[0]
        # Should have both original keys and analysis keys
        assert r["ticker"] == "SPY"
        assert "enhanced_score" in r
        assert "recommendation" in r


# ---------------------------------------------------------------------------
# TestEnhancedScore
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.SentimentScanner")
@patch(f"{MODULE}.PositionSizer")
@patch(f"{MODULE}.SignalModel")
@patch(f"{MODULE}.FeatureEngine")
@patch(f"{MODULE}.IVAnalyzer")
@patch(f"{MODULE}.RegimeDetector")
class TestEnhancedScore:
    """Tests for MLPipeline._calculate_enhanced_score()."""

    def test_score_in_0_100_range(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Enhanced score must always be between 0 and 100."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        analysis = {
            "ml_prediction": _mock_ml_prediction(probability=0.80, confidence=0.90),
            "regime": _mock_regime(regime="low_vol_trending"),
            "iv_analysis": _mock_iv_analysis(),
            "spread_type": "bull_put",
            "event_risk": _mock_event_scan(risk_score=0.05),
            "features": _mock_features(iv_rank=75, vol_premium=0.03),
        }

        score = pipeline._calculate_enhanced_score(analysis)

        assert 0 <= score <= 100

    def test_crisis_regime_reduces_score(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """A 'crisis' regime should result in a lower score than 'low_vol_trending'."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        base_analysis = {
            "ml_prediction": _mock_ml_prediction(probability=0.65, confidence=0.70),
            "iv_analysis": _mock_iv_analysis(overall_signal="neutral"),
            "spread_type": "bull_put",
            "event_risk": _mock_event_scan(risk_score=0.0),
            "features": _mock_features(iv_rank=50, vol_premium=0.0),
        }

        # Score in favorable regime
        favorable = {**base_analysis, "regime": _mock_regime(regime="low_vol_trending")}
        score_favorable = pipeline._calculate_enhanced_score(favorable)

        # Score in crisis regime
        crisis = {**base_analysis, "regime": _mock_regime(regime="crisis")}
        score_crisis = pipeline._calculate_enhanced_score(crisis)

        assert score_crisis < score_favorable

    def test_high_iv_rank_bonus(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Features with iv_rank > 70 should produce a higher score."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        base_analysis = {
            "ml_prediction": _mock_ml_prediction(probability=0.60, confidence=0.70),
            "regime": _mock_regime(regime="mean_reverting"),
            "iv_analysis": _mock_iv_analysis(overall_signal="neutral"),
            "spread_type": "bull_put",
            "event_risk": _mock_event_scan(risk_score=0.0),
        }

        low_iv = {**base_analysis, "features": _mock_features(iv_rank=40, vol_premium=0.0)}
        high_iv = {**base_analysis, "features": _mock_features(iv_rank=80, vol_premium=0.0)}

        score_low = pipeline._calculate_enhanced_score(low_iv)
        score_high = pipeline._calculate_enhanced_score(high_iv)

        assert score_high > score_low

    def test_extreme_inputs_clamped(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Even with extreme values, score should be clamped to 0-100."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        # Very unfavorable scenario
        bad_analysis = {
            "ml_prediction": _mock_ml_prediction(probability=0.10, confidence=1.0),
            "regime": _mock_regime(regime="crisis"),
            "iv_analysis": _mock_iv_analysis(overall_signal="unfavorable"),
            "spread_type": "bull_put",
            "event_risk": _mock_event_scan(risk_score=1.0),
            "features": _mock_features(iv_rank=10, vol_premium=-0.05),
        }
        score_bad = pipeline._calculate_enhanced_score(bad_analysis)
        assert score_bad >= 0

        # Very favorable scenario
        good_analysis = {
            "ml_prediction": _mock_ml_prediction(probability=0.99, confidence=1.0),
            "regime": _mock_regime(regime="low_vol_trending"),
            "iv_analysis": _mock_iv_analysis(
                bull_put_favorable=True, overall_signal="favorable_both"
            ),
            "spread_type": "bull_put",
            "event_risk": _mock_event_scan(risk_score=0.0),
            "features": _mock_features(iv_rank=95, vol_premium=0.10),
        }
        score_good = pipeline._calculate_enhanced_score(good_analysis)
        assert score_good <= 100

    def test_vol_premium_bonus(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Positive vol_premium should add to the score."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        base = {
            "ml_prediction": _mock_ml_prediction(probability=0.60, confidence=0.70),
            "regime": _mock_regime(regime="mean_reverting"),
            "iv_analysis": _mock_iv_analysis(overall_signal="neutral"),
            "spread_type": "bull_put",
            "event_risk": _mock_event_scan(risk_score=0.0),
        }

        no_premium = {**base, "features": _mock_features(iv_rank=50, vol_premium=-0.01)}
        with_premium = {**base, "features": _mock_features(iv_rank=50, vol_premium=0.05)}

        score_no = pipeline._calculate_enhanced_score(no_premium)
        score_yes = pipeline._calculate_enhanced_score(with_premium)

        assert score_yes > score_no


# ---------------------------------------------------------------------------
# TestRecommendation
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.SentimentScanner")
@patch(f"{MODULE}.PositionSizer")
@patch(f"{MODULE}.SignalModel")
@patch(f"{MODULE}.FeatureEngine")
@patch(f"{MODULE}.IVAnalyzer")
@patch(f"{MODULE}.RegimeDetector")
class TestRecommendation:
    """Tests for MLPipeline._generate_recommendation()."""

    def _make_analysis(self, score, ml_prob=0.70, event_rec="proceed", position_size=0.05):
        return {
            "enhanced_score": score,
            "ml_prediction": _mock_ml_prediction(probability=ml_prob),
            "event_risk": _mock_event_scan(recommendation=event_rec, events=[]),
            "position_sizing": {
                "recommended_size": position_size,
                "event_adjusted_size": position_size,
            },
            "regime": _mock_regime(),
        }

    def test_strong_buy_classification(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Score >= 75 with proceed event_rec should yield 'strong_buy'."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        analysis = self._make_analysis(score=80, event_rec="proceed")
        rec = pipeline._generate_recommendation(analysis)

        assert rec["action"] == "strong_buy"
        assert rec["confidence"] == "high"

    def test_strong_buy_with_proceed_reduced(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Score >= 75 with proceed_reduced event_rec should still yield 'strong_buy'."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        analysis = self._make_analysis(score=78, event_rec="proceed_reduced")
        rec = pipeline._generate_recommendation(analysis)

        assert rec["action"] == "strong_buy"

    def test_buy_classification(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Score >= 60 (but < 75) with non-avoid event_rec should yield 'buy'."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        analysis = self._make_analysis(score=65, event_rec="proceed")
        rec = pipeline._generate_recommendation(analysis)

        assert rec["action"] == "buy"
        assert rec["confidence"] == "medium"

    def test_consider_classification(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Score >= 50 (but < 60) with proceed event_rec should yield 'consider'."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        analysis = self._make_analysis(score=55, event_rec="proceed")
        rec = pipeline._generate_recommendation(analysis)

        assert rec["action"] == "consider"
        assert rec["confidence"] == "low"

    def test_pass_on_low_score(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Score < 50 should yield 'pass'."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        analysis = self._make_analysis(score=40, event_rec="proceed")
        rec = pipeline._generate_recommendation(analysis)

        assert rec["action"] == "pass"
        assert rec["confidence"] == "low"

    def test_pass_on_avoid_event(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Score >= 60 but event_rec='avoid' should still yield 'pass' (not buy)."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        analysis = self._make_analysis(score=70, event_rec="avoid")
        rec = pipeline._generate_recommendation(analysis)

        # 70 < 75 so strong_buy doesn't apply; buy requires event_rec != 'avoid'
        # consider requires event_rec == 'proceed'; so it falls to pass
        assert rec["action"] == "pass"

    def test_recommendation_contains_expected_keys(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Recommendation dict should contain all required keys."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        analysis = self._make_analysis(score=75, event_rec="proceed")
        rec = pipeline._generate_recommendation(analysis)

        assert "action" in rec
        assert "confidence" in rec
        assert "score" in rec
        assert "position_size" in rec
        assert "reasoning" in rec
        assert "ml_probability" in rec
        assert isinstance(rec["reasoning"], list)

    def test_recommendation_includes_ml_probability(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """ml_probability in recommendation should match the input ml prediction."""
        pipeline = _build_pipeline(
            MockRegime,
            MockIV,
            MockFeature,
            MockSignal,
            MockSizer,
            MockSentiment,
        )

        analysis = self._make_analysis(score=80, ml_prob=0.82, event_rec="proceed")
        rec = pipeline._generate_recommendation(analysis)

        assert rec["ml_probability"] == 0.82


@patch(f"{MODULE}.SentimentScanner")
@patch(f"{MODULE}.PositionSizer")
@patch(f"{MODULE}.SignalModel")
@patch(f"{MODULE}.FeatureEngine")
@patch(f"{MODULE}.IVAnalyzer")
@patch(f"{MODULE}.RegimeDetector")
class TestRegimeDirectionMismatch:
    """Regime-direction mismatch should penalize the enhanced score."""

    def test_mean_reverting_high_confidence_penalizes_directional(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """mean_reverting at >95% confidence should reduce score for directional spreads."""
        pipeline = _build_pipeline(
            MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment,
        )

        base = {
            "ml_prediction": _mock_ml_prediction(probability=0.65, confidence=0.70),
            "iv_analysis": _mock_iv_analysis(overall_signal="neutral"),
            "event_risk": _mock_event_scan(risk_score=0.0),
            "features": _mock_features(iv_rank=50, vol_premium=0.0),
        }

        # Score with low-confidence mean_reverting (no penalty)
        low_conf = {**base, "spread_type": "bull_put", "regime": _mock_regime("mean_reverting", 0.60)}
        score_low_conf = pipeline._calculate_enhanced_score(low_conf)

        # Score with high-confidence mean_reverting (penalty applied)
        high_conf = {**base, "spread_type": "bull_put", "regime": _mock_regime("mean_reverting", 0.97)}
        score_high_conf = pipeline._calculate_enhanced_score(high_conf)

        assert score_high_conf < score_low_conf

    def test_no_penalty_below_95_confidence(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """No mismatch penalty when regime confidence is below 95%."""
        pipeline = _build_pipeline(
            MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment,
        )

        analysis = {
            "ml_prediction": _mock_ml_prediction(probability=0.65, confidence=0.70),
            "iv_analysis": _mock_iv_analysis(overall_signal="neutral"),
            "event_risk": _mock_event_scan(risk_score=0.0),
            "features": _mock_features(iv_rank=50, vol_premium=0.0),
            "spread_type": "bear_call",
            "regime": _mock_regime("mean_reverting", 0.90),
        }

        # Should get the base score + 5 for mean_reverting, no penalty
        score = pipeline._calculate_enhanced_score(analysis)
        # mean_reverting normally adds 5. If penalty were applied, score would be lower.
        # With 0.90 confidence, no penalty should apply.
        # ml contribution: (0.65-0.5)*2*40*0.70 = 8.4
        # regime: +5
        # expected roughly 50 + 8.4 + 5 = 63.4
        assert score > 60  # no penalty applied

    def test_crisis_with_high_confidence_penalizes(
        self, MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment
    ):
        """Crisis regime at >95% confidence should further penalize directional spreads."""
        pipeline = _build_pipeline(
            MockRegime, MockIV, MockFeature, MockSignal, MockSizer, MockSentiment,
        )

        base = {
            "ml_prediction": _mock_ml_prediction(probability=0.65, confidence=0.70),
            "iv_analysis": _mock_iv_analysis(overall_signal="neutral"),
            "event_risk": _mock_event_scan(risk_score=0.0),
            "features": _mock_features(iv_rank=50, vol_premium=0.0),
        }

        # Crisis at 80% confidence
        crisis_80 = {**base, "spread_type": "bull_put", "regime": _mock_regime("crisis", 0.80)}
        score_80 = pipeline._calculate_enhanced_score(crisis_80)

        # Crisis at 98% confidence (should get additional mismatch penalty)
        crisis_98 = {**base, "spread_type": "bull_put", "regime": _mock_regime("crisis", 0.98)}
        score_98 = pipeline._calculate_enhanced_score(crisis_98)

        assert score_98 < score_80
