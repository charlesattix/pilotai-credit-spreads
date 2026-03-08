"""
Comprehensive tests for EarningsCalendar and EconomicCalendar.

Covers:
- shared/earnings_calendar.py (EarningsCalendar)
- shared/economic_calendar.py (EconomicCalendar)
"""

import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from shared.earnings_calendar import EarningsCalendar, _NO_EARNINGS_TICKERS
from shared.economic_calendar import EconomicCalendar, EVENT_IMPORTANCE


# ======================================================================
# TestEarningsCalendar
# ======================================================================


class TestEarningsCalendar:
    """Tests for EarningsCalendar: caching, ETF filtering, expected move."""

    # ------------------------------------------------------------------
    # ETF / no-earnings ticker filtering
    # ------------------------------------------------------------------

    def test_etf_returns_none(self):
        """SPY, QQQ, ^VIX and other ETFs return None from get_next_earnings."""
        cal = EarningsCalendar()
        for ticker in ("SPY", "QQQ", "^VIX", "IWM", "GLD"):
            result = cal.get_next_earnings(ticker)
            assert result is None, f"Expected None for ETF {ticker}, got {result}"

    def test_historical_dates_etf_returns_empty(self):
        """ETFs return an empty list from get_historical_earnings_dates."""
        cal = EarningsCalendar()
        for ticker in ("SPY", "QQQ", "^VIX"):
            result = cal.get_historical_earnings_dates(ticker)
            assert result == [], f"Expected [] for ETF {ticker}, got {result}"

    # ------------------------------------------------------------------
    # Cache behaviour
    # ------------------------------------------------------------------

    def test_cache_hit_returns_cached(self):
        """Second call within TTL returns cached value without re-fetching."""
        earnings_dt = datetime(2026, 5, 1, tzinfo=timezone.utc)

        with patch("yfinance.Ticker") as MockTicker:
            mock_instance = MagicMock()
            mock_instance.calendar = {"Earnings Date": [earnings_dt]}
            MockTicker.return_value = mock_instance

            cal = EarningsCalendar()
            first = cal.get_next_earnings("AAPL")
            second = cal.get_next_earnings("AAPL")

            assert first == earnings_dt
            assert second == earnings_dt
            # yfinance.Ticker should only have been constructed once
            assert MockTicker.call_count == 1

    def test_cache_expired_refetches(self):
        """After TTL expires, the calendar refetches from yfinance."""
        earnings_dt = datetime(2026, 5, 1, tzinfo=timezone.utc)

        with patch("yfinance.Ticker") as MockTicker:
            mock_instance = MagicMock()
            mock_instance.calendar = {"Earnings Date": [earnings_dt]}
            MockTicker.return_value = mock_instance

            cal = EarningsCalendar()
            cal._cache_ttl_hours = 0  # expire immediately

            first = cal.get_next_earnings("AAPL")
            assert first == earnings_dt

            # Manually expire the cache entry
            ticker_entry = cal._earnings_cache["AAPL"]
            expired_time = datetime.now(timezone.utc) - timedelta(hours=25)
            cal._earnings_cache["AAPL"] = (ticker_entry[0], expired_time)

            second = cal.get_next_earnings("AAPL")
            assert second == earnings_dt
            # Should have called Ticker twice (once per fetch)
            assert MockTicker.call_count == 2

    # ------------------------------------------------------------------
    # yfinance response formats
    # ------------------------------------------------------------------

    def test_yfinance_dict_format(self):
        """When Ticker.calendar returns dict with 'Earnings Date' key, parses correctly."""
        earnings_dt = datetime(2026, 4, 15, tzinfo=timezone.utc)

        with patch("yfinance.Ticker") as MockTicker:
            mock_instance = MagicMock()
            mock_instance.calendar = {"Earnings Date": [earnings_dt]}
            MockTicker.return_value = mock_instance

            cal = EarningsCalendar()
            result = cal.get_next_earnings("MSFT")
            assert result == earnings_dt

    def test_yfinance_date_object_converted_to_datetime(self):
        """When yfinance returns a bare datetime.date, it's converted to tz-aware datetime."""
        bare_date = date(2026, 4, 15)

        with patch("yfinance.Ticker") as MockTicker:
            mock_instance = MagicMock()
            mock_instance.calendar = {"Earnings Date": [bare_date]}
            MockTicker.return_value = mock_instance

            cal = EarningsCalendar()
            result = cal.get_next_earnings("AAPL")
            assert isinstance(result, datetime), f"Expected datetime, got {type(result)}"
            assert result.tzinfo is not None, "Expected timezone-aware datetime"
            assert result.year == 2026
            assert result.month == 4
            assert result.day == 15

    def test_yfinance_exception_returns_none(self):
        """When yfinance raises an exception, get_next_earnings returns None."""
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.side_effect = Exception("Network error")

            cal = EarningsCalendar()
            result = cal.get_next_earnings("TSLA")
            assert result is None

    # ------------------------------------------------------------------
    # Lookahead calendar
    # ------------------------------------------------------------------

    def test_lookahead_calendar_filters_by_days(self):
        """Only returns earnings within the days_ahead window."""
        now = datetime.now(timezone.utc)
        within = now + timedelta(days=5)
        outside = now + timedelta(days=20)

        cal = EarningsCalendar()

        with patch.object(cal, "get_next_earnings") as mock_get:
            def side_effect(ticker):
                return {"NEAR": within, "FAR": outside}.get(ticker)

            mock_get.side_effect = side_effect

            results = cal.get_lookahead_calendar(["NEAR", "FAR"], days_ahead=14)
            tickers_returned = [r["ticker"] for r in results]
            assert "NEAR" in tickers_returned
            assert "FAR" not in tickers_returned

    def test_lookahead_calendar_sorted_by_days_until(self):
        """Results are sorted by days_until in ascending order."""
        now = datetime.now(timezone.utc)
        date_a = now + timedelta(days=10)
        date_b = now + timedelta(days=3)
        date_c = now + timedelta(days=7)

        cal = EarningsCalendar()

        with patch.object(cal, "get_next_earnings") as mock_get:
            def side_effect(ticker):
                return {"A": date_a, "B": date_b, "C": date_c}.get(ticker)

            mock_get.side_effect = side_effect

            results = cal.get_lookahead_calendar(["A", "B", "C"], days_ahead=14)
            days = [r["days_until"] for r in results]
            assert days == sorted(days), f"Expected sorted days_until, got {days}"

    # ------------------------------------------------------------------
    # Expected move calculation
    # ------------------------------------------------------------------

    def test_expected_move_from_options_chain(self):
        """Correct ATM straddle mid calculation from options chain DataFrame."""
        chain = pd.DataFrame({
            "strike": [450, 450, 455, 455],
            "type": ["call", "put", "call", "put"],
            "bid": [5.0, 4.5, 3.0, 6.0],
            "ask": [5.5, 5.0, 3.5, 6.5],
        })

        cal = EarningsCalendar()
        result = cal.calculate_expected_move(chain, current_price=450)

        # ATM at strike 450: call mid = (5.0+5.5)/2 = 5.25, put mid = (4.5+5.0)/2 = 4.75
        # expected move = 5.25 + 4.75 = 10.00
        assert result == 10.00

    def test_expected_move_empty_chain_returns_none(self):
        """Empty or None chain returns None."""
        cal = EarningsCalendar()

        assert cal.calculate_expected_move(None, 450) is None

        empty_df = pd.DataFrame(columns=["strike", "type", "bid", "ask"])
        assert cal.calculate_expected_move(empty_df, 450) is None


# ======================================================================
# TestEconomicCalendar
# ======================================================================


class TestEconomicCalendar:
    """Tests for EconomicCalendar: date computation, event queries, importance."""

    # ------------------------------------------------------------------
    # Date computation correctness
    # ------------------------------------------------------------------

    def test_cpi_is_second_wednesday(self):
        """All computed CPI dates fall on a Wednesday (weekday=2)."""
        cal = EconomicCalendar(years=[2026])
        for dt in cal._cpi_dates:
            assert dt.weekday() == 2, (
                f"CPI date {dt.date()} is weekday {dt.weekday()}, expected 2 (Wednesday)"
            )

    def test_ppi_is_second_thursday(self):
        """All computed PPI dates fall on a Thursday (weekday=3)."""
        cal = EconomicCalendar(years=[2026])
        for dt in cal._ppi_dates:
            assert dt.weekday() == 3, (
                f"PPI date {dt.date()} is weekday {dt.weekday()}, expected 3 (Thursday)"
            )

    def test_jobs_is_first_friday(self):
        """All computed jobs (NFP) dates are Fridays with day <= 7 (first Friday)."""
        cal = EconomicCalendar(years=[2026])
        for dt in cal._jobs_dates:
            assert dt.weekday() == 4, (
                f"Jobs date {dt.date()} is weekday {dt.weekday()}, expected 4 (Friday)"
            )
            assert dt.day <= 7, (
                f"Jobs date {dt.date()} has day={dt.day}, expected <= 7 (first Friday)"
            )

    def test_gdp_is_last_thursday_quarter_months(self):
        """GDP dates are Thursdays in Jan/Apr/Jul/Oct only."""
        cal = EconomicCalendar(years=[2026])
        assert len(cal._gdp_dates) == 4, f"Expected 4 GDP dates, got {len(cal._gdp_dates)}"

        expected_months = {1, 4, 7, 10}
        for dt in cal._gdp_dates:
            assert dt.weekday() == 3, (
                f"GDP date {dt.date()} is weekday {dt.weekday()}, expected 3 (Thursday)"
            )
            assert dt.month in expected_months, (
                f"GDP date {dt.date()} month={dt.month}, expected one of {expected_months}"
            )

    def test_all_dates_have_830_utc_time(self):
        """All computed dates (CPI, PPI, jobs, GDP) have hour=8, minute=30, UTC."""
        cal = EconomicCalendar(years=[2026])
        all_computed = (
            cal._cpi_dates + cal._ppi_dates + cal._jobs_dates + cal._gdp_dates
        )
        for dt in all_computed:
            assert dt.hour == 8, f"Date {dt} has hour={dt.hour}, expected 8"
            assert dt.minute == 30, f"Date {dt} has minute={dt.minute}, expected 30"
            assert dt.tzinfo == timezone.utc, f"Date {dt} is not UTC"

    # ------------------------------------------------------------------
    # is_event_tomorrow
    # ------------------------------------------------------------------

    def test_is_event_tomorrow_true(self):
        """Returns True when a computed event is tomorrow relative to reference_date."""
        cal = EconomicCalendar(years=[2026])
        # Pick the first CPI date and set reference to the day before
        cpi_date = cal._cpi_dates[0]
        day_before = cpi_date - timedelta(days=1)
        assert cal.is_event_tomorrow(reference_date=day_before) is True

    def test_is_event_tomorrow_false(self):
        """Returns False when no event is tomorrow."""
        cal = EconomicCalendar(years=[2026])
        # Use a date far from any event (e.g., Dec 25 which is unlikely a 2nd Wed/Thu/etc.)
        ref = datetime(2026, 12, 25, 12, 0, tzinfo=timezone.utc)
        # Verify none of the dates land on Dec 26
        all_dates = (
            cal._fomc_dates + cal._cpi_dates + cal._ppi_dates
            + cal._jobs_dates + cal._gdp_dates
        )
        dec_26 = ref.date() + timedelta(days=1)
        if any(dt.date() == dec_26 for dt in all_dates):
            # Extremely unlikely, but if it does, shift reference
            ref = datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc)
            dec_21 = ref.date() + timedelta(days=1)
            assert not any(dt.date() == dec_21 for dt in all_dates), (
                "Cannot find a safe reference date for test"
            )

        assert cal.is_event_tomorrow(reference_date=ref) is False

    # ------------------------------------------------------------------
    # get_upcoming_events
    # ------------------------------------------------------------------

    def test_get_upcoming_events_filters(self):
        """Only returns events within the days_ahead window."""
        cal = EconomicCalendar(years=[2026])
        # Use a reference right before a CPI date
        cpi_date = cal._cpi_dates[3]  # April CPI
        ref = cpi_date - timedelta(hours=1)

        events = cal.get_upcoming_events(days_ahead=1, reference_date=ref)
        # The CPI event should be included (within 1 day)
        event_types = [e["event_type"] for e in events]
        event_dates = [e["date"] for e in events]
        assert cpi_date in event_dates, "CPI date should appear in upcoming events"

        # An event 30 days away should NOT appear
        far_events = cal.get_upcoming_events(days_ahead=0, reference_date=ref - timedelta(days=30))
        far_dates = [e["date"] for e in far_events]
        assert cpi_date not in far_dates

    def test_get_upcoming_events_sorted(self):
        """Results are sorted by date ascending."""
        cal = EconomicCalendar(years=[2026])
        # Use a wide window to capture multiple events
        ref = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        events = cal.get_upcoming_events(days_ahead=60, reference_date=ref)

        dates = [e["date"] for e in events]
        assert dates == sorted(dates), "Events should be sorted by date ascending"
        assert len(events) > 1, "Should find multiple events in a 60-day window"

    # ------------------------------------------------------------------
    # get_recent_events
    # ------------------------------------------------------------------

    def test_get_recent_events(self):
        """Returns events in the past window relative to reference_date."""
        cal = EconomicCalendar(years=[2026])
        # Pick a CPI date and set reference to 1 hour after it
        cpi_date = cal._cpi_dates[2]  # March CPI
        ref = cpi_date + timedelta(hours=1)

        events = cal.get_recent_events(days_back=1, reference_date=ref)
        event_dates = [e["date"] for e in events]
        assert cpi_date in event_dates, "CPI date should be in recent events"

    # ------------------------------------------------------------------
    # get_next_event
    # ------------------------------------------------------------------

    def test_get_next_event(self):
        """Returns the soonest upcoming event from the reference point."""
        cal = EconomicCalendar(years=[2026])
        ref = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        event = cal.get_next_event(reference_date=ref)

        assert event is not None, "Should find at least one event in 2026"
        assert "event_type" in event
        assert "date" in event
        assert "description" in event
        assert "importance" in event

        # The returned event should be >= reference
        assert event["date"] >= ref

    # ------------------------------------------------------------------
    # Event importance weights
    # ------------------------------------------------------------------

    def test_event_importance_weights(self):
        """Events carry the correct importance from EVENT_IMPORTANCE dict."""
        cal = EconomicCalendar(years=[2026])
        ref = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        events = cal.get_upcoming_events(days_ahead=365, reference_date=ref)

        # Collect importance by event_type
        seen_types = set()
        for e in events:
            seen_types.add(e["event_type"])
            expected_importance = EVENT_IMPORTANCE[e["event_type"]]
            assert e["importance"] == expected_importance, (
                f"Event {e['event_type']} has importance {e['importance']}, "
                f"expected {expected_importance}"
            )

        # Verify we actually tested multiple event types
        assert len(seen_types) >= 4, (
            f"Expected at least 4 event types, only saw {seen_types}"
        )

        # Verify the specific importance values
        assert EVENT_IMPORTANCE["fomc"] == 1.0
        assert EVENT_IMPORTANCE["cpi"] == 0.85
        assert EVENT_IMPORTANCE["jobs"] == 0.75
        assert EVENT_IMPORTANCE["ppi"] == 0.70
        assert EVENT_IMPORTANCE["gdp"] == 0.65
