"""Resilience tests for the 8-week unattended validation run hardening.

Covers: DataCache retry, stale-price fallback, Alpaca close retry,
dedup failure logging, startup reconcile without Alpaca, drawdown
auto-recovery, scan timeout, heartbeat, and health check.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path, max_positions=7):
    return {
        'risk': {
            'account_size': 100000,
            'max_risk_per_trade': 2.0,
            'max_positions': max_positions,
            'profit_target': 50,
            'stop_loss_multiplier': 2.5,
        },
        'alpaca': {'enabled': False},
    }


def _make_opportunity(ticker='SPY', credit=1.50, max_loss=3.50,
                      short_strike=450, long_strike=445,
                      expiration='2025-06-20', score=75, dte=35):
    return {
        'ticker': ticker,
        'type': 'bull_put_spread',
        'short_strike': short_strike,
        'long_strike': long_strike,
        'expiration': expiration,
        'credit': credit,
        'max_loss': max_loss,
        'score': score,
        'dte': dte,
        'current_price': 460,
        'pop': 85,
        'short_delta': 0.12,
    }


def _make_trade(ticker='SPY', pnl=None, status='open', **overrides):
    trade = {
        'id': 'test-trade-1',
        'ticker': ticker,
        'type': 'bull_put_spread',
        'strategy_type': 'bull_put_spread',
        'short_strike': 450,
        'long_strike': 445,
        'expiration': '2025-06-20',
        'credit': 1.50,
        'credit_per_spread': 1.50,
        'max_loss': 3.50,
        'total_credit': 150.0,
        'total_max_loss': 350.0,
        'contracts': 1,
        'entry_price': 460,
        'entry_date': datetime.now(timezone.utc).isoformat(),
        'status': status,
        'profit_target_pct': 0.50,
        'stop_loss_pct': 2.50,
        'pnl': pnl,
    }
    trade.update(overrides)
    return trade


# ===========================================================================
# WP1: DataCache retry
# ===========================================================================

class TestDataCacheRetry:
    """Tests for _fetch_with_retry in DataCache."""

    def test_retry_succeeds_on_second_attempt(self):
        from shared.data_cache import DataCache

        df = pd.DataFrame({'Close': [100.0]})
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = [Exception("timeout"), df]

        with patch('shared.data_cache.yf.Ticker', return_value=mock_ticker), \
             patch('shared.data_cache.time.sleep'):
            cache = DataCache()
            result = cache._fetch_with_retry('SPY')
            assert not result.empty
            assert mock_ticker.history.call_count == 2

    def test_all_retries_exhausted_raises(self):
        from shared.data_cache import DataCache
        from shared.exceptions import DataFetchError

        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("network error")

        with patch('shared.data_cache.yf.Ticker', return_value=mock_ticker), \
             patch('shared.data_cache.time.sleep'):
            cache = DataCache()
            with pytest.raises(DataFetchError, match="network error"):
                cache._fetch_with_retry('SPY')
            assert mock_ticker.history.call_count == 3  # _MAX_RETRIES

    def test_retry_increments_metrics(self):
        from shared.data_cache import DataCache
        from shared.exceptions import DataFetchError
        from shared.metrics import metrics

        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("fail")

        before_retries = metrics._counters.get('data_fetch_retries', 0)
        before_failures = metrics._counters.get('data_fetch_failures', 0)

        with patch('shared.data_cache.yf.Ticker', return_value=mock_ticker), \
             patch('shared.data_cache.time.sleep'):
            cache = DataCache()
            with pytest.raises(DataFetchError):
                cache._fetch_with_retry('SPY')

        assert metrics._counters.get('data_fetch_retries', 0) - before_retries == 3
        assert metrics._counters.get('data_fetch_failures', 0) - before_failures == 1


# ===========================================================================
# WP2: Stale price fallback
# ===========================================================================

class TestEmptyPricesFallback:
    """Tests for stale price fallback in CreditSpreadSystem.scan_opportunities."""

    def _build_mock_system(self, tickers, stale_prices=None):
        """Build a minimally-mocked CreditSpreadSystem for scan_opportunities testing."""
        from main import CreditSpreadSystem

        with patch.object(CreditSpreadSystem, '__init__', lambda self, **kw: None):
            system = CreditSpreadSystem.__new__(CreditSpreadSystem)

        system.config = {
            'tickers': tickers,
            'strategy': {},
            'risk': {'account_size': 100000, 'max_risk_per_trade': 2.0,
                     'max_positions': 5, 'profit_target': 50, 'stop_loss_multiplier': 2.5},
            'alpaca': {'enabled': False},
        }
        system._last_known_prices = dict(stale_prices) if stale_prices else {}
        system.data_cache = MagicMock()
        system.paper_trader = MagicMock()
        system.paper_trader.open_trades = []
        system.paper_trader.execute_signals.return_value = []
        system.paper_trader.check_positions.return_value = []
        system.paper_trader.closed_trades = []
        system.paper_trader.trades = {"current_balance": 100000, "stats": {"total_pnl": 0}}

        # Mock all scanners/monitors
        for attr in ('zero_dte_scanner', 'iron_condor_scanner', 'momentum_scanner',
                     'earnings_scanner', 'gamma_scanner'):
            scanner = MagicMock()
            scanner.scan.return_value = []
            setattr(system, attr, scanner)
        for attr in ('zero_dte_exit_monitor', 'iron_condor_exit_monitor',
                     'momentum_exit_monitor', 'earnings_exit_monitor',
                     'gamma_exit_monitor'):
            setattr(system, attr, MagicMock())

        system.alert_generator = MagicMock()
        system.alert_generator.generate_alerts.return_value = {}
        system.telegram_bot = MagicMock()
        system.telegram_bot.enabled = False
        system.alert_router = MagicMock()
        system._champion_strategies = []
        system.ml_pipeline = None

        # Mock _analyze_ticker to return a dummy opportunity so we bypass the
        # early return on no-opportunities and reach the price-fetching loop.
        system._analyze_ticker = MagicMock(return_value=[_make_opportunity()])

        return system

    def test_stale_prices_used_when_fresh_fail(self):
        """If all fresh fetches fail, stale prices are used for check_positions."""
        system = self._build_mock_system(
            tickers=['SPY', 'QQQ'],
            stale_prices={'SPY': 450.0, 'QQQ': 380.0},
        )
        # _analyze_ticker succeeds (mocked), but price-fetching loop fails
        system.data_cache.get_history.side_effect = Exception("network error")
        system.paper_trader.open_trades = [_make_trade()]

        system.scan_opportunities()

        system.paper_trader.check_positions.assert_called_once()
        call_prices = system.paper_trader.check_positions.call_args[0][0]
        assert call_prices == {'SPY': 450.0, 'QQQ': 380.0}

    def test_fresh_prices_update_stale_cache(self):
        """Successful fresh fetches should update the stale price cache."""
        system = self._build_mock_system(tickers=['SPY'])

        df = pd.DataFrame({'Close': [455.0]})
        system.data_cache.get_history.return_value = df

        system.scan_opportunities()

        assert system._last_known_prices == {'SPY': 455.0}


# ===========================================================================
# WP3: Alpaca close retry
# ===========================================================================

@patch('paper_trader.db_close_trade')
@patch('paper_trader.upsert_trade')
@patch('paper_trader.get_trades', return_value=[])
@patch('paper_trader.init_db')
@patch('paper_trader.PAPER_LOG')
@patch('paper_trader.DATA_DIR')
class TestAlpacaCloseRetry:
    """Tests for the close-retry mechanism."""

    def _make_trader(self, mock_data_dir, mock_paper_log, tmp_path):
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt._log_trade_outcome = MagicMock()
        return pt

    def test_retry_succeeds_on_next_cycle(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_upsert, mock_db_close, tmp_path):
        """A failed Alpaca close should be retried and succeed on next check_positions."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        trade = _make_trade()
        # Under max retries — will call _close_trade which should succeed (no alpaca)
        trade["_close_retry"] = {"pnl": 75.0, "reason": "profit_target", "attempts": 1}
        pt._open_trades = [trade]

        pt._process_close_retries()

        # _close_trade should succeed (no alpaca_order_id → skips Alpaca)
        assert trade.get("status") == "closed"

    def test_exhausted_force_closes_and_alerts(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_upsert, mock_db_close, tmp_path):
        """After max retries, force-close locally and send desync alert."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        pt.telegram_bot = MagicMock()
        trade = _make_trade()
        trade["_close_retry"] = {"pnl": -100.0, "reason": "stop_loss", "attempts": 3}
        pt._open_trades = [trade]

        pt._process_close_retries()

        assert trade.get("status") == "closed"
        # send_alert called twice: exit alert + desync alert
        assert pt.telegram_bot.send_alert.call_count >= 1
        # Find the desync alert
        desync_calls = [c for c in pt.telegram_bot.send_alert.call_args_list
                       if "BROKER DESYNC" in str(c)]
        assert len(desync_calls) == 1

    def test_close_retry_increments_metric(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_upsert, mock_db_close, tmp_path):
        """Alpaca close failure should increment metrics."""
        from shared.metrics import metrics
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        mock_alpaca = MagicMock()
        mock_alpaca.close_spread.side_effect = Exception("broker down")
        pt.alpaca = mock_alpaca

        trade = _make_trade()
        trade["alpaca_order_id"] = "order-123"
        before = metrics._counters.get('alpaca_close_retries', 0)

        pt._close_trade(trade, 75.0, "profit_target")

        assert metrics._counters.get('alpaca_close_retries', 0) - before == 1
        assert "_close_retry" in trade


# ===========================================================================
# WP4A: Dedup failure logging
# ===========================================================================

@patch('paper_trader.db_close_trade')
@patch('paper_trader.upsert_trade')
@patch('paper_trader.get_trades')
@patch('paper_trader.init_db')
@patch('paper_trader.PAPER_LOG')
@patch('paper_trader.DATA_DIR')
class TestDedupFailureLogging:

    def test_db_dedup_failure_logged_not_silent(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_upsert, mock_db_close, tmp_path):
        """DB dedup check failure should log a warning, not silently pass."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False

        # First call for _load_trades returns [], second call for dedup raises
        mock_get_trades.side_effect = [[], Exception("DB locked")]

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt._log_trade_outcome = MagicMock()

        import logging
        with patch.object(logging.getLogger('paper_trader'), 'warning') as mock_warn:
            opp = _make_opportunity(score=75)
            pt._open_trade(opp)
            # Should have logged a warning about DB dedup failure
            warning_calls = [c for c in mock_warn.call_args_list
                           if 'dedup' in str(c).lower()]
            assert len(warning_calls) >= 1


# ===========================================================================
# WP4B: Startup reconcile without Alpaca
# ===========================================================================

@patch('paper_trader.db_close_trade')
@patch('paper_trader.upsert_trade')
@patch('paper_trader.get_trades')
@patch('paper_trader.init_db')
@patch('paper_trader.PAPER_LOG')
@patch('paper_trader.DATA_DIR')
class TestStartupReconcileDBOnly:

    def test_pending_open_promoted_without_alpaca(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_upsert, mock_db_close, tmp_path):
        """pending_open trades without alpaca_client_order_id should be promoted to open."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False

        pending_trade = _make_trade(status='pending_open')
        pending_trade.pop('alpaca_client_order_id', None)

        # get_trades is called multiple times:
        # 1. status="pending_open" for _startup_reconcile Phase 1
        # 2. source="scanner" for _load_trades
        def get_trades_side_effect(**kwargs):
            if kwargs.get('status') == 'pending_open':
                return [pending_trade]
            return [pending_trade]  # _load_trades sees it

        mock_get_trades.side_effect = get_trades_side_effect

        pt = PaperTrader(_make_config(tmp_path))

        # The trade should have been promoted to open via upsert
        upsert_calls = mock_upsert.call_args_list
        promoted = [c for c in upsert_calls
                   if c[0][0].get("status") == "open"]
        assert len(promoted) >= 1


# ===========================================================================
# WP4D: Drawdown auto-recovery
# ===========================================================================

@patch('paper_trader.db_close_trade')
@patch('paper_trader.upsert_trade')
@patch('paper_trader.get_trades', return_value=[])
@patch('paper_trader.init_db')
@patch('paper_trader.PAPER_LOG')
@patch('paper_trader.DATA_DIR')
class TestDrawdownRecovery:

    def test_trading_resumes_after_24h_cooldown(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_upsert, mock_db_close, tmp_path):
        """After drawdown kill switch triggers, trading should resume after 24h cooldown."""
        from paper_trader import _DRAWDOWN_COOLDOWN_HOURS

        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt._log_trade_outcome = MagicMock()

        # Set up: balance at 75k, peak at 100k = 25% drawdown > 20% threshold
        pt.trades["current_balance"] = 75000
        pt.trades["stats"]["peak_balance"] = 100000

        # First attempt: should be blocked (drawdown active)
        opp = _make_opportunity(score=80)
        result = pt._open_trade(opp)
        assert result is None
        assert pt._drawdown_triggered_at is not None

        # Simulate 24h+ having passed
        pt._drawdown_triggered_at = datetime.now(timezone.utc) - timedelta(
            hours=_DRAWDOWN_COOLDOWN_HOURS + 1
        )

        # Second attempt: should be allowed (cooldown expired)
        result = pt._open_trade(opp)
        assert result is not None


# ===========================================================================
# WP5: Scan timeout + heartbeat
# ===========================================================================

class TestScanTimeout:

    def test_timeout_does_not_crash_scheduler(self):
        """A scan that exceeds the timeout should not crash the scheduler."""
        from shared.scheduler import ScanScheduler, _SCAN_TIMEOUT_SECONDS

        call_count = 0

        def slow_scan(slot_type):
            nonlocal call_count
            call_count += 1
            time.sleep(10)  # much longer than our patched timeout

        scheduler = ScanScheduler(scan_fn=slow_scan, startup_delay=0)

        # Patch timeout to 0.1s so test runs fast
        with patch('shared.scheduler._SCAN_TIMEOUT_SECONDS', 0.1), \
             patch('shared.scheduler._HEARTBEAT_PATH', Path('/tmp/test_heartbeat.json')), \
             patch('shared.scheduler._next_scan_time') as mock_next, \
             patch('shared.scheduler._is_weekday', return_value=True):

            now = datetime.now(ScanScheduler.__module__ and __import__('pytz').timezone("America/New_York"))
            # Return a time in the very near past so scan fires immediately
            import pytz
            ET = pytz.timezone("America/New_York")
            now_et = datetime.now(ET)
            mock_next.return_value = (now_et - timedelta(seconds=1), "scan")

            # Run just one iteration
            def stop_after_one(*args, **kwargs):
                scheduler.stop()
                return False
            scheduler._stop_event.wait = MagicMock(side_effect=[False, True])

            scheduler.run_forever()

            # The scan was attempted
            assert call_count == 1

    def test_heartbeat_written_after_scan(self, tmp_path):
        """Heartbeat file should be written after a scan completes."""
        from shared.scheduler import ScanScheduler

        heartbeat_path = tmp_path / "heartbeat.json"

        def quick_scan(slot_type):
            pass

        scheduler = ScanScheduler(scan_fn=quick_scan, startup_delay=0)

        with patch('shared.scheduler._HEARTBEAT_PATH', heartbeat_path):
            scheduler._write_heartbeat("scan", error=False)

        assert heartbeat_path.exists()
        data = json.loads(heartbeat_path.read_text())
        assert data["last_slot_type"] == "scan"
        assert data["had_error"] is False
        assert "pid" in data


class TestHeartbeat:

    def test_heartbeat_marks_error_state(self, tmp_path):
        """Heartbeat should record error state correctly."""
        from shared.scheduler import ScanScheduler

        heartbeat_path = tmp_path / "heartbeat.json"
        scheduler = ScanScheduler(scan_fn=lambda st: None, startup_delay=0)

        with patch('shared.scheduler._HEARTBEAT_PATH', heartbeat_path):
            scheduler._write_heartbeat("scan", error=True)

        data = json.loads(heartbeat_path.read_text())
        assert data["had_error"] is True

    def test_heartbeat_increments_scan_count(self, tmp_path):
        """Heartbeat scan_count should reflect the scheduler's internal counter."""
        from shared.scheduler import ScanScheduler

        heartbeat_path = tmp_path / "heartbeat.json"
        scheduler = ScanScheduler(scan_fn=lambda st: None, startup_delay=0)
        scheduler._scan_count = 42

        with patch('shared.scheduler._HEARTBEAT_PATH', heartbeat_path):
            scheduler._write_heartbeat("scan", error=False)

        data = json.loads(heartbeat_path.read_text())
        assert data["scan_count"] == 42


# ===========================================================================
# WP6: Health check
# ===========================================================================

class TestHealthCheck:

    def test_no_heartbeat_file_unhealthy(self, tmp_path):
        """Missing heartbeat file should return unhealthy."""
        from scripts.health_check import check_health, STATUS_UNHEALTHY

        with patch('scripts.health_check.HEARTBEAT_PATH', tmp_path / 'missing.json'):
            result = check_health()
        assert result["status"] == STATUS_UNHEALTHY

    def test_fresh_heartbeat_healthy(self, tmp_path):
        """A fresh heartbeat with a live PID should be healthy."""
        from scripts.health_check import check_health, STATUS_HEALTHY

        heartbeat_file = tmp_path / "heartbeat.json"
        now_utc = datetime.now(timezone.utc)
        heartbeat_file.write_text(json.dumps({
            "last_scan_time": "2026-03-07 10:00:00",
            "last_scan_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_slot_type": "scan",
            "scan_count": 5,
            "had_error": False,
            "pid": os.getpid(),  # current PID is alive
        }))

        with patch('scripts.health_check.HEARTBEAT_PATH', heartbeat_file):
            result = check_health()
        assert result["status"] == STATUS_HEALTHY

    def test_stale_heartbeat_unhealthy(self, tmp_path):
        """A heartbeat older than max_age should be unhealthy."""
        from scripts.health_check import check_health, STATUS_UNHEALTHY

        heartbeat_file = tmp_path / "heartbeat.json"
        old_utc = datetime.now(timezone.utc) - timedelta(hours=2)
        heartbeat_file.write_text(json.dumps({
            "last_scan_time": "2026-03-07 08:00:00",
            "last_scan_utc": old_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_slot_type": "scan",
            "scan_count": 3,
            "had_error": False,
            "pid": os.getpid(),
        }))

        with patch('scripts.health_check.HEARTBEAT_PATH', heartbeat_file):
            result = check_health(max_age_minutes=45)
        assert result["status"] == STATUS_UNHEALTHY

    def test_error_state_degraded(self, tmp_path):
        """A fresh heartbeat with had_error=True should be degraded."""
        from scripts.health_check import check_health, STATUS_DEGRADED

        heartbeat_file = tmp_path / "heartbeat.json"
        now_utc = datetime.now(timezone.utc)
        heartbeat_file.write_text(json.dumps({
            "last_scan_time": "2026-03-07 10:00:00",
            "last_scan_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_slot_type": "scan",
            "scan_count": 5,
            "had_error": True,
            "pid": os.getpid(),
        }))

        with patch('scripts.health_check.HEARTBEAT_PATH', heartbeat_file):
            result = check_health()
        assert result["status"] == STATUS_DEGRADED

    def test_dead_pid_unhealthy(self, tmp_path):
        """A fresh heartbeat with a dead PID should be unhealthy."""
        from scripts.health_check import check_health, STATUS_UNHEALTHY

        heartbeat_file = tmp_path / "heartbeat.json"
        now_utc = datetime.now(timezone.utc)
        heartbeat_file.write_text(json.dumps({
            "last_scan_time": "2026-03-07 10:00:00",
            "last_scan_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_slot_type": "scan",
            "scan_count": 5,
            "had_error": False,
            "pid": 999999,  # unlikely to be alive
        }))

        with patch('scripts.health_check.HEARTBEAT_PATH', heartbeat_file):
            result = check_health()
        assert result["status"] == STATUS_UNHEALTHY


# Import at module level for the patched classes
from paper_trader import PaperTrader
