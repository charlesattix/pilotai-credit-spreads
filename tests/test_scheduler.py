"""Tests for the scan scheduler."""

import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytz
import pytest

from shared.scheduler import (
    ET,
    SCAN_TIMES,
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
    def test_before_first_scan(self):
        """Before 9:15 AM on a weekday → next scan is 9:15 today."""
        now = ET.localize(datetime(2026, 2, 16, 8, 0))  # Monday 8:00
        nxt = _next_scan_time(now)
        assert nxt.hour == 9
        assert nxt.minute == 15
        assert nxt.date() == now.date()

    def test_between_scans(self):
        """Between 9:15 and 9:45 → next scan is 9:45."""
        now = ET.localize(datetime(2026, 2, 16, 9, 20))  # Monday 9:20
        nxt = _next_scan_time(now)
        assert nxt.hour == 9
        assert nxt.minute == 45

    def test_after_last_scan(self):
        """After 3:30 PM on weekday → next scan is 9:15 AM next weekday."""
        now = ET.localize(datetime(2026, 2, 16, 16, 0))  # Monday 4:00 PM
        nxt = _next_scan_time(now)
        assert nxt.hour == 9
        assert nxt.minute == 15
        assert nxt.date() == datetime(2026, 2, 17).date()  # Tuesday

    def test_friday_after_close_skips_weekend(self):
        """Friday after close → next scan is Monday 9:15 AM."""
        now = ET.localize(datetime(2026, 2, 20, 16, 0))  # Friday 4:00 PM
        nxt = _next_scan_time(now)
        assert nxt.hour == 9
        assert nxt.minute == 15
        assert nxt.weekday() == 0  # Monday

    def test_saturday_skips_to_monday(self):
        """Saturday → next scan is Monday 9:15 AM."""
        now = ET.localize(datetime(2026, 2, 21, 12, 0))  # Saturday noon
        nxt = _next_scan_time(now)
        assert nxt.weekday() == 0  # Monday
        assert nxt.hour == 9
        assert nxt.minute == 15

    def test_all_14_scan_times_defined(self):
        assert len(SCAN_TIMES) == 14

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

        call_count = 0

        # Patch _next_scan_time to return "right now" on first call, then stop
        original_next = _next_scan_time

        def mock_next(now_et):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Return a time in the immediate past so wait_seconds ≈ 0
                return now_et
            else:
                # Stop after one scan
                scheduler.stop()
                return now_et + pytz.timezone("America/New_York").localize(
                    datetime(2099, 1, 1)
                ).astimezone(pytz.UTC).replace(tzinfo=None).__class__(2099, 1, 1)

        with patch("shared.scheduler._next_scan_time") as mock:
            mock.side_effect = lambda now: now  # return "now" so wait is 0

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
