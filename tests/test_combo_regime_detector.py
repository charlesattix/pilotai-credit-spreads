"""Tests for ml.combo_regime_detector.ComboRegimeDetector."""

import pytest
from datetime import datetime, timedelta, timezone

from ml.combo_regime_detector import ComboRegimeDetector, BULL, BEAR, NEUTRAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_detector(**kwargs):
    """Create a detector with sensible defaults."""
    defaults = {"hysteresis_hours": 24, "ma200_band_pct": 0.02}
    defaults.update(kwargs)
    return ComboRegimeDetector(**defaults)


def _ts(hours_offset=0):
    """Deterministic timestamp with optional hour offset."""
    base = datetime(2026, 3, 6, 14, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(hours=hours_offset)


# ---------------------------------------------------------------------------
# 1-2  VIX circuit breaker
# ---------------------------------------------------------------------------

class TestVIXCircuitBreaker:
    def test_vix_above_40_forces_bear(self):
        """VIX > 40 → forced BEAR regardless of bullish signals."""
        det = _make_detector()
        result = det.detect(
            vix=45, price=500, ma200=450,
            signals=[BULL, BULL, BULL], now=_ts(),
        )
        assert result["regime"] == BEAR
        assert result["confidence"] == 1.0
        assert result["reason"] == "vix_circuit_breaker"

    def test_vix_below_threshold_uses_normal_voting(self):
        """VIX <= 40 → normal signal voting applies."""
        det = _make_detector()
        result = det.detect(
            vix=25, price=500, ma200=450,
            signals=[BULL, BULL, BULL], now=_ts(),
        )
        assert result["regime"] == BULL
        assert result["reason"] == "vote"


# ---------------------------------------------------------------------------
# 3-4  Hysteresis
# ---------------------------------------------------------------------------

class TestHysteresis:
    def test_blocks_rapid_flip(self):
        """Regime cannot flip within the hysteresis window."""
        det = _make_detector(hysteresis_hours=24)

        # Establish BULL
        r1 = det.detect(
            vix=15, price=500, ma200=450,
            signals=[BULL, BULL, BULL], now=_ts(0),
        )
        assert r1["regime"] == BULL

        # 1 hour later, all-BEAR signals — should be blocked
        r2 = det.detect(
            vix=15, price=500, ma200=450,
            signals=[BEAR, BEAR, BEAR], now=_ts(1),
        )
        assert r2["regime"] == BULL  # held by hysteresis
        assert r2["hysteresis_active"] is True

    def test_allows_flip_after_window(self):
        """Regime can flip once the hysteresis window expires."""
        det = _make_detector(hysteresis_hours=24)

        # Establish BULL
        det.detect(
            vix=15, price=500, ma200=450,
            signals=[BULL, BULL, BULL], now=_ts(0),
        )

        # 25 hours later → flip allowed
        r = det.detect(
            vix=15, price=500, ma200=450,
            signals=[BEAR, BEAR, BEAR], now=_ts(25),
        )
        assert r["regime"] == BEAR
        assert r["hysteresis_active"] is False


# ---------------------------------------------------------------------------
# 5  MA200 abstain zone
# ---------------------------------------------------------------------------

class TestMA200Abstain:
    def test_price_near_ma200_forces_neutral(self):
        """Price within +/-2% of MA200 → NEUTRAL (abstain zone)."""
        det = _make_detector(ma200_band_pct=0.02)

        # Price exactly at MA200 (0% distance)
        result = det.detect(
            vix=15, price=400, ma200=400,
            signals=[BULL, BULL, BULL], now=_ts(),
        )
        assert result["regime"] == NEUTRAL
        assert result["reason"] == "ma200_abstain"


# ---------------------------------------------------------------------------
# 6-8  Signal voting
# ---------------------------------------------------------------------------

class TestSignalVoting:
    def test_all_bull_signals(self):
        """3/3 BULL → BULL (unanimous agreement required)."""
        det = _make_detector()
        result = det.detect(
            vix=15, price=500, ma200=450,
            signals=[BULL, BULL, BULL], now=_ts(),
        )
        assert result["regime"] == BULL
        assert result["confidence"] == 1.0

    def test_all_bear_signals(self):
        """3/3 BEAR → BEAR (unanimous agreement required)."""
        det = _make_detector()
        result = det.detect(
            vix=15, price=500, ma200=450,
            signals=[BEAR, BEAR, BEAR], now=_ts(),
        )
        assert result["regime"] == BEAR
        assert result["confidence"] == 1.0

    def test_two_thirds_bear_means_neutral(self):
        """2/3 BEAR → NEUTRAL (not enough conviction for BEAR)."""
        det = _make_detector()
        result = det.detect(
            vix=15, price=500, ma200=450,
            signals=[BEAR, BEAR, BULL], now=_ts(),
        )
        assert result["regime"] == NEUTRAL
        assert result["confidence"] == pytest.approx(0.6)
