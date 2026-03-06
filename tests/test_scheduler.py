"""Tests for the scan scheduler."""

import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytz
import pytest

from shared.scheduler import (
    ET,
    SCAN_TIMES,
    SLOT_SCAN,
    SLOT_PRE_MARKET,
    SLOT_DAILY_REPORT,
    ScanScheduler,
    _is_weekday,
    _next_scan_time,
)


class TestIsWeekday:
    def test_monday_is_weekday(self):
        # 2026-02-16 is Monday
        dt = ET.localize(datetime(2026, 2, 16, 10, 0))
        assert _is_weekday(dt)

    def test_friday_is_weekday(self):
        dt = ET.localize(datetime(2026, 2, 20, 10, 0))
        assert _is_weekday(dt)

    def test_saturday_is_not_weekday(self):
        dt = ET.localize(datetime(2026, 2, 21, 10, 0))
        assert not _is_weekday(dt)

    def test_sunday_is_not_weekday(self):
        dt = ET.localize(datetime(2026, 2, 22, 10, 0))
        assert not _is_weekday(dt)


class TestNextScanTime:
    def test_before_first_slot(self):
        """Before 9:00 AM on a weekday → next slot is 9:00 pre_market."""
        now = ET.localize(datetime(2026, 2, 16, 8, 0))  # Monday 8:00
        nxt, slot = _next_scan_time(now)
        assert nxt.hour == 9
        assert nxt.minute == 0
        assert slot == SLOT_PRE_MARKET
        assert nxt.date() == now.date()

    def test_between_scans(self):
        """Between 9:15 and 9:45 → next scan is 9:45."""
        now = ET.localize(datetime(2026, 2, 16, 9, 20))  # Monday 9:20
        nxt, slot = _next_scan_time(now)
        assert nxt.hour == 9
        assert nxt.minute == 45
        assert slot == SLOT_SCAN

    def test_after_last_regular_scan(self):
        """After 3:30 PM on weekday → next slot is 4:15 PM daily_report."""
        now = ET.localize(datetime(2026, 2, 16, 15, 31))  # Monday 3:31 PM
        nxt, slot = _next_scan_time(now)
        assert nxt.hour == 16
        assert nxt.minute == 15
        assert slot == SLOT_DAILY_REPORT
        assert nxt.date() == now.date()

    def test_after_daily_report_next_day(self):
        """After 4:15 PM on weekday → next slot is 9:00 AM next weekday."""
        now = ET.localize(datetime(2026, 2, 16, 16, 16))  # Monday 4:16 PM
        nxt, slot = _next_scan_time(now)
        assert nxt.hour == 9
        assert nxt.minute == 0
        assert slot == SLOT_PRE_MARKET
        assert nxt.date() == datetime(2026, 2, 17).date()  # Tuesday

    def test_friday_after_close_skips_weekend(self):
        """Friday after daily report → next slot is Monday 9:00 AM."""
        now = ET.localize(datetime(2026, 2, 20, 16, 16))  # Friday 4:16 PM
        nxt, slot = _next_scan_time(now)
        assert nxt.hour == 9
        assert nxt.minute == 0
        assert slot == SLOT_PRE_MARKET
        assert nxt.weekday() == 0  # Monday

    def test_saturday_skips_to_monday(self):
        """Saturday → next slot is Monday 9:00 AM pre_market."""
        now = ET.localize(datetime(2026, 2, 21, 12, 0))  # Saturday noon
        nxt, slot = _next_scan_time(now)
        assert nxt.weekday() == 0  # Monday
        assert nxt.hour == 9
        assert nxt.minute == 0
        assert slot == SLOT_PRE_MARKET

    def test_16_scan_times_defined(self):
        assert len(SCAN_TIMES) == 16

    def test_slot_types_present(self):
        slot_types = [s[2] for s in SCAN_TIMES]
        assert slot_types.count(SLOT_PRE_MARKET) == 1
        assert slot_types.count(SLOT_DAILY_REPORT) == 1
        assert slot_types.count(SLOT_SCAN) == 14

    def test_scan_times_are_sorted(self):
        for i in range(len(SCAN_TIMES) - 1):
            a = SCAN_TIMES[i][0] * 60 + SCAN_TIMES[i][1]
            b = SCAN_TIMES[i + 1][0] * 60 + SCAN_TIMES[i + 1][1]
            assert a < b, f"SCAN_TIMES not sorted: {SCAN_TIMES[i]} >= {SCAN_TIMES[i+1]}"


class TestScanScheduler:
    def test_stop_interrupts_wait(self):
        """Calling stop() should break out of run_forever quickly."""
        scan_fn = MagicMock()
        scheduler = ScanScheduler(scan_fn)

        # Stop after a short delay
        def stop_soon():
            import time
            time.sleep(0.1)
            scheduler.stop()

        threading.Thread(target=stop_soon, daemon=True).start()
        scheduler.run_forever()  # Should return quickly

        # Scan should NOT have been called (we stopped before any scan time)
        scan_fn.assert_not_called()

    def test_scan_runs_when_time_matches(self):
        """Scheduler should call scan_fn when the scheduled time arrives."""
        scan_fn = MagicMock()
        scheduler = ScanScheduler(scan_fn, startup_delay=0)

        with patch("shared.scheduler._next_scan_time") as mock:
            # Return (now, slot_type) so wait is 0
            mock.side_effect = lambda now: (now, SLOT_SCAN)

            # Stop after brief delay
            def stop_soon():
                import time
                time.sleep(0.5)
                scheduler.stop()

            threading.Thread(target=stop_soon, daemon=True).start()

            # Patch weekday check to return True
            with patch("shared.scheduler._is_weekday", return_value=True):
                scheduler.run_forever()

        assert scan_fn.call_count >= 1
        # Verify slot_type was passed
        scan_fn.assert_called_with(SLOT_SCAN)
