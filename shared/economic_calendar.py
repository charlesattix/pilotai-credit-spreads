"""
Unified economic event calendar for gamma/lotto plays.

Provides computed dates for major economic events (FOMC, CPI, PPI, Jobs, GDP)
and exposes simple query methods for the gamma scanner.
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional

from shared.constants import FOMC_DATES

logger = logging.getLogger(__name__)

# Importance weights used by the gamma scanner scoring function
EVENT_IMPORTANCE: Dict[str, float] = {
    "fomc": 1.0,
    "cpi": 0.85,
    "jobs": 0.75,
    "ppi": 0.70,
    "gdp": 0.65,
}


class EconomicCalendar:
    """Unified economic event calendar with algorithmic date generation."""

    def __init__(self, years: Optional[List[int]] = None):
        # FOMC dates imported from shared.constants (hand-maintained)
        self._fomc_dates: List[datetime] = list(FOMC_DATES)

        # Compute algorithmic dates for specified years, or current + next
        if years is None:
            now = datetime.now(timezone.utc)
            years = [now.year, now.year + 1]

        self._cpi_dates: List[datetime] = []
        self._ppi_dates: List[datetime] = []
        self._jobs_dates: List[datetime] = []
        self._gdp_dates: List[datetime] = []

        for year in years:
            self._cpi_dates.extend(self._compute_cpi_dates(year))
            self._ppi_dates.extend(self._compute_ppi_dates(year))
            self._jobs_dates.extend(self._compute_jobs_dates(year))
            self._gdp_dates.extend(self._compute_gdp_dates(year))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_upcoming_events(
        self,
        days_ahead: int = 2,
        reference_date: Optional[datetime] = None,
    ) -> List[Dict]:
        """Return economic events within *days_ahead* of *reference_date*.

        Each event dict: ``{event_type, date, description, importance}``.
        Sorted by date ascending.
        """
        ref = reference_date or datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)

        cutoff = ref + timedelta(days=days_ahead)
        events: List[Dict] = []

        for dt in self._fomc_dates:
            if ref <= dt <= cutoff:
                events.append(self._event("fomc", dt, "FOMC rate decision"))

        for dt in self._cpi_dates:
            if ref <= dt <= cutoff:
                events.append(self._event("cpi", dt, "CPI inflation report"))

        for dt in self._ppi_dates:
            if ref <= dt <= cutoff:
                events.append(self._event("ppi", dt, "PPI producer prices"))

        for dt in self._jobs_dates:
            if ref <= dt <= cutoff:
                events.append(self._event("jobs", dt, "Non-farm payrolls"))

        for dt in self._gdp_dates:
            if ref <= dt <= cutoff:
                events.append(self._event("gdp", dt, "GDP report"))

        events.sort(key=lambda e: e["date"])
        return events

    def is_event_tomorrow(
        self, reference_date: Optional[datetime] = None
    ) -> bool:
        """Return True if any major economic event is tomorrow."""
        ref = reference_date or datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)

        tomorrow = ref + timedelta(days=1)
        tomorrow_date = tomorrow.date()

        all_dates = (
            self._fomc_dates
            + self._cpi_dates
            + self._ppi_dates
            + self._jobs_dates
            + self._gdp_dates
        )
        return any(dt.date() == tomorrow_date for dt in all_dates)

    def get_next_event(
        self, reference_date: Optional[datetime] = None
    ) -> Optional[Dict]:
        """Return the soonest upcoming economic event, or None."""
        # Use a generous lookahead to find the next event
        events = self.get_upcoming_events(days_ahead=90, reference_date=reference_date)
        return events[0] if events else None

    # ------------------------------------------------------------------
    # Date computation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_cpi_dates(year: int) -> List[datetime]:
        """CPI release: ~2nd Tuesday-Wednesday of each month (approximate as 2nd Wednesday)."""
        dates = []
        for month in range(1, 13):
            # Find 2nd Wednesday: first day of month, find first Wednesday, then +7
            first_day = date(year, month, 1)
            # weekday(): Monday=0 ... Sunday=6; Wednesday=2
            days_until_wed = (2 - first_day.weekday()) % 7
            first_wed = first_day + timedelta(days=days_until_wed)
            second_wed = first_wed + timedelta(days=7)
            dates.append(
                datetime(year, month, second_wed.day, 8, 30, tzinfo=timezone.utc)
            )
        return dates

    @staticmethod
    def _compute_ppi_dates(year: int) -> List[datetime]:
        """PPI release: day after CPI (approximate as 2nd Thursday)."""
        dates = []
        for month in range(1, 13):
            first_day = date(year, month, 1)
            # Thursday=3
            days_until_thu = (3 - first_day.weekday()) % 7
            first_thu = first_day + timedelta(days=days_until_thu)
            second_thu = first_thu + timedelta(days=7)
            dates.append(
                datetime(year, month, second_thu.day, 8, 30, tzinfo=timezone.utc)
            )
        return dates

    @staticmethod
    def _compute_jobs_dates(year: int) -> List[datetime]:
        """Non-farm payrolls: first Friday of each month."""
        dates = []
        for month in range(1, 13):
            first_day = date(year, month, 1)
            # Friday=4
            days_until_fri = (4 - first_day.weekday()) % 7
            first_fri = first_day + timedelta(days=days_until_fri)
            dates.append(
                datetime(year, month, first_fri.day, 8, 30, tzinfo=timezone.utc)
            )
        return dates

    @staticmethod
    def _compute_gdp_dates(year: int) -> List[datetime]:
        """GDP report: last Thursday of Jan, Apr, Jul, Oct."""
        dates = []
        for month in [1, 4, 7, 10]:
            # Find last Thursday of the month
            if month == 12:
                last_day = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                last_day = date(year, month + 1, 1) - timedelta(days=1)
            # Walk backwards to find Thursday
            days_back = (last_day.weekday() - 3) % 7  # Thursday=3
            last_thu = last_day - timedelta(days=days_back)
            dates.append(
                datetime(year, month, last_thu.day, 8, 30, tzinfo=timezone.utc)
            )
        return dates

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _event(event_type: str, dt: datetime, description: str) -> Dict:
        return {
            "event_type": event_type,
            "date": dt,
            "description": description,
            "importance": EVENT_IMPORTANCE.get(event_type, 0.5),
        }
