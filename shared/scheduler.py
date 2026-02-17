"""
Built-in trade scanner scheduler.

Runs scans at fixed market-hours intervals (America/New_York, weekdays only).
No external cron or APScheduler dependency — uses a simple sleep loop.

Schedule (all times ET, Mon-Fri):
  9:15, 9:45  — pre-market / open
  10:00, 10:30, 11:00, 11:30, 12:00, 12:30,
  1:00, 1:30, 2:00, 2:30, 3:00, 3:30  — intraday every 30 min
"""

import logging
import threading
import time
from datetime import datetime, timedelta

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# (hour, minute) in ET — 14 scans per day
SCAN_TIMES = [
    (9, 15), (9, 45),
    (10, 0), (10, 30),
    (11, 0), (11, 30),
    (12, 0), (12, 30),
    (13, 0), (13, 30),
    (14, 0), (14, 30),
    (15, 0), (15, 30),
]


def _is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5  # Mon=0 … Fri=4


def _next_scan_time(now_et: datetime) -> datetime:
    """Return the next scheduled scan time (ET-aware datetime)."""
    today_date = now_et.date()

    # Check remaining slots today
    for hour, minute in SCAN_TIMES:
        candidate = ET.localize(datetime(today_date.year, today_date.month, today_date.day, hour, minute))
        if candidate > now_et and _is_weekday(candidate):
            return candidate

    # No more slots today — find next weekday
    next_day = today_date + timedelta(days=1)
    while next_day.weekday() >= 5:  # skip weekends
        next_day += timedelta(days=1)

    first_hour, first_minute = SCAN_TIMES[0]
    return ET.localize(datetime(next_day.year, next_day.month, next_day.day, first_hour, first_minute))


class ScanScheduler:
    """Runs a scan callback on the market-hours schedule."""

    def __init__(self, scan_fn):
        """
        Args:
            scan_fn: Callable that performs the scan (no arguments).
        """
        self._scan_fn = scan_fn
        self._stop_event = threading.Event()

    def stop(self):
        """Signal the scheduler to stop after the current sleep."""
        self._stop_event.set()

    def run_forever(self):
        """Block and run scans on schedule until stop() is called or SIGTERM."""
        logger.info("Scheduler started — %d scan times per trading day", len(SCAN_TIMES))

        while not self._stop_event.is_set():
            now_et = datetime.now(ET)
            nxt = _next_scan_time(now_et)
            wait_seconds = (nxt - now_et).total_seconds()

            logger.info(
                "Next scan at %s ET (in %.0f min)",
                nxt.strftime("%Y-%m-%d %H:%M"),
                wait_seconds / 60,
            )

            # Sleep in short intervals so we can react to stop_event quickly
            if self._stop_event.wait(timeout=wait_seconds):
                logger.info("Scheduler stopping (signal received during wait)")
                break

            # Double-check we're in a valid window (guards against clock drift)
            now_et = datetime.now(ET)
            if not _is_weekday(now_et):
                continue

            # Run the scan
            try:
                logger.info("=== Scheduled scan starting (%s ET) ===", now_et.strftime("%H:%M"))
                self._scan_fn()
                logger.info("=== Scheduled scan complete ===")
            except Exception:
                logger.exception("Scan failed — will retry at next scheduled time")
