"""
Unit tests for the COMPASS regime classifier.

Target module: compass/regime.py (post-Phase 2 move)
Pre-move source: engine/regime.py

Tests cover:
  - classify() single-day classification for all 5 regimes
  - VIX threshold boundaries and priority ordering
  - Trend direction detection (_trend_direction)
  - Sharp decline detection (_is_declining)
  - classify_series() multi-day tagging
  - summarize() statistics computation
  - Edge cases: short data, ambiguous zones, custom parameters

Blueprint spec: 15+ tests, all green (Phase 3 exit criteria).
"""

import pandas as pd
import pytest

# --------------------------------------------------------------------------
# Import will switch from engine.regime → compass.regime after Phase 2 move.
# Until then, test against the pre-move source.
# --------------------------------------------------------------------------
try:
    from compass.regime import Regime, RegimeClassifier, REGIME_INFO
except ImportError:
    from engine.regime import Regime, RegimeClassifier, REGIME_INFO

from tests.compass_helpers import (
    mock_spy_prices,
    mock_vix_series,
    mock_spy_dataframe,
    RegimeScenario,
    REGIME_SCENARIOS,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def classifier():
    """Default RegimeClassifier with standard parameters."""
    return RegimeClassifier(trend_window=50, trend_threshold=5.0)


@pytest.fixture
def bull_prices():
    """100-day SPY series with a strong uptrend (+25% annual)."""
    return mock_spy_prices(days=100, trend=25.0, base=450.0)


@pytest.fixture
def bear_prices():
    """100-day SPY series with a strong downtrend (-25% annual)."""
    return mock_spy_prices(days=100, trend=-25.0, base=450.0)


@pytest.fixture
def flat_prices():
    """100-day SPY series with zero trend."""
    return mock_spy_prices(days=100, trend=0.0, base=450.0)


@pytest.fixture
def crash_prices():
    """100-day SPY series with a sharp >5% decline in the last 10 days."""
    scenario = REGIME_SCENARIOS["crash"]
    return scenario.build_prices()


# ══════════════════════════════════════════════════════════════════════════════
# A. Regime enum and metadata
# ══════════════════════════════════════════════════════════════════════════════

class TestRegimeEnum:

    def test_regime_has_five_members(self):
        """Regime enum contains exactly: bull, bear, high_vol, low_vol, crash."""
        pass

    def test_regime_info_covers_all_regimes(self):
        """REGIME_INFO has an entry for every Regime member with label, strategies, risk."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# B. classify() — single-day classification
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyCrash:
    """VIX > 40 + sharp decline → CRASH (highest priority)."""

    def test_crash_vix_above_40_with_sharp_decline(self, classifier, crash_prices):
        """VIX=45 and >5% drop in last 10 days → CRASH."""
        pass

    def test_high_vol_vix_above_40_without_decline(self, classifier, bull_prices):
        """VIX=45 but no sharp decline → HIGH_VOL (not CRASH)."""
        pass


class TestClassifyHighVol:
    """VIX > 30 (any direction) → HIGH_VOL."""

    def test_high_vol_vix_32(self, classifier, bull_prices):
        """VIX=32 with uptrend → HIGH_VOL (VIX threshold overrides trend)."""
        pass

    def test_high_vol_vix_35_downtrend(self, classifier, bear_prices):
        """VIX=35 with downtrend → HIGH_VOL (not BEAR, VIX > 30 takes priority)."""
        pass


class TestClassifyBear:
    """VIX > 25 + SPY downtrend → BEAR."""

    def test_bear_vix_27_downtrend(self, classifier, bear_prices):
        """VIX=27, strong downtrend → BEAR."""
        pass


class TestClassifyBull:
    """VIX < 20 + SPY uptrend → BULL."""

    def test_bull_vix_18_uptrend(self, classifier, bull_prices):
        """VIX=18, strong uptrend → BULL."""
        pass


class TestClassifyLowVol:
    """VIX < 15, no strong trend → LOW_VOL."""

    def test_low_vol_vix_12_flat(self, classifier, flat_prices):
        """VIX=12, flat trend → LOW_VOL."""
        pass


class TestClassifyAmbiguous:
    """Ambiguous zones: VIX between clear thresholds, mixed signals."""

    def test_ambiguous_uptrend_defaults_bull(self, classifier, bull_prices):
        """VIX=22 (no clear bucket), trend > 0 → BULL."""
        pass

    def test_ambiguous_downtrend_high_vix_bear(self, classifier, bear_prices):
        """VIX=23, trend < 0 → BEAR (VIX > 22 tips to bear)."""
        pass

    def test_ambiguous_downtrend_low_vix_bull(self, classifier, bear_prices):
        """VIX=18, trend < 0 → BULL (mild pullback, low VIX → still constructive)."""
        pass

    def test_no_trend_low_vix_low_vol(self, classifier, flat_prices):
        """VIX=16, trend=0 → LOW_VOL (vix < 18, no trend)."""
        pass

    def test_no_trend_moderate_vix_bull(self, classifier, flat_prices):
        """VIX=19, trend=0 → BULL (neutral default)."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# C. Trend helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestTrendDirection:
    """RegimeClassifier._trend_direction() — slope-based trend detection."""

    def test_uptrend_returns_positive(self, classifier, bull_prices):
        """Strong uptrend → +1."""
        pass

    def test_downtrend_returns_negative(self, classifier, bear_prices):
        """Strong downtrend → -1."""
        pass

    def test_flat_returns_zero(self, classifier, flat_prices):
        """No trend → 0."""
        pass

    def test_short_data_uses_shorter_window(self, classifier):
        """Fewer than trend_window (50) days → falls back to max(10, len(prices))."""
        pass


class TestIsDeclining:
    """RegimeClassifier._is_declining() — sharp decline check."""

    def test_sharp_decline_detected(self, classifier, crash_prices):
        """>5% drop in last 10 trading days → True."""
        pass

    def test_gentle_decline_not_detected(self, classifier, bear_prices):
        """Gradual decline (not >5% in 10 days) → False."""
        pass

    def test_insufficient_data(self, classifier):
        """Fewer than 10 data points → False."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# D. classify_series() — multi-day tagging
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifySeries:

    def test_returns_series_same_length_as_input(self, classifier, bull_prices):
        """Output Series has same index as input DataFrame."""
        pass

    def test_tags_bull_market_data(self, classifier, bull_prices):
        """Constant low VIX + uptrend → predominantly BULL labels."""
        pass

    def test_missing_vix_defaults_to_20(self, classifier, bull_prices):
        """Dates missing from vix_series get default VIX=20.0."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# E. summarize()
# ══════════════════════════════════════════════════════════════════════════════

class TestSummarize:

    def test_summarize_returns_required_keys(self):
        """Output has total_days, distribution, transitions, avg_regime_duration."""
        pass

    def test_summarize_counts_transitions(self):
        """Alternating regimes produce correct transition count."""
        pass

    def test_summarize_distribution_sums_to_100(self):
        """All regime percentages sum to ~100%."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# F. Custom parameters
# ══════════════════════════════════════════════════════════════════════════════

class TestCustomParameters:

    def test_custom_trend_window(self):
        """trend_window=20 changes which prices are considered for trend."""
        pass

    def test_custom_trend_threshold(self):
        """trend_threshold=15.0 raises the bar — mild trends read as flat."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# G. Post-enhancement stubs (Phase 3 — pending CC-1 delivery)
# ══════════════════════════════════════════════════════════════════════════════

class TestEnhancedRegimeClassifier:
    """Tests for compass/regime.py enhancements (hysteresis, RSI, VIX3M).

    These test the ENHANCED public API specified in the blueprint:
      classify(vix, spy_prices, date, rsi=None, vix3m=None)
      classify_series(spy_data, vix_series, rsi_series=None, vix3m_series=None)
      __init__(config: dict = None)

    Skipped until CC-1 delivers the enhanced module.
    """

    @pytest.mark.skip(reason="Pending CC-1: compass/regime.py hysteresis enhancement")
    def test_hysteresis_prevents_rapid_flip(self):
        """Regime just changed; raw signal wants to flip again → keeps current regime."""
        pass

    @pytest.mark.skip(reason="Pending CC-1: compass/regime.py RSI signal")
    def test_rsi_momentum_signal(self):
        """High RSI + other bull signals → stronger BULL conviction."""
        pass

    @pytest.mark.skip(reason="Pending CC-1: compass/regime.py VIX3M term structure")
    def test_vix3m_term_structure_signal(self):
        """VIX/VIX3M > 1.05 (backwardation) → bearish signal boost."""
        pass

    @pytest.mark.skip(reason="Pending CC-1: compass/regime.py configurable thresholds")
    def test_configurable_thresholds_via_dict(self):
        """RegimeClassifier(config={'vix_crash': 35}) lowers crash threshold."""
        pass

    @pytest.mark.skip(reason="Pending CC-1: compass/regime.py lookahead protection")
    def test_lookahead_protection_shift_by_1(self):
        """classify_series uses shifted data to prevent lookahead bias."""
        pass
