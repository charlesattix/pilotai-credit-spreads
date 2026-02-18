"""Tests for the SentimentScanner event-risk scanner."""

import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from ml.sentiment_scanner import SentimentScanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scanner(earnings_date=None):
    """
    Build a SentimentScanner with a mocked data_cache.

    If *earnings_date* is provided, the mock ticker object's calendar will
    contain that date under the 'Earnings Date' key.  Otherwise the calendar
    is ``None`` (no upcoming earnings).
    """
    data_cache = MagicMock()
    mock_ticker = MagicMock()

    if earnings_date is not None:
        mock_ticker.calendar = {"Earnings Date": pd.Timestamp(earnings_date)}
    else:
        mock_ticker.calendar = None

    data_cache.get_ticker_obj.return_value = mock_ticker

    scanner = SentimentScanner(data_cache=data_cache)
    # Clear built-in dates so tests are deterministic unless overridden.
    scanner.FOMC_DATES = []
    scanner.CPI_RELEASE_DAYS = []
    return scanner


# ===========================================================================
# TestScan
# ===========================================================================

class TestScan:
    """Tests for SentimentScanner.scan()."""

    def test_no_events_returns_low_risk(self):
        """When no events fall in the scan window, risk should be zero."""
        scanner = _make_scanner(earnings_date=None)

        # Use a far-future expiration so the window is wide but still empty.
        expiration = datetime(2025, 6, 1, tzinfo=timezone.utc)
        result = scanner.scan("SPY", expiration_date=expiration, lookahead_days=7)

        assert result["event_risk_score"] == 0.0
        assert result["recommendation"] == "proceed"
        assert result["events"] == []
        assert result["ticker"] == "SPY"

    def test_earnings_in_window_detected(self):
        """Earnings that fall inside the scan window must appear in events."""
        # Place earnings 3 days from now so they land inside lookahead=7.
        earnings_dt = datetime.now(timezone.utc) + timedelta(days=3)
        scanner = _make_scanner(earnings_date=earnings_dt)

        expiration = datetime.now(timezone.utc) + timedelta(days=30)
        result = scanner.scan("AAPL", expiration_date=expiration, lookahead_days=7)

        assert len(result["events"]) >= 1
        event_types = [e["event_type"] for e in result["events"]]
        assert "earnings" in event_types
        assert result["event_risk_score"] > 0

    def test_earnings_outside_window_not_detected(self):
        """Earnings far beyond the scan window should not appear."""
        earnings_dt = datetime.now(timezone.utc) + timedelta(days=60)
        scanner = _make_scanner(earnings_date=earnings_dt)

        expiration = datetime.now(timezone.utc) + timedelta(days=5)
        result = scanner.scan("AAPL", expiration_date=expiration, lookahead_days=5)

        event_types = [e["event_type"] for e in result["events"]]
        assert "earnings" not in event_types


# ===========================================================================
# TestCheckFOMC
# ===========================================================================

class TestCheckFOMC:
    """Tests for SentimentScanner._check_fomc()."""

    def test_fomc_in_window_detected(self):
        """An FOMC date inside [start, end] should be returned."""
        scanner = _make_scanner()
        now = datetime.now(timezone.utc)
        fomc_date = now + timedelta(days=3)
        scanner.FOMC_DATES = [fomc_date]

        start = now + timedelta(days=1)
        end = now + timedelta(days=7)

        event = scanner._check_fomc(start, end)

        assert event is not None
        assert event["event_type"] == "fomc"
        assert event["risk_score"] > 0

    def test_no_fomc_returns_none(self):
        """When no FOMC dates fall in the window, result should be None."""
        scanner = _make_scanner()
        now = datetime.now(timezone.utc)
        # FOMC date well outside the window
        scanner.FOMC_DATES = [now + timedelta(days=90)]

        start = now + timedelta(days=1)
        end = now + timedelta(days=7)

        event = scanner._check_fomc(start, end)
        assert event is None

    def test_fomc_empty_dates_returns_none(self):
        """An empty FOMC_DATES list should yield None."""
        scanner = _make_scanner()
        scanner.FOMC_DATES = []

        start = datetime(2025, 3, 10, tzinfo=timezone.utc)
        end = datetime(2025, 3, 15, tzinfo=timezone.utc)

        assert scanner._check_fomc(start, end) is None


# ===========================================================================
# TestCheckCPI
# ===========================================================================

class TestCheckCPI:
    """Tests for SentimentScanner._check_cpi()."""

    def test_cpi_day_in_window_detected(self):
        """A CPI release day that falls within the window should be found."""
        scanner = _make_scanner()
        now = datetime.now(timezone.utc)
        # Build a future window and set CPI_RELEASE_DAYS to include a day
        # that falls within it.
        future = now + timedelta(days=2)
        scanner.CPI_RELEASE_DAYS = [future.day]

        start = now + timedelta(days=1)
        end = now + timedelta(days=5)

        event = scanner._check_cpi(start, end)

        assert event is not None
        assert event["event_type"] == "cpi"
        assert event["risk_score"] > 0

    def test_cpi_day_outside_window_returns_none(self):
        """When no CPI release days fall in the window, result is None."""
        scanner = _make_scanner()
        # Only day-of-month 25-28, but window is March 10-15.
        scanner.CPI_RELEASE_DAYS = [25, 26, 27, 28]

        start = datetime(2025, 3, 10, tzinfo=timezone.utc)
        end = datetime(2025, 3, 15, tzinfo=timezone.utc)

        assert scanner._check_cpi(start, end) is None

    def test_cpi_empty_days_returns_none(self):
        """An empty CPI_RELEASE_DAYS list should yield None."""
        scanner = _make_scanner()
        scanner.CPI_RELEASE_DAYS = []

        start = datetime(2025, 3, 10, tzinfo=timezone.utc)
        end = datetime(2025, 3, 15, tzinfo=timezone.utc)

        assert scanner._check_cpi(start, end) is None


# ===========================================================================
# TestAdjustPosition
# ===========================================================================

class TestAdjustPosition:
    """Tests for SentimentScanner.adjust_position_for_events()."""

    def test_high_risk_zeros_position(self):
        """Risk >= 0.80 should eliminate the position entirely."""
        scanner = _make_scanner()
        assert scanner.adjust_position_for_events(1.0, 0.80) == 0.0
        assert scanner.adjust_position_for_events(1.0, 0.95) == 0.0

    def test_low_risk_unchanged(self):
        """Risk < 0.20 should leave position size untouched."""
        scanner = _make_scanner()
        assert scanner.adjust_position_for_events(1.0, 0.10) == 1.0
        assert scanner.adjust_position_for_events(0.50, 0.0) == 0.50

    def test_moderate_risk_halves_position(self):
        """Risk in [0.40, 0.60) should apply a 0.50 multiplier."""
        scanner = _make_scanner()
        assert scanner.adjust_position_for_events(1.0, 0.40) == pytest.approx(0.50)
        assert scanner.adjust_position_for_events(1.0, 0.59) == pytest.approx(0.50)

    def test_moderate_high_risk_reduces_to_quarter(self):
        """Risk in [0.60, 0.80) should apply a 0.25 multiplier."""
        scanner = _make_scanner()
        assert scanner.adjust_position_for_events(1.0, 0.60) == pytest.approx(0.25)
        assert scanner.adjust_position_for_events(1.0, 0.79) == pytest.approx(0.25)

    def test_slight_risk_reduces_to_three_quarters(self):
        """Risk in [0.20, 0.40) should apply a 0.75 multiplier."""
        scanner = _make_scanner()
        assert scanner.adjust_position_for_events(1.0, 0.20) == pytest.approx(0.75)
        assert scanner.adjust_position_for_events(1.0, 0.39) == pytest.approx(0.75)


# ===========================================================================
# TestShouldAvoidTrade
# ===========================================================================

class TestShouldAvoidTrade:
    """Tests for SentimentScanner.should_avoid_trade()."""

    def test_high_risk_avoids(self):
        """A scan that produces risk >= max_risk_score should return True."""
        # Put earnings 1 day out so risk_score will be very high (0.95).
        earnings_dt = datetime.now(timezone.utc) + timedelta(days=1)
        scanner = _make_scanner(earnings_date=earnings_dt)

        expiration = datetime.now(timezone.utc) + timedelta(days=30)
        avoid, reason = scanner.should_avoid_trade(
            "TSLA", expiration, max_risk_score=0.70
        )

        assert avoid is True
        assert "risk" in reason.lower() or "High" in reason

    def test_low_risk_proceeds(self):
        """No events means risk 0 -- trade should NOT be avoided."""
        scanner = _make_scanner(earnings_date=None)

        expiration = datetime.now(timezone.utc) + timedelta(days=30)
        avoid, reason = scanner.should_avoid_trade(
            "SPY", expiration, max_risk_score=0.70
        )

        assert avoid is False
