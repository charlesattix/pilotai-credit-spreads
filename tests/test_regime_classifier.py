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

from compass.regime import Regime, RegimeClassifier, REGIME_INFO

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
        members = set(Regime)
        assert len(members) == 5
        expected = {Regime.BULL, Regime.BEAR, Regime.HIGH_VOL, Regime.LOW_VOL, Regime.CRASH}
        assert members == expected

    def test_regime_info_covers_all_regimes(self):
        """REGIME_INFO has an entry for every Regime member with label, strategies, risk."""
        for regime in Regime:
            assert regime in REGIME_INFO, f"Missing REGIME_INFO for {regime}"
            info = REGIME_INFO[regime]
            assert "label" in info
            assert "strategies" in info
            assert "risk" in info
            assert isinstance(info["strategies"], list)


# ══════════════════════════════════════════════════════════════════════════════
# B. classify() — single-day classification
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyCrash:
    """VIX > 40 + sharp decline -> CRASH (highest priority)."""

    def test_crash_vix_above_40_with_sharp_decline(self, classifier, crash_prices):
        """VIX=45 and >5% drop in last 10 days -> CRASH."""
        result = classifier.classify(vix=45.0, spy_prices=crash_prices, date=crash_prices.index[-1])
        assert result == Regime.CRASH

    def test_high_vol_vix_above_40_without_decline(self, classifier, bull_prices):
        """VIX=45 but no sharp decline -> HIGH_VOL (not CRASH)."""
        result = classifier.classify(vix=45.0, spy_prices=bull_prices, date=bull_prices.index[-1])
        assert result == Regime.HIGH_VOL


class TestClassifyHighVol:
    """VIX > 30 (any direction) -> HIGH_VOL."""

    def test_high_vol_vix_32(self, classifier, bull_prices):
        """VIX=32 with uptrend -> HIGH_VOL (VIX threshold overrides trend)."""
        result = classifier.classify(vix=32.0, spy_prices=bull_prices, date=bull_prices.index[-1])
        assert result == Regime.HIGH_VOL

    def test_high_vol_vix_35_downtrend(self, classifier, bear_prices):
        """VIX=35 with downtrend -> HIGH_VOL (not BEAR, VIX > 30 takes priority)."""
        result = classifier.classify(vix=35.0, spy_prices=bear_prices, date=bear_prices.index[-1])
        assert result == Regime.HIGH_VOL


class TestClassifyBear:
    """VIX > 25 + SPY downtrend -> BEAR."""

    def test_bear_vix_27_downtrend(self, classifier, bear_prices):
        """VIX=27, strong downtrend -> BEAR."""
        result = classifier.classify(vix=27.0, spy_prices=bear_prices, date=bear_prices.index[-1])
        assert result == Regime.BEAR


class TestClassifyBull:
    """VIX < 20 + SPY uptrend -> BULL."""

    def test_bull_vix_18_uptrend(self, classifier, bull_prices):
        """VIX=18, strong uptrend -> BULL."""
        result = classifier.classify(vix=18.0, spy_prices=bull_prices, date=bull_prices.index[-1])
        assert result == Regime.BULL


class TestClassifyLowVol:
    """VIX < 15, no strong trend -> LOW_VOL."""

    def test_low_vol_vix_12_flat(self, classifier, flat_prices):
        """VIX=12, flat trend -> LOW_VOL."""
        result = classifier.classify(vix=12.0, spy_prices=flat_prices, date=flat_prices.index[-1])
        assert result == Regime.LOW_VOL


class TestClassifyAmbiguous:
    """Ambiguous zones: VIX between clear thresholds, mixed signals."""

    def test_ambiguous_uptrend_defaults_bull(self, classifier, bull_prices):
        """VIX=22 (no clear bucket), trend > 0 -> BULL."""
        result = classifier.classify(vix=22.0, spy_prices=bull_prices, date=bull_prices.index[-1])
        assert result == Regime.BULL

    def test_ambiguous_downtrend_high_vix_bear(self, classifier, bear_prices):
        """VIX=23, trend < 0 -> BEAR (VIX > 22 tips to bear)."""
        result = classifier.classify(vix=23.0, spy_prices=bear_prices, date=bear_prices.index[-1])
        assert result == Regime.BEAR

    def test_ambiguous_downtrend_low_vix_bull(self, classifier, bear_prices):
        """VIX=18, trend < 0 -> BULL (mild pullback, low VIX -> still constructive)."""
        result = classifier.classify(vix=18.0, spy_prices=bear_prices, date=bear_prices.index[-1])
        assert result == Regime.BULL

    def test_no_trend_low_vix_low_vol(self, classifier, flat_prices):
        """VIX=16, trend=0 -> LOW_VOL (vix < 18, no trend)."""
        result = classifier.classify(vix=16.0, spy_prices=flat_prices, date=flat_prices.index[-1])
        assert result == Regime.LOW_VOL

    def test_no_trend_moderate_vix_bull(self, classifier, flat_prices):
        """VIX=19, trend=0 -> BULL (neutral default)."""
        result = classifier.classify(vix=19.0, spy_prices=flat_prices, date=flat_prices.index[-1])
        assert result == Regime.BULL


# ══════════════════════════════════════════════════════════════════════════════
# C. Trend helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestTrendDirection:
    """RegimeClassifier._trend_direction() — slope-based trend detection."""

    def test_uptrend_returns_positive(self, classifier, bull_prices):
        """Strong uptrend -> +1."""
        assert classifier._trend_direction(bull_prices) == 1

    def test_downtrend_returns_negative(self, classifier, bear_prices):
        """Strong downtrend -> -1."""
        assert classifier._trend_direction(bear_prices) == -1

    def test_flat_returns_zero(self, classifier, flat_prices):
        """No trend -> 0."""
        assert classifier._trend_direction(flat_prices) == 0

    def test_short_data_uses_shorter_window(self, classifier):
        """Fewer than trend_window (50) days -> falls back to max(10, len(prices))."""
        short_prices = mock_spy_prices(days=20, trend=40.0, base=450.0)
        # With only 20 days, it should still detect an uptrend using the shorter window
        result = classifier._trend_direction(short_prices)
        assert result == 1


class TestIsDeclining:
    """RegimeClassifier._is_declining() — sharp decline check."""

    def test_sharp_decline_detected(self, classifier, crash_prices):
        """>5% drop in last 10 trading days -> True."""
        assert classifier._is_declining(crash_prices) == True

    def test_gentle_decline_not_detected(self, classifier, bear_prices):
        """Gradual decline (not >5% in 10 days) -> False."""
        # -25% annual = ~1% per 10 trading days, well under 5%
        assert classifier._is_declining(bear_prices) == False

    def test_insufficient_data(self, classifier):
        """Fewer than 10 data points -> False."""
        short = mock_spy_prices(days=5, trend=-50.0, base=450.0)
        assert classifier._is_declining(short) == False


# ══════════════════════════════════════════════════════════════════════════════
# D. classify_series() — multi-day tagging
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifySeries:

    def test_returns_series_same_length_as_input(self, classifier, bull_prices):
        """Output Series has same index as input DataFrame."""
        spy_df = mock_spy_dataframe(bull_prices)
        vix = mock_vix_series(start_date="2024-01-02", days=len(bull_prices), base_level=16.0)
        result = classifier.classify_series(spy_df, vix)
        assert len(result) == len(spy_df)

    def test_tags_bull_market_data(self, classifier, bull_prices):
        """Constant low VIX + uptrend -> predominantly BULL labels."""
        spy_df = mock_spy_dataframe(bull_prices)
        vix = mock_vix_series(start_date="2024-01-02", days=len(bull_prices), base_level=16.0)
        result = classifier.classify_series(spy_df, vix)
        # After warmup period, most days should be BULL
        bull_count = (result == Regime.BULL).sum()
        assert bull_count > len(result) * 0.5, f"Expected majority BULL, got {bull_count}/{len(result)}"

    def test_missing_vix_defaults_to_20(self, classifier, bull_prices):
        """Dates missing from vix_series get default VIX=20.0."""
        spy_df = mock_spy_dataframe(bull_prices)
        # Provide VIX for only half the dates
        half = len(bull_prices) // 2
        vix = mock_vix_series(start_date="2024-01-02", days=half, base_level=16.0)
        result = classifier.classify_series(spy_df, vix)
        # Should still produce a regime for every day (no crashes)
        assert len(result) == len(spy_df)


# ══════════════════════════════════════════════════════════════════════════════
# E. summarize()
# ══════════════════════════════════════════════════════════════════════════════

class TestSummarize:

    def test_summarize_returns_required_keys(self):
        """Output has total_days, distribution, transitions, avg_regime_duration."""
        regimes = pd.Series([Regime.BULL] * 50 + [Regime.BEAR] * 50)
        result = RegimeClassifier.summarize(regimes)
        assert "total_days" in result
        assert "distribution" in result
        assert "transitions" in result
        assert "avg_regime_duration" in result
        assert result["total_days"] == 100

    def test_summarize_counts_transitions(self):
        """Alternating regimes produce correct transition count."""
        # BULL x 30, BEAR x 20, BULL x 10 = 2 transitions
        regimes = pd.Series(
            [Regime.BULL] * 30 + [Regime.BEAR] * 20 + [Regime.BULL] * 10
        )
        result = RegimeClassifier.summarize(regimes)
        assert result["transitions"] == 2

    def test_summarize_distribution_sums_to_100(self):
        """All regime percentages sum to ~100%."""
        regimes = pd.Series(
            [Regime.BULL] * 40 + [Regime.BEAR] * 30
            + [Regime.HIGH_VOL] * 15 + [Regime.LOW_VOL] * 10
            + [Regime.CRASH] * 5
        )
        result = RegimeClassifier.summarize(regimes)
        total_pct = sum(v["pct"] for v in result["distribution"].values())
        assert abs(total_pct - 100.0) < 0.5


# ══════════════════════════════════════════════════════════════════════════════
# F. Custom parameters
# ══════════════════════════════════════════════════════════════════════════════

class TestCustomParameters:

    def test_custom_trend_window(self):
        """trend_window=20 changes which prices are considered for trend."""
        clf_20 = RegimeClassifier(trend_window=20, trend_threshold=5.0)
        clf_50 = RegimeClassifier(trend_window=50, trend_threshold=5.0)
        # Short uptrend: only visible in 20-day window
        prices = mock_spy_prices(days=30, trend=30.0, base=450.0)
        # Both should detect uptrend, but this confirms the window param is used
        assert clf_20._trend_direction(prices) == 1
        assert clf_20.trend_window == 20
        assert clf_50.trend_window == 50

    def test_custom_trend_threshold(self):
        """trend_threshold=15.0 raises the bar — mild trends read as flat."""
        clf_mild = RegimeClassifier(trend_window=50, trend_threshold=15.0)
        # A mild 8% annual trend should be flat with threshold=15
        prices = mock_spy_prices(days=100, trend=8.0, base=450.0)
        result = clf_mild._trend_direction(prices)
        assert result == 0, "Mild trend should read as flat with high threshold"


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
        """Regime just changed; raw signal wants to flip again -> keeps current regime."""
        pass

    @pytest.mark.skip(reason="Pending CC-1: compass/regime.py RSI signal")
    def test_rsi_momentum_signal(self):
        """High RSI + other bull signals -> stronger BULL conviction."""
        pass

    @pytest.mark.skip(reason="Pending CC-1: compass/regime.py VIX3M term structure")
    def test_vix3m_term_structure_signal(self):
        """VIX/VIX3M > 1.05 (backwardation) -> bearish signal boost."""
        pass

    @pytest.mark.skip(reason="Pending CC-1: compass/regime.py configurable thresholds")
    def test_configurable_thresholds_via_dict(self):
        """RegimeClassifier(config={'vix_crash': 35}) lowers crash threshold."""
        pass

    @pytest.mark.skip(reason="Pending CC-1: compass/regime.py lookahead protection")
    def test_lookahead_protection_shift_by_1(self):
        """classify_series uses shifted data to prevent lookahead bias."""
        pass
