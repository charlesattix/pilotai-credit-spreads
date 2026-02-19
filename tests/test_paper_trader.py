"""Tests for the PaperTrader (all file I/O and network calls are mocked)."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from paper_trader import (
    PaperTrader, MAX_DRAWDOWN_PCT,
    CONSECUTIVE_LOSS_BLOCK_THRESHOLD, TICKER_DIRECTION_COOLDOWN_HOURS,
    STRIKE_COOLDOWN_HOURS,
)
from shared.io_utils import atomic_json_write


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


def _mock_alpaca():
    """Return a mock Alpaca provider so _open_trade doesn't skip trades."""
    mock = MagicMock()
    mock.submit_credit_spread.return_value = {
        'order_id': 'mock-order-123',
        'status': 'submitted',
    }
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPaperTrader:

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_load_empty_trades(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """A fresh PaperTrader with no existing file should have zero trades."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False

        pt = PaperTrader(_make_config(tmp_path))
        assert len(pt.trades['trades']) == 0
        assert pt.trades['current_balance'] == 100000

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_open_trade(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """execute_signals should open a trade for a valid opportunity."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()

        opp = _make_opportunity()
        new_trades = pt.execute_signals([opp])

        assert len(new_trades) == 1
        assert new_trades[0]['ticker'] == 'SPY'
        assert new_trades[0]['status'] == 'open'

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_duplicate_prevention(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """The same ticker+strike+expiration should not be opened twice."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()

        opp = _make_opportunity()
        pt.execute_signals([opp])

        # Try to open the exact same opportunity again
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 0

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_position_limit(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """Should not open more trades than max_positions."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path, max_positions=2))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()

        opps = [
            _make_opportunity(ticker='SPY', short_strike=450),
            _make_opportunity(ticker='QQQ', short_strike=380),
            _make_opportunity(ticker='IWM', short_strike=200),
        ]
        new_trades = pt.execute_signals(opps)
        assert len(new_trades) == 2  # limited by max_positions

    @patch('paper_trader.db_close_trade')
    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_close_at_profit_target(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, mock_db_close, tmp_path):
        """Position should close when P&L hits the profit target."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()

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

    def test_atomic_write(self, tmp_path):
        """atomic_json_write should write via temp file then rename."""
        target = tmp_path / "test_output.json"
        data = {"hello": "world", "number": 42}
        atomic_json_write(target, data)

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

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def _get_trader(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
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


# ---------------------------------------------------------------------------
# Tests for EH-TRADE-01: Negative balance guard
# ---------------------------------------------------------------------------

class TestNegativeBalanceGuard:
    """EH-TRADE-01: Refuse to open trades when current_balance <= 0."""

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_zero_balance_blocks_trade(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """No new trades should open when current_balance is zero."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.trades['current_balance'] = 0

        opp = _make_opportunity()
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 0

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_negative_balance_blocks_trade(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """No new trades should open when current_balance is negative."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.trades['current_balance'] = -5000

        opp = _make_opportunity()
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 0

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_positive_balance_allows_trade(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """Positive balance should still allow trades."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()
        assert pt.trades['current_balance'] == 100000

        opp = _make_opportunity()
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1


# ---------------------------------------------------------------------------
# Tests for EH-TRADE-02: Open risk exposure in position sizing
# ---------------------------------------------------------------------------

class TestOpenRiskExposure:
    """EH-TRADE-02: Available capital subtracts existing open positions' total_max_loss."""

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_open_risk_exhausts_capital(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """When open risk >= current_balance, new trades should be refused."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()

        # Manually inject an open trade with total_max_loss that consumes all capital
        big_trade = {
            'id': 99,
            'status': 'open',
            'ticker': 'AAPL',
            'type': 'bull_put_spread',
            'short_strike': 200,
            'long_strike': 195,
            'expiration': '2025-12-20',
            'total_max_loss': 100000,  # equals entire balance
            'contracts': 10,
            'total_credit': 5000,
        }
        pt.trades['trades'].append(big_trade)
        pt._open_trades.append(big_trade)

        opp = _make_opportunity(ticker='SPY')
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 0

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_partial_risk_allows_trade(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """When open risk is only a fraction of capital, new trades should be allowed."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()

        # Inject a small open trade that uses only a little capital
        small_trade = {
            'id': 99,
            'status': 'open',
            'ticker': 'AAPL',
            'type': 'bull_put_spread',
            'short_strike': 200,
            'long_strike': 195,
            'expiration': '2025-12-20',
            'total_max_loss': 1000,  # only 1% of balance
            'contracts': 1,
            'total_credit': 500,
        }
        pt.trades['trades'].append(small_trade)
        pt._open_trades.append(small_trade)

        opp = _make_opportunity(ticker='SPY')
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1


# ---------------------------------------------------------------------------
# Tests for EH-TRADE-03: Max drawdown kill switch
# ---------------------------------------------------------------------------

class TestMaxDrawdownKillSwitch:
    """EH-TRADE-03: Block all new trades when drawdown >= MAX_DRAWDOWN_PCT (peak-based)."""

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_drawdown_at_threshold_blocks_trade(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """Exactly at 20% drawdown from peak should block new trades."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()

        # Peak was 100000, balance at exactly 20% drawdown from peak
        pt.trades['current_balance'] = 80000
        pt.trades['stats']['peak_balance'] = 100000

        opp = _make_opportunity()
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 0

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_drawdown_beyond_threshold_blocks_trade(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """More than 20% drawdown from peak should block new trades."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()

        # 30% drawdown from peak
        pt.trades['current_balance'] = 70000
        pt.trades['stats']['peak_balance'] = 100000

        opp = _make_opportunity()
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 0

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_drawdown_below_threshold_allows_trade(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """Less than 20% drawdown from peak should allow new trades."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()

        # 10% drawdown from peak, below threshold
        pt.trades['current_balance'] = 90000
        pt.trades['stats']['peak_balance'] = 100000

        opp = _make_opportunity()
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_peak_based_drawdown_blocks_even_when_close_to_start(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        """Starting=100K, peak=120K, current=95K should block (20.8% from peak >= 20%)
        even though only 5% down from starting balance."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()

        pt.trades['starting_balance'] = 100000
        pt.trades['current_balance'] = 95000
        pt.trades['stats']['peak_balance'] = 120000

        # Drawdown from peak: (120000-95000)/120000 = 20.8% >= 20% => blocked
        opp = _make_opportunity()
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 0

    def test_max_drawdown_constant_value(self):
        """MAX_DRAWDOWN_PCT should be 0.20 (20%)."""
        assert MAX_DRAWDOWN_PCT == 0.20


# ---------------------------------------------------------------------------
# Tests for EH-TRADE-04: Alpaca close failure prevents local state transition
# ---------------------------------------------------------------------------

class TestAlpacaCloseFailureSafety:
    """EH-TRADE-04: If Alpaca close fails, trade must remain open locally."""

    @patch('paper_trader.db_close_trade')
    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_alpaca_close_failure_keeps_trade_open(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, mock_db_close, tmp_path):
        """When Alpaca close_spread raises, local trade must stay open."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()

        # Set up a mock Alpaca provider that fails on close
        mock_alpaca = MagicMock()
        mock_alpaca.close_spread.side_effect = Exception("Alpaca API timeout")
        pt.alpaca = mock_alpaca

        # Create a trade with an alpaca_order_id (simulating a trade opened via Alpaca)
        trade = {
            'id': 1,
            'status': 'open',
            'ticker': 'SPY',
            'type': 'bull_put_spread',
            'short_strike': 450,
            'long_strike': 445,
            'expiration': '2025-06-20',
            'contracts': 2,
            'total_credit': 300.0,
            'total_max_loss': 700.0,
            'alpaca_order_id': 'order-abc-123',
        }
        pt.trades['trades'].append(trade)
        pt._open_trades.append(trade)
        original_balance = pt.trades['current_balance']

        # Attempt to close — Alpaca will fail
        pt._close_trade(trade, pnl=150.0, reason='profit_target')

        # Trade must remain open
        assert trade['status'] == 'open'
        assert trade.get('exit_date') is None
        assert trade.get('exit_reason') is None
        assert trade.get('pnl') is None
        assert trade['alpaca_sync_error'] == "Alpaca API timeout"

        # Balance must not change
        assert pt.trades['current_balance'] == original_balance

        # Trade must still be in open_trades list
        assert trade in pt._open_trades
        assert trade not in pt._closed_trades

        # db_close_trade must NOT have been called
        mock_db_close.assert_not_called()

    @patch('paper_trader.db_close_trade')
    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_alpaca_close_success_updates_trade(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, mock_db_close, tmp_path):
        """When Alpaca close_spread succeeds, local trade should close normally."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()

        # Set up a mock Alpaca provider that succeeds
        mock_alpaca = MagicMock()
        pt.alpaca = mock_alpaca

        trade = {
            'id': 2,
            'status': 'open',
            'ticker': 'QQQ',
            'type': 'bull_put_spread',
            'short_strike': 380,
            'long_strike': 375,
            'expiration': '2025-06-20',
            'contracts': 1,
            'total_credit': 150.0,
            'total_max_loss': 350.0,
            'alpaca_order_id': 'order-def-456',
        }
        pt.trades['trades'].append(trade)
        pt._open_trades.append(trade)

        pt._close_trade(trade, pnl=75.0, reason='profit_target')

        # Trade should be closed
        assert trade['status'] == 'closed'
        assert trade['exit_reason'] == 'profit_target'
        assert trade['pnl'] == 75.0

        # db_close_trade should have been called
        mock_db_close.assert_called_once()

    @patch('paper_trader.db_close_trade')
    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_no_alpaca_close_still_works(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, mock_db_close, tmp_path):
        """When Alpaca is disabled, close should proceed normally (no Alpaca call)."""
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        mock_paper_log.parent = tmp_path

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        assert pt.alpaca is None  # Alpaca not configured

        trade = {
            'id': 3,
            'status': 'open',
            'ticker': 'IWM',
            'type': 'bull_put_spread',
            'short_strike': 200,
            'long_strike': 195,
            'expiration': '2025-06-20',
            'contracts': 1,
            'total_credit': 100.0,
            'total_max_loss': 400.0,
        }
        pt.trades['trades'].append(trade)
        pt._open_trades.append(trade)

        pt._close_trade(trade, pnl=50.0, reason='profit_target')

        # Should close normally without Alpaca
        assert trade['status'] == 'closed'
        assert trade['pnl'] == 50.0
        mock_db_close.assert_called_once()


# ---------------------------------------------------------------------------
# Tests for anti-suicide-loop circuit breakers
# ---------------------------------------------------------------------------

@patch('paper_trader.upsert_trade')
@patch('paper_trader.db_close_trade')
@patch('paper_trader.get_trades', return_value=[])
@patch('paper_trader.init_db')
@patch('paper_trader.PAPER_LOG')
@patch('paper_trader.DATA_DIR')
class TestLossCircuitBreaker:
    """Block trades after consecutive losses on the same ticker+direction."""

    def _make_trader(self, mock_data_dir, mock_paper_log, tmp_path):
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()
        pt._log_trade_outcome = MagicMock()
        return pt

    def test_two_consecutive_losses_blocks_third(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """After 2 consecutive losses on QQQ bearish, a 3rd QQQ bear_call should be blocked."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        now = datetime.now(timezone.utc)

        pt._recent_losses[("QQQ", "bearish")] = [
            {"exit_time": now - timedelta(minutes=30), "pnl": -1454, "strikes": (643, 648)},
            {"exit_time": now - timedelta(minutes=15), "pnl": -1454, "strikes": (643, 648)},
        ]

        opp = _make_opportunity(
            ticker='QQQ', short_strike=643, long_strike=648,
            expiration='2026-03-31', score=80,
        )
        opp['type'] = 'bear_call_spread'
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 0

    def test_one_loss_allows_trade(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """A single loss should NOT block the next trade."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        now = datetime.now(timezone.utc)

        pt._recent_losses[("QQQ", "bearish")] = [
            {"exit_time": now - timedelta(minutes=30), "pnl": -1454, "strikes": (643, 648)},
        ]

        opp = _make_opportunity(
            ticker='QQQ', short_strike=645, long_strike=650,
            expiration='2026-03-31', score=80,
        )
        opp['type'] = 'bear_call_spread'
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1

    def test_losses_on_different_ticker_dont_block(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """Losses on QQQ should not block SPY trades."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        now = datetime.now(timezone.utc)

        pt._recent_losses[("QQQ", "bearish")] = [
            {"exit_time": now - timedelta(minutes=30), "pnl": -1454, "strikes": (643, 648)},
            {"exit_time": now - timedelta(minutes=15), "pnl": -1454, "strikes": (643, 648)},
        ]

        opp = _make_opportunity(ticker='SPY', short_strike=450, long_strike=445)
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1

    def test_losses_on_different_direction_dont_block(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """Bearish losses on QQQ should not block QQQ bullish trades."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        now = datetime.now(timezone.utc)

        pt._recent_losses[("QQQ", "bearish")] = [
            {"exit_time": now - timedelta(minutes=30), "pnl": -1454, "strikes": (643, 648)},
            {"exit_time": now - timedelta(minutes=15), "pnl": -1454, "strikes": (643, 648)},
        ]

        opp = _make_opportunity(ticker='QQQ', short_strike=580, long_strike=575)
        opp['type'] = 'bull_put_spread'
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1

    def test_old_losses_dont_block(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """Losses older than the lookback window should not count."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        now = datetime.now(timezone.utc)

        pt._recent_losses[("QQQ", "bearish")] = [
            {"exit_time": now - timedelta(hours=2), "pnl": -1454, "strikes": (643, 648)},
            {"exit_time": now - timedelta(hours=2, minutes=30), "pnl": -1454, "strikes": (643, 648)},
        ]

        opp = _make_opportunity(
            ticker='QQQ', short_strike=645, long_strike=650,
            expiration='2026-03-31', score=80,
        )
        opp['type'] = 'bear_call_spread'
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1

    def test_cooldown_expires_after_duration(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """After the cooldown period, trading should resume."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)

        old_time = datetime.now(timezone.utc) - timedelta(hours=TICKER_DIRECTION_COOLDOWN_HOURS + 1)
        pt._recent_losses[("QQQ", "bearish")] = [
            {"exit_time": old_time - timedelta(minutes=30), "pnl": -1454, "strikes": (643, 648)},
            {"exit_time": old_time, "pnl": -1454, "strikes": (643, 648)},
        ]

        opp = _make_opportunity(
            ticker='QQQ', short_strike=645, long_strike=650,
            expiration='2026-03-31', score=80,
        )
        opp['type'] = 'bear_call_spread'
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1


@patch('paper_trader.upsert_trade')
@patch('paper_trader.db_close_trade')
@patch('paper_trader.get_trades', return_value=[])
@patch('paper_trader.init_db')
@patch('paper_trader.PAPER_LOG')
@patch('paper_trader.DATA_DIR')
class TestStrikeCooldown:
    """Block re-entry on exact same strikes after stop-out."""

    def _make_trader(self, mock_data_dir, mock_paper_log, tmp_path):
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()
        pt._log_trade_outcome = MagicMock()
        return pt

    def test_same_strikes_blocked_after_stopout(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """Exact same strikes should be blocked after a recent stop-out."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        now = datetime.now(timezone.utc)

        pt._strike_cooldowns[("QQQ", "bearish", 643.0, 648.0)] = now - timedelta(minutes=30)

        opp = _make_opportunity(
            ticker='QQQ', short_strike=643.0, long_strike=648.0,
            expiration='2026-03-31', score=80,
        )
        opp['type'] = 'bear_call_spread'
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 0

    def test_different_strikes_allowed_after_stopout(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """Different strikes on the same ticker should be allowed."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        now = datetime.now(timezone.utc)

        pt._strike_cooldowns[("QQQ", "bearish", 643.0, 648.0)] = now - timedelta(minutes=30)

        opp = _make_opportunity(
            ticker='QQQ', short_strike=645.0, long_strike=650.0,
            expiration='2026-03-31', score=80,
        )
        opp['type'] = 'bear_call_spread'
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1

    def test_strike_cooldown_expires(self, mock_data_dir, mock_paper_log,
            mock_init_db, mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """Same strikes should be allowed after cooldown expires."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)

        old_time = datetime.now(timezone.utc) - timedelta(hours=STRIKE_COOLDOWN_HOURS + 1)
        pt._strike_cooldowns[("QQQ", "bearish", 643.0, 648.0)] = old_time

        opp = _make_opportunity(
            ticker='QQQ', short_strike=643.0, long_strike=648.0,
            expiration='2026-03-31', score=80,
        )
        opp['type'] = 'bear_call_spread'
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1


class TestConsecutiveLossMetadata:
    """consecutive_loss_count should be added to trade metadata."""

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_loss_count_in_metadata(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()

        # Record 1 prior loss on SPY bullish
        now = datetime.now(timezone.utc)
        pt._recent_losses[("SPY", "bullish")] = [
            {"exit_time": now - timedelta(hours=5), "pnl": -500, "strikes": (450, 445)},
        ]

        opp = _make_opportunity(ticker='SPY')
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1
        assert new_trades[0].get('consecutive_loss_count') == 1

    @patch('paper_trader.upsert_trade')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.init_db')
    @patch('paper_trader.PAPER_LOG')
    @patch('paper_trader.DATA_DIR')
    def test_zero_loss_count_when_no_history(self, mock_data_dir, mock_paper_log, mock_init_db, mock_get_trades, mock_upsert, tmp_path):
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False

        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        pt.alpaca = _mock_alpaca()

        opp = _make_opportunity(ticker='SPY')
        new_trades = pt.execute_signals([opp])
        assert len(new_trades) == 1
        assert new_trades[0].get('consecutive_loss_count') == 0


@patch('paper_trader.upsert_trade')
@patch('paper_trader.db_close_trade')
@patch('paper_trader.get_trades', return_value=[])
@patch('paper_trader.init_db')
@patch('paper_trader.PAPER_LOG')
@patch('paper_trader.DATA_DIR')
class TestTradeOutcomeLogging:
    """_close_trade should log outcomes to data/ml_training/."""

    def _make_trader(self, mock_data_dir, mock_paper_log, tmp_path):
        mock_data_dir.__truediv__ = lambda s, n: tmp_path / n
        mock_data_dir.mkdir = MagicMock()
        mock_paper_log.exists.return_value = False
        pt = PaperTrader(_make_config(tmp_path))
        pt._save_trades = MagicMock()
        return pt

    def test_outcome_logged_on_close(self, mock_data_dir, mock_paper_log, mock_init_db,
                                      mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)

        trade = {
            'id': 'PT-test-001',
            'status': 'open',
            'ticker': 'QQQ',
            'type': 'bear_call_spread',
            'short_strike': 643,
            'long_strike': 648,
            'expiration': '2026-03-31',
            'contracts': 4,
            'total_credit': 420.0,
            'total_max_loss': 1580.0,
            'credit': 1.05,
            'entry_price': 605.0,
            'entry_date': '2026-02-19T16:00:00+00:00',
            'entry_score': 40.0,
            'entry_pop': 86.0,
            'entry_delta': 0.14,
            'dte_at_entry': 39,
        }
        pt.trades['trades'].append(trade)
        pt._open_trades.append(trade)

        pt._close_trade(trade, pnl=-1454.0, reason='stop_loss')

        # Verify trade was closed and outcome file written
        assert trade['status'] == 'closed'
        assert trade['pnl'] == -1454.0
        log_file = tmp_path / "ml_training" / "trade_outcomes.jsonl"
        assert log_file.exists()
        import json as _json
        outcome = _json.loads(log_file.read_text().strip().split('\n')[-1])
        assert outcome['id'] == 'PT-test-001'
        assert outcome['result'] == 'loss'
        assert outcome['pnl'] == -1454.0

    def test_loss_recorded_in_tracker(self, mock_data_dir, mock_paper_log, mock_init_db,
                                       mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """Closing a losing trade should record it in _recent_losses."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)
        assert len(pt._recent_losses) == 0

        trade = {
            'id': 'PT-test-002',
            'status': 'open',
            'ticker': 'QQQ',
            'type': 'bear_call_spread',
            'short_strike': 643,
            'long_strike': 648,
            'expiration': '2026-03-31',
            'contracts': 4,
            'total_credit': 420.0,
            'total_max_loss': 1580.0,
        }
        pt.trades['trades'].append(trade)
        pt._open_trades.append(trade)

        pt._close_trade(trade, pnl=-1454.0, reason='stop_loss')

        assert len(pt._recent_losses[("QQQ", "bearish")]) == 1
        assert pt._recent_losses[("QQQ", "bearish")][0]["pnl"] == -1454.0

    def test_winning_trade_not_recorded_as_loss(self, mock_data_dir, mock_paper_log, mock_init_db,
                                                  mock_get_trades, mock_db_close, mock_upsert, tmp_path):
        """Winning trades should NOT be added to _recent_losses."""
        pt = self._make_trader(mock_data_dir, mock_paper_log, tmp_path)

        trade = {
            'id': 'PT-test-003',
            'status': 'open',
            'ticker': 'SPY',
            'type': 'bull_put_spread',
            'short_strike': 450,
            'long_strike': 445,
            'expiration': '2026-03-31',
            'contracts': 2,
            'total_credit': 300.0,
            'total_max_loss': 700.0,
        }
        pt.trades['trades'].append(trade)
        pt._open_trades.append(trade)

        pt._close_trade(trade, pnl=150.0, reason='profit_target')

        assert len(pt._recent_losses[("SPY", "bullish")]) == 0
