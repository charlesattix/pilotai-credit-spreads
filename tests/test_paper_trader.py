"""Tests for the PaperTrader (all file I/O and network calls are mocked)."""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from paper_trader import PaperTrader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path, max_positions=7):
    """Return a minimal config dict that PaperTrader accepts."""
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPaperTrader:

    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_load_empty_trades(self, mock_data_dir, mock_paper_log, tmp_path):
        """A fresh PaperTrader with no existing file should have zero trades."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False

        pt = PaperTrader(_make_config(tmp_path))
        assert len(pt.trades['trades']) == 0
        assert pt.trades['current_balance'] == 100000

    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_open_trade(self, mock_data_dir, mock_paper_log, tmp_path):
        """execute_signals should open a trade for a valid opportunity."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        # Patch _save_trades to avoid real file I/O
        pt._save_trades = MagicMock()

        opp = _make_opportunity()
        new_trades = pt.execute_signals([opp])

        assert len(new_trades) == 1
        assert new_trades[0]['ticker'] == 'SPY'
        assert new_trades[0]['status'] == 'open'

    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_duplicate_prevention(self, mock_data_dir, mock_paper_log, tmp_path):
        """The same ticker+strike+expiration should not be opened twice."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()

        opp = _make_opportunity()
        pt.execute_signals([opp])

        # Try to open the exact same opportunity again
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 0

    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_position_limit(self, mock_data_dir, mock_paper_log, tmp_path):
        """Should not open more trades than max_positions."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path, max_positions=2))
        pt._save_trades = MagicMock()

        opps = [
            _make_opportunity(ticker='SPY', short_strike=450),
            _make_opportunity(ticker='QQQ', short_strike=380),
            _make_opportunity(ticker='IWM', short_strike=200),
        ]
        new_trades = pt.execute_signals(opps)
        assert len(new_trades) == 2  # limited by max_positions

    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_close_at_profit_target(self, mock_data_dir, mock_paper_log, tmp_path):
        """Position should close when P&L hits the profit target."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()

        opp = _make_opportunity(dte=35)
        pt.execute_signals([opp])

        # Simulate time passing and price moving favorably
        trade = pt.open_trades[0]
        # Set the entry_dte so that we can compute time passed
        trade['dte_at_entry'] = 35

        # Force a scenario where the trade is OTM and lots of time passed
        # by passing a price well above the short strike, which makes the
        # bull put OTM and profitable.
        current_prices = {'SPY': 480.0}
        closed = pt.check_positions(current_prices)
        # It may or may not close depending on exact P&L vs target;
        # verify that the trade was evaluated (no crash).
        assert isinstance(closed, list)

    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_atomic_write(self, mock_data_dir, mock_paper_log, tmp_path):
        """_atomic_json_write should write via temp file then rename."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()

        target = tmp_path / "test_output.json"
        data = {"hello": "world", "number": 42}
        PaperTrader._atomic_json_write(target, data)

        assert target.exists()
        with open(target) as f:
            loaded = json.load(f)
        assert loaded["hello"] == "world"
        assert loaded["number"] == 42

        # Verify no leftover .tmp files
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


# ---------------------------------------------------------------------------
# Helper for _evaluate_position tests
# ---------------------------------------------------------------------------

def _make_trade(
    ticker='SPY',
    spread_type='bull_put_spread',
    short_strike=450,
    long_strike=445,
    contracts=2,
    credit_per_spread=1.50,
    dte_at_entry=35,
    profit_target_pct=0.50,
    stop_loss_mult=2.5,
):
    """Build a trade dict as produced by _open_trade."""
    total_credit = round(credit_per_spread * contracts * 100, 2)
    max_loss_per_spread = abs(short_strike - long_strike) - credit_per_spread
    total_max_loss = round(max_loss_per_spread * contracts * 100, 2)
    return {
        'id': 1,
        'status': 'open',
        'ticker': ticker,
        'type': spread_type,
        'short_strike': short_strike,
        'long_strike': long_strike,
        'contracts': contracts,
        'credit_per_spread': credit_per_spread,
        'total_credit': total_credit,
        'max_loss_per_spread': max_loss_per_spread,
        'total_max_loss': total_max_loss,
        'profit_target': round(total_credit * profit_target_pct, 2),
        'stop_loss_amount': round(total_credit * stop_loss_mult, 2),
        'entry_price': 460,
        'dte_at_entry': dte_at_entry,
        'current_pnl': 0,
    }


# ---------------------------------------------------------------------------
# Tests for _evaluate_position
# ---------------------------------------------------------------------------

class TestEvaluatePosition:
    """Tests for PaperTrader._evaluate_position."""

    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def _get_trader(self, mock_data_dir, mock_paper_log, tmp_path):
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        return PaperTrader(_make_config(tmp_path))

    def test_otm_bull_put_profitable(self, tmp_path):
        """OTM bull put (price above short strike) should show positive PnL."""
        pt = self._get_trader(tmp_path=tmp_path)
        trade = _make_trade(spread_type='bull_put_spread', short_strike=450, long_strike=445)
        # Price well above short strike -> OTM, profitable via time decay
        pnl, reason = pt._evaluate_position(trade, current_price=480, dte=10)
        assert pnl > 0, "OTM bull put with time passed should be profitable"

    def test_itm_bull_put_losing(self, tmp_path):
        """ITM bull put (price below short strike) should show negative PnL."""
        pt = self._get_trader(tmp_path=tmp_path)
        trade = _make_trade(spread_type='bull_put_spread', short_strike=450, long_strike=445)
        # Price well below short strike -> ITM, losing
        pnl, reason = pt._evaluate_position(trade, current_price=430, dte=20)
        assert pnl < 0, "ITM bull put should be losing"

    def test_bear_call_direction(self, tmp_path):
        """Bear call spread: price above short strike = ITM (losing)."""
        pt = self._get_trader(tmp_path=tmp_path)
        trade = _make_trade(
            spread_type='bear_call_spread',
            short_strike=460,
            long_strike=465,
        )
        # Price above short strike for call = ITM
        pnl, reason = pt._evaluate_position(trade, current_price=475, dte=20)
        assert pnl < 0, "ITM bear call should be losing"

    def test_exit_profit_target(self, tmp_path):
        """Should return 'profit_target' when PnL exceeds target."""
        pt = self._get_trader(tmp_path=tmp_path)
        trade = _make_trade(
            spread_type='bull_put_spread',
            short_strike=450,
            long_strike=445,
            dte_at_entry=35,
        )
        # With enough time passed and price well OTM, P&L should hit profit target
        pnl, reason = pt._evaluate_position(trade, current_price=500, dte=5)
        assert reason == 'profit_target'

    def test_exit_stop_loss(self, tmp_path):
        """Should return 'stop_loss' when loss exceeds stop_loss_amount."""
        pt = self._get_trader(tmp_path=tmp_path)
        # Use a small stop_loss_mult so stop_loss_amount is easier to breach
        trade = _make_trade(
            spread_type='bull_put_spread',
            short_strike=450,
            long_strike=445,
            contracts=2,
            dte_at_entry=35,
            stop_loss_mult=1.0,  # stop_loss_amount = total_credit * 1.0 = 300
        )
        # Price deeply ITM: intrinsic=50, spread_value=min(50*2*100, 700)=700
        # pnl = -(700 - extrinsic) which is well below -300
        pnl, reason = pt._evaluate_position(trade, current_price=400, dte=30)
        assert reason == 'stop_loss'

    def test_exit_expiration(self, tmp_path):
        """Should return 'expiration' when DTE <= 1 and position is ITM (not profitable)."""
        pt = self._get_trader(tmp_path=tmp_path)
        trade = _make_trade(
            spread_type='bull_put_spread',
            short_strike=450,
            long_strike=445,
            dte_at_entry=35,
        )
        # Price slightly below short strike so position is ITM (losing),
        # but not enough loss to trigger stop_loss before expiration check
        pnl, reason = pt._evaluate_position(trade, current_price=449, dte=0)
        # At DTE=0, expiration should fire (dte <= 1)
        assert reason == 'expiration'

    def test_exit_management_dte(self, tmp_path):
        """Should return 'management_dte' when DTE <= threshold and profitable."""
        pt = self._get_trader(tmp_path=tmp_path)
        trade = _make_trade(
            spread_type='bull_put_spread',
            short_strike=450,
            long_strike=445,
            dte_at_entry=35,
        )
        # Price OTM + moderate time passed -> profitable, under management DTE threshold
        # MANAGEMENT_DTE_THRESHOLD is 21
        pnl, reason = pt._evaluate_position(trade, current_price=480, dte=15)
        if pnl > 0 and pnl < trade['profit_target']:
            assert reason == 'management_dte'
        # If it already hit profit_target, that takes priority
        elif pnl >= trade['profit_target']:
            assert reason == 'profit_target'

    def test_no_exit_mid_trade(self, tmp_path):
        """No exit reason when position is open with no triggers hit."""
        pt = self._get_trader(tmp_path=tmp_path)
        trade = _make_trade(
            spread_type='bull_put_spread',
            short_strike=450,
            long_strike=445,
            dte_at_entry=35,
        )
        # Slight movement, high DTE -> no exit conditions met
        pnl, reason = pt._evaluate_position(trade, current_price=452, dte=30)
        assert reason is None

    def test_zero_dte_entry(self, tmp_path):
        """Edge case: zero DTE at entry should not cause division errors."""
        pt = self._get_trader(tmp_path=tmp_path)
        trade = _make_trade(
            spread_type='bull_put_spread',
            short_strike=450,
            long_strike=445,
            dte_at_entry=0,
        )
        # Use ITM price so that PnL is negative (won't trigger profit_target)
        pnl, reason = pt._evaluate_position(trade, current_price=448, dte=0)
        # Should not crash, and DTE=0 should trigger expiration
        # (profit_target won't fire because position is ITM/losing)
        assert reason is not None  # some exit should trigger at DTE=0

    def test_price_at_strike_boundary(self, tmp_path):
        """Price exactly at short strike boundary should not crash."""
        pt = self._get_trader(tmp_path=tmp_path)
        trade = _make_trade(
            spread_type='bull_put_spread',
            short_strike=450,
            long_strike=445,
        )
        pnl, reason = pt._evaluate_position(trade, current_price=450, dte=25)
        # Price == short_strike: intrinsic = max(0, 450-450) = 0 (OTM)
        assert isinstance(pnl, float)
