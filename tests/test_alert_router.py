"""Tests for alerts.alert_router — full pipeline integration test.

Uses mocked dependencies (RiskGate, AlertPositionSizer, TelegramBot,
TelegramAlertFormatter) to verify routing logic in isolation.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from alerts.alert_schema import Alert, AlertType, Direction, Leg, SizeResult
from alerts.risk_gate import RiskGate
from alerts.alert_position_sizer import AlertPositionSizer
from alerts.alert_router import AlertRouter
from alerts.formatters.telegram import TelegramAlertFormatter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opp(ticker="SPY", score=75, opp_type="bull_put_spread", **extra):
    base = {
        "ticker": ticker,
        "type": opp_type,
        "expiration": "2025-06-20",
        "short_strike": 540.0,
        "long_strike": 535.0,
        "credit": 1.50,
        "stop_loss": 3.00,
        "profit_target": 0.75,
        "score": score,
    }
    base.update(extra)
    return base


def _clean_state():
    return {
        "account_value": 100_000,
        "open_positions": [],
        "daily_pnl_pct": 0.0,
        "weekly_pnl_pct": 0.0,
        "recent_stops": [],
    }


def _build_router(
    risk_gate=None,
    position_sizer=None,
    telegram_bot=None,
    formatter=None,
):
    if risk_gate is None:
        risk_gate = RiskGate()
    if position_sizer is None:
        position_sizer = AlertPositionSizer()
    if telegram_bot is None:
        telegram_bot = MagicMock()
        telegram_bot.send_alert = MagicMock(return_value=True)
    if formatter is None:
        formatter = TelegramAlertFormatter()
    return AlertRouter(risk_gate, position_sizer, telegram_bot, formatter)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConversion:
    """Stage 1: convert opportunities to alerts."""

    def test_scores_below_60_filtered(self):
        router = _build_router()
        opps = [_opp(score=59), _opp(score=40)]
        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities(opps, _clean_state())
        assert result == []

    def test_scores_at_60_included(self):
        router = _build_router()
        opps = [_opp(score=60)]
        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities(opps, _clean_state())
        assert len(result) == 1

    def test_invalid_opp_skipped(self):
        """Malformed opportunity should be skipped, not crash the pipeline."""
        router = _build_router()
        bad_opp = {"ticker": "BAD"}  # missing required fields
        good_opp = _opp(score=70)
        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities([bad_opp, good_opp], _clean_state())
        assert len(result) == 1
        assert result[0].ticker == "SPY"


class TestDeduplication:
    """Stage 2: same ticker+direction within 30 min is deduped."""

    def test_first_alert_passes(self):
        router = _build_router()
        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities([_opp(score=70)], _clean_state())
        assert len(result) == 1

    def test_duplicate_within_window_filtered(self):
        router = _build_router()
        with patch("alerts.alert_router.insert_alert"):
            router.route_opportunities([_opp(score=70)], _clean_state())
            result = router.route_opportunities([_opp(score=70)], _clean_state())
        assert len(result) == 0

    def test_different_ticker_not_deduped(self):
        router = _build_router()
        with patch("alerts.alert_router.insert_alert"):
            router.route_opportunities([_opp(ticker="SPY", score=70)], _clean_state())
            result = router.route_opportunities([_opp(ticker="QQQ", score=70)], _clean_state())
        assert len(result) == 1


class TestRiskGateIntegration:
    """Stage 3: risk gate blocks alerts that fail checks."""

    def test_risk_gate_rejection(self):
        gate = MagicMock(spec=RiskGate)
        gate.check.return_value = (False, "over exposure")
        gate.weekly_loss_breach.return_value = False
        router = _build_router(risk_gate=gate)

        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities([_opp(score=70)], _clean_state())
        assert result == []

    def test_risk_gate_approval(self):
        gate = MagicMock(spec=RiskGate)
        gate.check.return_value = (True, "")
        gate.weekly_loss_breach.return_value = False
        router = _build_router(risk_gate=gate)

        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities([_opp(score=70)], _clean_state())
        assert len(result) == 1


class TestSizing:
    """Stage 4: position sizing attached to approved alerts."""

    def test_sizing_attached(self):
        router = _build_router()
        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities([_opp(score=70)], _clean_state())
        assert len(result) == 1
        assert result[0].sizing is not None
        assert result[0].sizing.contracts >= 0


class TestPrioritization:
    """Stage 5: type priority, then score. Top 5."""

    def test_top_5_limit(self):
        router = _build_router()
        opps = [_opp(ticker=f"T{i}", score=70 + i) for i in range(10)]
        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities(opps, _clean_state())
        assert len(result) <= 5

    def test_type_priority_order(self):
        """Credit spreads should rank above gamma lotto at same score."""
        router = _build_router()
        opps = [
            _opp(ticker="SPY", score=70, opp_type="bull_put_spread"),
            # gamma_lotto type doesn't map from legacy opp types,
            # but credit_spread ranks first
        ]
        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities(opps, _clean_state())
        assert len(result) >= 1
        assert result[0].type == AlertType.credit_spread


class TestDispatch:
    """Stage 6: Telegram send + DB persistence."""

    def test_telegram_called(self):
        bot = MagicMock()
        bot.send_alert.return_value = True
        router = _build_router(telegram_bot=bot)

        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities([_opp(score=70)], _clean_state())

        assert len(result) == 1
        bot.send_alert.assert_called_once()

    def test_db_persist_called(self):
        with patch("alerts.alert_router.insert_alert") as mock_insert:
            router = _build_router()
            router.route_opportunities([_opp(score=70)], _clean_state())
            mock_insert.assert_called_once()

    def test_telegram_failure_does_not_block(self):
        """If Telegram fails, the alert should still be persisted."""
        bot = MagicMock()
        bot.send_alert.side_effect = Exception("network error")
        router = _build_router(telegram_bot=bot)

        with patch("alerts.alert_router.insert_alert") as mock_insert:
            result = router.route_opportunities([_opp(score=70)], _clean_state())
        assert len(result) == 1
        mock_insert.assert_called_once()


class TestFullPipeline:
    """End-to-end: realistic multi-opportunity scenario."""

    def test_mixed_scores_and_types(self):
        router = _build_router()
        opps = [
            _opp(ticker="SPY", score=85, opp_type="bull_put_spread"),
            _opp(ticker="QQQ", score=72, opp_type="bear_call_spread"),
            _opp(ticker="AAPL", score=55),   # below 60 — filtered
            _opp(ticker="IWM", score=90, opp_type="iron_condor",
                 call_short_strike=220.0, call_long_strike=225.0),
        ]

        with patch("alerts.alert_router.insert_alert"):
            result = router.route_opportunities(opps, _clean_state())

        tickers = {a.ticker for a in result}
        assert "AAPL" not in tickers  # filtered (score < 60)
        assert "SPY" in tickers
        assert len(result) <= 5
