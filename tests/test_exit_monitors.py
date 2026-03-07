"""
Comprehensive tests for all four exit monitors:
- EarningsExitMonitor
- GammaExitMonitor
- IronCondorExitMonitor
- MomentumExitMonitor

Each monitor follows the same pattern:
- Takes paper_trader, telegram_bot, optional formatter in __init__
- check_and_alert(current_prices, now_et=None) returns list of triggered dicts
- Composite dedup keys (trade_id:reason) in self._alerted
- Calls self._paper_trader._evaluate_position(trade, price, dte=0) for P&L
- Filters by strategy_type/type keywords
- Skips trades with no id, no price, or zero credit/debit
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from alerts.earnings_exit_monitor import EarningsExitMonitor
from alerts.gamma_exit_monitor import GammaExitMonitor
from alerts.iron_condor_exit_monitor import IronCondorExitMonitor
from alerts.momentum_exit_monitor import MomentumExitMonitor


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_paper_trader(trades, pnl_return=(0.0, None)):
    """Create a MagicMock paper trader with open_trades and _evaluate_position."""
    pt = MagicMock()
    pt.open_trades = trades
    pt._evaluate_position.return_value = pnl_return
    return pt


def _make_telegram_bot():
    """Create a MagicMock telegram bot."""
    return MagicMock()


def _make_formatter():
    """Create a MagicMock formatter that returns a fixed string."""
    fmt = MagicMock()
    fmt.format_exit_alert.return_value = "ALERT_MSG"
    return fmt


# ─────────────────────────────────────────────────────────────────────────────
# TestEarningsExitMonitor
# ─────────────────────────────────────────────────────────────────────────────

class TestEarningsExitMonitor:
    """Tests for EarningsExitMonitor (~8 tests)."""

    def test_non_earnings_trade_skipped(self):
        """Trade with type 'bull_put_spread' (no 'earnings' keyword) is ignored."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "bull_put_spread",
            "type": "bull_put_spread",
            "total_credit": 200.0,
        }
        pt = _make_paper_trader([trade], pnl_return=(150.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = EarningsExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        assert triggered == []
        pt._evaluate_position.assert_not_called()
        bot.send_alert.assert_not_called()

    def test_post_earnings_fires_alert(self):
        """Trade with earnings_date in the past triggers post_earnings alert."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "earnings_iron_condor",
            "type": "earnings_iron_condor",
            "total_credit": 200.0,
            "earnings_date": "2026-03-06T00:00:00+00:00",
        }
        pt = _make_paper_trader([trade], pnl_return=(50.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = EarningsExitMonitor(pt, bot, formatter=fmt)
        # now_et is after earnings_date
        post = datetime(2026, 3, 7, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        triggered = monitor.check_and_alert({"AAPL": 150.0}, now_et=post)

        reasons = [t["reason"] for t in triggered]
        assert "post_earnings" in reasons
        bot.send_alert.assert_called()

    def test_profit_target_50pct(self):
        """P&L >= 50% of total_credit triggers profit_target alert."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "earnings_iron_condor",
            "type": "earnings_iron_condor",
            "total_credit": 200.0,
        }
        # P&L of 100.0 = 50% of 200.0 credit
        pt = _make_paper_trader([trade], pnl_return=(100.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = EarningsExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        reasons = [t["reason"] for t in triggered]
        assert "profit_target" in reasons
        bot.send_alert.assert_called()

    def test_stop_loss_2x(self):
        """P&L <= -2x total_credit triggers stop_loss alert."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "earnings_iron_condor",
            "type": "earnings_iron_condor",
            "total_credit": 200.0,
        }
        # P&L of -400.0 = -(2 * 200.0)
        pt = _make_paper_trader([trade], pnl_return=(-400.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = EarningsExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        reasons = [t["reason"] for t in triggered]
        assert "stop_loss" in reasons
        bot.send_alert.assert_called()

    def test_missing_earnings_date_no_post_earnings(self):
        """Trade without earnings_date doesn't fire post_earnings alert."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "earnings_iron_condor",
            "type": "earnings_iron_condor",
            "total_credit": 200.0,
            # No earnings_date key
        }
        # P&L of 0 -- below all thresholds
        pt = _make_paper_trader([trade], pnl_return=(0.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = EarningsExitMonitor(pt, bot, formatter=fmt)
        post = datetime(2026, 3, 7, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        triggered = monitor.check_and_alert({"AAPL": 150.0}, now_et=post)

        reasons = [t["reason"] for t in triggered]
        assert "post_earnings" not in reasons

    def test_dedup_suppresses_repeat(self):
        """Same alert doesn't fire twice for the same trade_id:reason pair."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "earnings_iron_condor",
            "type": "earnings_iron_condor",
            "total_credit": 200.0,
        }
        # Profit target threshold (100 >= 200 * 0.50)
        pt = _make_paper_trader([trade], pnl_return=(100.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = EarningsExitMonitor(pt, bot, formatter=fmt)
        first = monitor.check_and_alert({"AAPL": 150.0})
        second = monitor.check_and_alert({"AAPL": 150.0})

        assert len([t for t in first if t["reason"] == "profit_target"]) == 1
        assert len([t for t in second if t["reason"] == "profit_target"]) == 0

    def test_zero_credit_skipped(self):
        """Trade with total_credit=0 is skipped entirely."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "earnings_iron_condor",
            "type": "earnings_iron_condor",
            "total_credit": 0,
        }
        pt = _make_paper_trader([trade], pnl_return=(50.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = EarningsExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        assert triggered == []
        pt._evaluate_position.assert_not_called()

    def test_telegram_failure_doesnt_crash(self):
        """telegram_bot.send_alert raising an exception doesn't crash the monitor."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "earnings_iron_condor",
            "type": "earnings_iron_condor",
            "total_credit": 200.0,
        }
        # Profit target threshold
        pt = _make_paper_trader([trade], pnl_return=(100.0, None))
        bot = _make_telegram_bot()
        bot.send_alert.side_effect = RuntimeError("Telegram API down")
        fmt = _make_formatter()

        monitor = EarningsExitMonitor(pt, bot, formatter=fmt)
        # Should not raise
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        # Alert is still recorded in triggered (it was attempted)
        reasons = [t["reason"] for t in triggered]
        assert "profit_target" in reasons


# ─────────────────────────────────────────────────────────────────────────────
# TestGammaExitMonitor
# ─────────────────────────────────────────────────────────────────────────────

class TestGammaExitMonitor:
    """Tests for GammaExitMonitor (~7 tests)."""

    def test_non_gamma_trade_skipped(self):
        """Trade with type 'bull_put_spread' (no 'gamma'/'lotto' keyword) is ignored."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "bull_put_spread",
            "type": "bull_put_spread",
            "debit": 1.50,
        }
        pt = _make_paper_trader([trade], pnl_return=(500.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = GammaExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        assert triggered == []
        pt._evaluate_position.assert_not_called()
        bot.send_alert.assert_not_called()

    def test_trailing_stop_activation_at_3x(self):
        """P&L >= 3x debit*100 activates trailing stop and fires activation alert."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "gamma_lotto",
            "type": "gamma_lotto",
            "debit": 1.50,
        }
        # Activation threshold: 1.50 * 3.0 * 100 = 450.0
        pt = _make_paper_trader([trade], pnl_return=(450.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = GammaExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        reasons = [t["reason"] for t in triggered]
        assert "trailing_stop_activation" in reasons
        bot.send_alert.assert_called()

    def test_trailing_stop_triggered_below_2x(self):
        """After activation, P&L drops below 2x debit*100 fires trailing_stop_triggered."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "gamma_lotto",
            "type": "gamma_lotto",
            "debit": 1.50,
        }
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        # First call: activate at 3x (450.0)
        pt = _make_paper_trader([trade], pnl_return=(450.0, None))
        monitor = GammaExitMonitor(pt, bot, formatter=fmt)
        first = monitor.check_and_alert({"AAPL": 150.0})
        assert "trailing_stop_activation" in [t["reason"] for t in first]

        # Second call: P&L drops below 2x (< 300.0)
        pt._evaluate_position.return_value = (250.0, None)
        second = monitor.check_and_alert({"AAPL": 145.0})

        reasons = [t["reason"] for t in second]
        assert "trailing_stop_triggered" in reasons

    def test_expired_worthless(self):
        """P&L <= -(debit*100) fires expired_worthless alert."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "gamma_lotto",
            "type": "gamma_lotto",
            "debit": 1.50,
        }
        # Expired worthless threshold: -(1.50 * 100) = -150.0
        pt = _make_paper_trader([trade], pnl_return=(-150.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = GammaExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        reasons = [t["reason"] for t in triggered]
        assert "expired_worthless" in reasons
        bot.send_alert.assert_called()

    def test_no_activation_below_3x(self):
        """P&L < 3x debit*100 doesn't activate trailing stop."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "gamma_lotto",
            "type": "gamma_lotto",
            "debit": 1.50,
        }
        # Below activation threshold: 449.0 < 450.0
        pt = _make_paper_trader([trade], pnl_return=(449.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = GammaExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        reasons = [t["reason"] for t in triggered]
        assert "trailing_stop_activation" not in reasons

    def test_trailing_not_triggered_without_activation(self):
        """P&L < 2x debit*100 without prior activation doesn't fire trailing_stop_triggered."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "gamma_lotto",
            "type": "gamma_lotto",
            "debit": 1.50,
        }
        # P&L below 2x threshold but no activation happened
        pt = _make_paper_trader([trade], pnl_return=(200.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = GammaExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        reasons = [t["reason"] for t in triggered]
        assert "trailing_stop_triggered" not in reasons

    def test_dedup_suppresses_repeat(self):
        """Same alert doesn't fire twice for the same trade_id:reason pair."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "gamma_lotto",
            "type": "gamma_lotto",
            "debit": 1.50,
        }
        # Expired worthless threshold
        pt = _make_paper_trader([trade], pnl_return=(-150.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = GammaExitMonitor(pt, bot, formatter=fmt)
        first = monitor.check_and_alert({"AAPL": 150.0})
        second = monitor.check_and_alert({"AAPL": 150.0})

        assert len([t for t in first if t["reason"] == "expired_worthless"]) == 1
        assert len([t for t in second if t["reason"] == "expired_worthless"]) == 0


# ─────────────────────────────────────────────────────────────────────────────
# TestIronCondorExitMonitor
# ─────────────────────────────────────────────────────────────────────────────

class TestIronCondorExitMonitor:
    """Tests for IronCondorExitMonitor (~7 tests)."""

    def test_non_condor_trade_skipped(self):
        """Trade with type 'bull_put_spread' (no 'condor' keyword) is ignored."""
        trade = {
            "id": "test-1",
            "ticker": "SPY",
            "strategy_type": "bull_put_spread",
            "type": "bull_put_spread",
            "total_credit": 200.0,
        }
        pt = _make_paper_trader([trade], pnl_return=(150.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = IronCondorExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"SPY": 450.0})

        assert triggered == []
        pt._evaluate_position.assert_not_called()
        bot.send_alert.assert_not_called()

    def test_profit_target_50pct(self):
        """P&L >= 50% of total_credit triggers profit_target alert."""
        trade = {
            "id": "test-1",
            "ticker": "SPY",
            "strategy_type": "iron_condor",
            "type": "iron_condor",
            "total_credit": 200.0,
        }
        # P&L of 100.0 = 50% of 200.0 credit
        pt = _make_paper_trader([trade], pnl_return=(100.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = IronCondorExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"SPY": 450.0})

        reasons = [t["reason"] for t in triggered]
        assert "profit_target" in reasons
        bot.send_alert.assert_called()

    def test_stop_loss_2x(self):
        """P&L <= -2x total_credit triggers stop_loss alert."""
        trade = {
            "id": "test-1",
            "ticker": "SPY",
            "strategy_type": "iron_condor",
            "type": "iron_condor",
            "total_credit": 200.0,
        }
        # P&L of -400.0 = -(2 * 200.0)
        pt = _make_paper_trader([trade], pnl_return=(-400.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = IronCondorExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"SPY": 450.0})

        reasons = [t["reason"] for t in triggered]
        assert "stop_loss" in reasons
        bot.send_alert.assert_called()

    def test_thursday_weekly_close_warning(self):
        """weekday=3 (Thursday) fires weekly_close_warning alert."""
        trade = {
            "id": "test-1",
            "ticker": "SPY",
            "strategy_type": "iron_condor",
            "type": "iron_condor",
            "total_credit": 200.0,
        }
        # P&L below profit/stop thresholds
        pt = _make_paper_trader([trade], pnl_return=(10.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = IronCondorExitMonitor(pt, bot, formatter=fmt)
        thursday = datetime(2026, 3, 5, 14, 0, tzinfo=ZoneInfo("America/New_York"))
        triggered = monitor.check_and_alert({"SPY": 450.0}, now_et=thursday)

        reasons = [t["reason"] for t in triggered]
        assert "weekly_close_warning" in reasons
        bot.send_alert.assert_called()

    def test_friday_close_now(self):
        """weekday=4 (Friday) fires weekly_close_now alert."""
        trade = {
            "id": "test-1",
            "ticker": "SPY",
            "strategy_type": "iron_condor",
            "type": "iron_condor",
            "total_credit": 200.0,
        }
        # P&L below profit/stop thresholds
        pt = _make_paper_trader([trade], pnl_return=(10.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = IronCondorExitMonitor(pt, bot, formatter=fmt)
        friday = datetime(2026, 3, 6, 14, 0, tzinfo=ZoneInfo("America/New_York"))
        triggered = monitor.check_and_alert({"SPY": 450.0}, now_et=friday)

        reasons = [t["reason"] for t in triggered]
        assert "weekly_close_now" in reasons
        bot.send_alert.assert_called()

    def test_non_thursday_no_warning(self):
        """weekday != 3 or 4 doesn't fire weekly close alerts."""
        trade = {
            "id": "test-1",
            "ticker": "SPY",
            "strategy_type": "iron_condor",
            "type": "iron_condor",
            "total_credit": 200.0,
        }
        # P&L below profit/stop thresholds
        pt = _make_paper_trader([trade], pnl_return=(10.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = IronCondorExitMonitor(pt, bot, formatter=fmt)
        wednesday = datetime(2026, 3, 4, 14, 0, tzinfo=ZoneInfo("America/New_York"))
        triggered = monitor.check_and_alert({"SPY": 450.0}, now_et=wednesday)

        reasons = [t["reason"] for t in triggered]
        assert "weekly_close_warning" not in reasons
        assert "weekly_close_now" not in reasons

    def test_dedup_suppresses_repeat(self):
        """Same alert doesn't fire twice for the same trade_id:reason pair."""
        trade = {
            "id": "test-1",
            "ticker": "SPY",
            "strategy_type": "iron_condor",
            "type": "iron_condor",
            "total_credit": 200.0,
        }
        # Profit target threshold
        pt = _make_paper_trader([trade], pnl_return=(100.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = IronCondorExitMonitor(pt, bot, formatter=fmt)
        first = monitor.check_and_alert({"SPY": 450.0})
        second = monitor.check_and_alert({"SPY": 450.0})

        assert len([t for t in first if t["reason"] == "profit_target"]) == 1
        assert len([t for t in second if t["reason"] == "profit_target"]) == 0


# ─────────────────────────────────────────────────────────────────────────────
# TestMomentumExitMonitor
# ─────────────────────────────────────────────────────────────────────────────

class TestMomentumExitMonitor:
    """Tests for MomentumExitMonitor (~6 tests)."""

    def test_non_momentum_trade_skipped(self):
        """Trade with type 'iron_condor' (no 'debit'/'momentum' keyword) is ignored."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "iron_condor",
            "type": "iron_condor",
            "total_debit": 150.0,
        }
        pt = _make_paper_trader([trade], pnl_return=(200.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = MomentumExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        assert triggered == []
        pt._evaluate_position.assert_not_called()
        bot.send_alert.assert_not_called()

    def test_profit_target_100pct(self):
        """P&L >= 100% of total_debit triggers profit_target alert."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "debit_spread",
            "type": "debit_spread",
            "total_debit": 150.0,
            "dte": 10,
        }
        # P&L of 150.0 = 100% of 150.0 debit
        pt = _make_paper_trader([trade], pnl_return=(150.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = MomentumExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        reasons = [t["reason"] for t in triggered]
        assert "profit_target" in reasons
        bot.send_alert.assert_called()

    def test_stop_loss_50pct(self):
        """P&L <= -50% of total_debit triggers stop_loss alert."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "debit_spread",
            "type": "debit_spread",
            "total_debit": 150.0,
            "dte": 10,
        }
        # P&L of -75.0 = -(50% of 150.0)
        pt = _make_paper_trader([trade], pnl_return=(-75.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = MomentumExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        reasons = [t["reason"] for t in triggered]
        assert "stop_loss" in reasons
        bot.send_alert.assert_called()

    def test_time_decay_dte_3(self):
        """Trade with dte=3 fires time_decay warning."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "debit_spread",
            "type": "debit_spread",
            "total_debit": 150.0,
            "dte": 3,
        }
        # P&L below profit/stop thresholds
        pt = _make_paper_trader([trade], pnl_return=(10.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = MomentumExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        reasons = [t["reason"] for t in triggered]
        assert "time_decay" in reasons
        bot.send_alert.assert_called()

    def test_time_decay_not_fired_dte_4(self):
        """Trade with dte=4 does NOT fire time_decay warning (threshold is <= 3)."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "debit_spread",
            "type": "debit_spread",
            "total_debit": 150.0,
            "dte": 4,
        }
        # P&L below profit/stop thresholds
        pt = _make_paper_trader([trade], pnl_return=(10.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = MomentumExitMonitor(pt, bot, formatter=fmt)
        triggered = monitor.check_and_alert({"AAPL": 150.0})

        reasons = [t["reason"] for t in triggered]
        assert "time_decay" not in reasons

    def test_dedup_suppresses_repeat(self):
        """Same alert doesn't fire twice for the same trade_id:reason pair."""
        trade = {
            "id": "test-1",
            "ticker": "AAPL",
            "strategy_type": "debit_spread",
            "type": "debit_spread",
            "total_debit": 150.0,
            "dte": 10,
        }
        # Profit target threshold
        pt = _make_paper_trader([trade], pnl_return=(150.0, None))
        bot = _make_telegram_bot()
        fmt = _make_formatter()

        monitor = MomentumExitMonitor(pt, bot, formatter=fmt)
        first = monitor.check_and_alert({"AAPL": 150.0})
        second = monitor.check_and_alert({"AAPL": 150.0})

        assert len([t for t in first if t["reason"] == "profit_target"]) == 1
        assert len([t for t in second if t["reason"] == "profit_target"]) == 0
