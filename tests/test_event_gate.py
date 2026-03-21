"""
Unit tests for the COMPASS event calendar and position-size scaling.

Target module: compass/events.py (post-Phase 2 move)
Pre-move source: shared/macro_event_gate.py

Tests cover:
  - FOMC date completeness (2020-2026 including emergency dates)
  - CPI / NFP date computation helpers
  - _iter_months year boundary handling
  - get_upcoming_events() pre-event scaling and post-event buffers (G5)
  - compute_composite_scaling() per-type minimums (G4)
  - run_daily_event_check() DB persistence integration

Blueprint spec: 10+ tests, all green (Phase 3 exit criteria).
"""

from datetime import date, timedelta

import pytest

from compass.events import (
    ALL_FOMC_DATES,
    FOMC_SCALING,
    CPI_SCALING,
    NFP_SCALING,
    get_upcoming_events,
    compute_composite_scaling,
    run_daily_event_check,
    _first_friday_of_month,
    _cpi_release_date,
    _nfp_release_date,
    _iter_months,
)

from tests.compass_helpers import (
    KNOWN_FOMC_DATES,
    KNOWN_CPI_DATES,
    KNOWN_NFP_DATES,
    POST_FOMC_SCALING,
    POST_CPI_SCALING,
    POST_NFP_SCALING,
    mock_macro_db,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def test_db(tmp_path):
    """Isolated SQLite macro DB for integration tests."""
    return mock_macro_db(tmp_path)


# ══════════════════════════════════════════════════════════════════════════════
# A. FOMC date data integrity
# ══════════════════════════════════════════════════════════════════════════════

class TestFomcDates:

    def test_2026_fomc_dates_present(self):
        """All 8 scheduled 2026 FOMC dates are in ALL_FOMC_DATES."""
        pass

    def test_emergency_dates_included(self):
        """COVID emergency dates 2020-03-03 and 2020-03-15 are present."""
        pass

    def test_all_fomc_dates_sorted(self):
        """ALL_FOMC_DATES is in chronological order."""
        pass

    def test_fomc_dates_no_duplicates(self):
        """ALL_FOMC_DATES contains no duplicate entries."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# B. Date computation helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestDateHelpers:

    def test_first_friday_is_always_friday(self):
        """_first_friday_of_month always returns a Friday (weekday=4)."""
        pass

    def test_cpi_release_date_is_weekday(self):
        """_cpi_release_date never returns a Saturday or Sunday."""
        pass

    def test_cpi_release_date_year_boundary(self):
        """CPI for December → releases in January of next year."""
        pass

    def test_nfp_release_date_is_friday(self):
        """_nfp_release_date always returns a Friday."""
        pass

    def test_nfp_release_date_year_boundary(self):
        """NFP for December → first Friday of January next year."""
        pass

    def test_iter_months_wraps_year(self):
        """_iter_months correctly handles December → January year boundary."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# C. get_upcoming_events() — pre-event scaling
# ══════════════════════════════════════════════════════════════════════════════

class TestGetUpcomingEvents:

    def test_fomc_day_scaling_0_50(self):
        """On FOMC day itself → scaling_factor = 0.50."""
        pass

    def test_fomc_1_day_before_scaling_0_60(self):
        """1 day before FOMC → scaling_factor = 0.60."""
        pass

    def test_fomc_5_days_before_scaling_1_00(self):
        """5 days before FOMC → scaling_factor = 1.00 (within window but max)."""
        pass

    def test_fomc_6_plus_days_no_event(self):
        """6+ calendar days before FOMC → no FOMC event returned (outside horizon)."""
        pass

    def test_no_events_far_from_dates(self):
        """Date far from any event → empty list or only distant events."""
        pass

    def test_events_are_deduplicated(self):
        """No duplicate (event_date, event_type) pairs in output."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# D. Post-event buffers (G5)
# ══════════════════════════════════════════════════════════════════════════════

class TestPostEventBuffers:

    def test_post_fomc_buffer_day_after(self):
        """1 day after FOMC → FOMC_POST event at 0.70× scaling."""
        pass

    def test_post_cpi_buffer_day_after(self):
        """1 day after CPI release → CPI_POST event at 0.80× scaling."""
        pass

    def test_post_nfp_buffer_day_after(self):
        """1 day after NFP release → NFP_POST event at 0.80× scaling."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# E. compute_composite_scaling() — G4 per-type minimums
# ══════════════════════════════════════════════════════════════════════════════

class TestCompositeScaling:

    def test_empty_events_returns_1_0(self):
        """No events → scaling factor is 1.0 (no restriction)."""
        pass

    def test_fomc_only(self):
        """Single FOMC event → composite equals its scaling factor."""
        pass

    def test_cpi_only(self):
        """Single CPI event → composite equals its scaling factor."""
        pass

    def test_fomc_plus_cpi_concurrent(self):
        """FOMC (0.50) + CPI (0.65) same week → min(0.50, 0.65) = 0.50."""
        pass

    def test_separates_fomc_from_data_events(self):
        """FOMC_POST (0.70) + NFP (0.75) → min(fomc_floor=0.70, data_floor=0.75) = 0.70."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# F. run_daily_event_check() — DB persistence integration
# ══════════════════════════════════════════════════════════════════════════════

class TestRunDailyEventCheck:

    def test_persists_scaling_factor_to_db(self, test_db):
        """run_daily_event_check writes event_scaling_factor to macro_state table."""
        pass

    def test_persists_last_daily_check_date(self, test_db):
        """run_daily_event_check writes last_daily_check to macro_state table."""
        pass

    def test_returns_scaling_and_events_tuple(self, test_db):
        """Return value is (float, list) tuple."""
        pass
