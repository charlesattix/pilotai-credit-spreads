"""
Macro Event Gate
================
Computes position-size scaling factors based on proximity to scheduled
macro events: FOMC decisions, CPI releases, and NFP (jobs) reports.

Scaling logic (from proposal Section F config):
  FOMC: {5d: 1.00, 4d: 0.90, 3d: 0.80, 2d: 0.70, 1d: 0.60, 0d: 0.50}
  CPI:  {2d: 1.00, 1d: 0.75, 0d: 0.65}
  NFP:  {2d: 1.00, 1d: 0.80, 0d: 0.75}

Composite scaling = min() across all active event scalings.

Event calendar sources:
  FOMC — hard-coded 2026 decision dates (update annually)
  CPI  — BLS releases approximately the 11th of each month
  NFP  — first Friday of each month (BLS jobs report)
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# FOMC decision dates (hard-coded — update each December for coming year)
# Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# ─────────────────────────────────────────────────────────────────────────────
FOMC_DATES_2025 = [
    date(2025, 1, 29),
    date(2025, 3, 19),
    date(2025, 5, 7),
    date(2025, 6, 18),
    date(2025, 7, 30),
    date(2025, 9, 17),
    date(2025, 11, 5),
    date(2025, 12, 10),
]

FOMC_DATES_2026 = [
    date(2026, 1, 29),
    date(2026, 3, 19),
    date(2026, 5, 7),
    date(2026, 6, 18),
    date(2026, 7, 30),
    date(2026, 9, 17),
    date(2026, 11, 5),
    date(2026, 12, 17),
]

ALL_FOMC_DATES = sorted(set(FOMC_DATES_2025 + FOMC_DATES_2026))

# Scaling table: days_out -> factor
FOMC_SCALING: Dict[int, float] = {5: 1.00, 4: 0.90, 3: 0.80, 2: 0.70, 1: 0.60, 0: 0.50}
CPI_SCALING:  Dict[int, float] = {2: 1.00, 1: 0.75, 0: 0.65}
NFP_SCALING:  Dict[int, float] = {2: 1.00, 1: 0.80, 0: 0.75}


# ─────────────────────────────────────────────────────────────────────────────
# Date computation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _first_friday_of_month(year: int, month: int) -> date:
    """Return the first Friday of the given month."""
    d = date(year, month, 1)
    days_until_friday = (4 - d.weekday()) % 7
    return d + timedelta(days=days_until_friday)


def _cpi_release_date(year: int, month: int) -> date:
    """
    Approximate BLS CPI release date for the given reference month.
    BLS typically releases CPI data for month M around the 10th–15th of month M+1.
    We use the 12th as the central estimate; if it falls on a weekend, advance to Monday.
    """
    # CPI for month M is released in month M+1
    release_month = month + 1
    release_year = year
    if release_month > 12:
        release_month = 1
        release_year += 1
    d = date(release_year, release_month, 12)
    # Advance past weekends
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _nfp_release_date(year: int, month: int) -> date:
    """
    NFP (jobs report) for month M is released on the first Friday of month M+1.
    """
    release_month = month + 1
    release_year = year
    if release_month > 12:
        release_month = 1
        release_year += 1
    return _first_friday_of_month(release_year, release_month)


def get_upcoming_events(
    as_of: Optional[date] = None,
    horizon_days: int = 14,
) -> List[Dict]:
    """
    Return all scheduled events within horizon_days calendar days of as_of.

    Each event dict:
      {event_date, event_type, description, days_out, scaling_factor}
    """
    today = as_of or date.today()
    cutoff = today + timedelta(days=horizon_days)
    events: List[Dict] = []

    # FOMC
    for fd in ALL_FOMC_DATES:
        if today <= fd <= cutoff:
            days_out = (fd - today).days
            factor = FOMC_SCALING.get(min(days_out, max(FOMC_SCALING.keys())), 1.0)
            events.append({
                "event_date": fd.strftime("%Y-%m-%d"),
                "event_type": "FOMC",
                "description": f"FOMC Rate Decision — {fd.strftime('%b %d, %Y')}",
                "days_out": days_out,
                "scaling_factor": factor,
            })

    # CPI + NFP for relevant months
    for delta_months in range(-1, 3):
        # Check a window of months around today
        year = today.year
        month = today.month + delta_months
        while month > 12:
            month -= 12
            year += 1
        while month < 1:
            month += 12
            year -= 1

        cpi_date = _cpi_release_date(year, month)
        if today <= cpi_date <= cutoff:
            days_out = (cpi_date - today).days
            factor = CPI_SCALING.get(min(days_out, max(CPI_SCALING.keys())), 1.0)
            events.append({
                "event_date": cpi_date.strftime("%Y-%m-%d"),
                "event_type": "CPI",
                "description": f"CPI Release ({year}-{month:02d}) — {cpi_date.strftime('%b %d, %Y')}",
                "days_out": days_out,
                "scaling_factor": factor,
            })

        nfp_date = _nfp_release_date(year, month)
        if today <= nfp_date <= cutoff:
            days_out = (nfp_date - today).days
            factor = NFP_SCALING.get(min(days_out, max(NFP_SCALING.keys())), 1.0)
            events.append({
                "event_date": nfp_date.strftime("%Y-%m-%d"),
                "event_type": "NFP",
                "description": f"NFP Jobs Report ({year}-{month:02d}) — {nfp_date.strftime('%b %d, %Y')}",
                "days_out": days_out,
                "scaling_factor": factor,
            })

    # Deduplicate (same date/type)
    seen = set()
    unique = []
    for ev in sorted(events, key=lambda x: x["event_date"]):
        key = (ev["event_date"], ev["event_type"])
        if key not in seen:
            seen.add(key)
            unique.append(ev)

    return unique


def compute_composite_scaling(events: List[Dict]) -> float:
    """
    Return the composite scaling factor = min(all active event scalings).
    Returns 1.0 when no events are active.
    """
    if not events:
        return 1.0
    return min(ev["scaling_factor"] for ev in events)


def run_daily_event_check(
    as_of: Optional[date] = None,
    db_path: Optional[str] = None,
) -> Tuple[float, List[Dict]]:
    """
    Run the daily event gate check:
      1. Compute upcoming events within 5 days
      2. Compute composite scaling factor
      3. Persist to macro_state.db
      4. Return (scaling_factor, events)
    """
    from shared.macro_state_db import set_state, upsert_events

    today = as_of or date.today()
    events = get_upcoming_events(as_of=today, horizon_days=5)
    scaling = compute_composite_scaling(events)

    if events:
        upsert_events(events, db_path=db_path)

    set_state("event_scaling_factor", str(scaling), db_path=db_path)
    set_state("last_daily_check", today.strftime("%Y-%m-%d"), db_path=db_path)

    return scaling, events
