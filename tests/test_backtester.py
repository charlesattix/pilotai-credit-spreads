"""Tests for the Backtester class."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from backtest.backtester import Backtester


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config():
    """Minimal config for Backtester."""
    return {
        'backtest': {
            'starting_capital': 100000,
            'commission_per_contract': 0.65,
            'slippage': 0.05,
        },
        'strategy': {
            'spread_width': 5,
        },
        'risk': {
            'max_positions': 5,
            'max_risk_per_trade': 2.0,
            'stop_loss_multiplier': 2.5,
        },
    }


def _make_position(
    credit=1.50,
    max_loss=3.50,
    short_strike=450,
    long_strike=445,
    contracts=1,
    commission=1.30,
    entry_date=None,
    expiration=None,
    spread_type='bull_put_spread',
    option_type='P',
):
    """Return a minimal position dict for testing."""
    entry_date = entry_date or datetime(2025, 1, 1)
    expiration = expiration or datetime(2025, 2, 5)
    return {
        'ticker': 'SPY',
        'type': spread_type,
        'entry_date': entry_date,
        'expiration': expiration,
        'short_strike': short_strike,
        'long_strike': long_strike,
        'credit': credit,
        'contracts': contracts,
        'max_loss': max_loss,
        'profit_target': credit * 0.5,
        'stop_loss': credit * 2.5,
        'commission': commission,
        'status': 'open',
        'current_value': credit * contracts * 100,
        'option_type': option_type,
    }


def _make_mock_historical_data():
    """Create a mock HistoricalOptionsData for testing."""
    mock = MagicMock()
    mock.api_calls_made = 0
    return mock


# ---------------------------------------------------------------------------
# Tests for _estimate_spread_value (legacy heuristic mode)
# ---------------------------------------------------------------------------

class TestEstimateSpreadValue:

    def setup_method(self):
        self.bt = Backtester(_make_config())

    def test_otm_value_decays(self):
        """Far OTM spread should decay toward zero as DTE decreases."""
        position = _make_position(short_strike=450, credit=1.50)
        # Price well above short strike (OTM for bull put)
        value_high_dte = self.bt._estimate_spread_value(position, current_price=480, dte=30)
        value_low_dte = self.bt._estimate_spread_value(position, current_price=480, dte=5)
        assert value_high_dte > value_low_dte
        assert value_low_dte >= 0

    def test_itm_value_increases_with_depth(self):
        """Below short strike, value should approach spread width."""
        position = _make_position(short_strike=450, long_strike=445, credit=1.50)
        # Price below short strike (ITM for bull put)
        value = self.bt._estimate_spread_value(position, current_price=420, dte=20)
        assert value > 0
        spread_width = position['short_strike'] - position['long_strike']
        assert value <= spread_width

    def test_zero_dte(self):
        """At zero DTE, OTM spread should have near-zero value."""
        position = _make_position(short_strike=450, credit=1.50)
        value = self.bt._estimate_spread_value(position, current_price=480, dte=0)
        assert value >= 0
        assert value < position['credit'] * 0.5  # Should be decayed significantly

    def test_near_the_money(self):
        """Price near short strike should produce moderate value."""
        position = _make_position(short_strike=450, credit=1.50)
        value = self.bt._estimate_spread_value(position, current_price=451, dte=20)
        assert value >= 0

    def test_value_never_negative(self):
        """Spread value should never be negative."""
        position = _make_position(short_strike=450, credit=1.50)
        for price in [400, 450, 500]:
            for dte in [0, 10, 35]:
                value = self.bt._estimate_spread_value(position, price, dte)
                assert value >= 0

    def test_bear_call_otm_decays(self):
        """Bear call spread OTM should decay toward zero."""
        position = _make_position(
            short_strike=500, long_strike=505, credit=1.50,
            spread_type='bear_call_spread', option_type='C',
        )
        # Price well below short strike (OTM for bear call)
        value_high_dte = self.bt._estimate_spread_value(position, current_price=470, dte=30)
        value_low_dte = self.bt._estimate_spread_value(position, current_price=470, dte=5)
        assert value_high_dte > value_low_dte
        assert value_low_dte >= 0

    def test_bear_call_itm(self):
        """Bear call spread ITM should increase in value."""
        position = _make_position(
            short_strike=500, long_strike=505, credit=1.50,
            spread_type='bear_call_spread', option_type='C',
        )
        # Price above short strike (ITM for bear call)
        value = self.bt._estimate_spread_value(position, current_price=530, dte=20)
        assert value > 0


# ---------------------------------------------------------------------------
# Tests for _close_position (legacy heuristic mode)
# ---------------------------------------------------------------------------

class TestClosePosition:

    def setup_method(self):
        self.bt = Backtester(_make_config())
        self.bt.capital = 100000
        self.bt.trades = []

    def test_expiration_profit(self):
        """Expiration profit should earn full credit minus commissions."""
        pos = _make_position(credit=1.50, contracts=2, commission=1.30)
        self.bt._close_position(pos, datetime(2025, 2, 5), 460, 'expiration_profit')
        assert len(self.bt.trades) == 1
        expected_pnl = 1.50 * 2 * 100 - 1.30  # credit * contracts * 100 - commission
        assert self.bt.trades[0]['pnl'] == pytest.approx(expected_pnl, rel=1e-6)
        assert self.bt.capital == pytest.approx(100000 + expected_pnl, rel=1e-6)

    def test_expiration_loss(self):
        """Expiration loss should lose max_loss minus commissions."""
        pos = _make_position(credit=1.50, max_loss=3.50, contracts=1, commission=1.30)
        self.bt._close_position(pos, datetime(2025, 2, 5), 430, 'expiration_loss')
        assert len(self.bt.trades) == 1
        expected_pnl = -(3.50 * 1 * 100) - 1.30
        assert self.bt.trades[0]['pnl'] == pytest.approx(expected_pnl, rel=1e-6)

    def test_profit_target(self):
        """Profit target should earn profit_target amount minus commissions."""
        pos = _make_position(credit=1.50, contracts=1, commission=1.30)
        self.bt._close_position(pos, datetime(2025, 1, 20), 460, 'profit_target')
        expected_pnl = pos['profit_target'] * 1 * 100 - 1.30
        assert self.bt.trades[0]['pnl'] == pytest.approx(expected_pnl, rel=1e-6)

    def test_stop_loss(self):
        """Stop loss should lose stop_loss amount plus commissions."""
        pos = _make_position(credit=1.50, contracts=1, commission=1.30)
        self.bt._close_position(pos, datetime(2025, 1, 15), 440, 'stop_loss')
        expected_pnl = -(pos['stop_loss'] * 1 * 100) - 1.30
        assert self.bt.trades[0]['pnl'] == pytest.approx(expected_pnl, rel=1e-6)

    def test_other_reason(self):
        """Unknown exit reason should result in 0 PnL minus commissions."""
        pos = _make_position(credit=1.50, contracts=1, commission=1.30)
        self.bt._close_position(pos, datetime(2025, 2, 5), 450, 'backtest_end')
        expected_pnl = 0 - 1.30
        assert self.bt.trades[0]['pnl'] == pytest.approx(expected_pnl, rel=1e-6)

    def test_trade_record_fields(self):
        """Closed trade should contain all required fields."""
        pos = _make_position()
        self.bt._close_position(pos, datetime(2025, 2, 5), 460, 'expiration_profit')
        trade = self.bt.trades[0]
        required_fields = [
            'ticker', 'type', 'entry_date', 'exit_date', 'exit_reason',
            'short_strike', 'long_strike', 'credit', 'contracts', 'pnl', 'return_pct',
        ]
        for field in required_fields:
            assert field in trade, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Tests for _record_close (real-data mode)
# ---------------------------------------------------------------------------

class TestRecordClose:

    def setup_method(self):
        self.bt = Backtester(_make_config())
        self.bt.capital = 100000
        self.bt.trades = []

    def test_record_close_updates_capital(self):
        """_record_close should update capital by the PnL amount."""
        pos = _make_position(credit=2.00, max_loss=3.00, contracts=2)
        self.bt._record_close(pos, datetime(2025, 2, 5), 250.0, 'profit_target')
        assert self.bt.capital == pytest.approx(100250.0, rel=1e-6)
        assert len(self.bt.trades) == 1
        assert self.bt.trades[0]['pnl'] == 250.0

    def test_record_close_loss(self):
        """Negative PnL should decrease capital."""
        pos = _make_position(credit=2.00, max_loss=3.00, contracts=1)
        self.bt._record_close(pos, datetime(2025, 2, 5), -150.0, 'stop_loss')
        assert self.bt.capital == pytest.approx(99850.0, rel=1e-6)

    def test_record_close_return_pct(self):
        """Return percentage should be based on max risk."""
        pos = _make_position(credit=2.00, max_loss=3.00, contracts=2)
        # max_risk = 3.00 * 2 * 100 = 600
        self.bt._record_close(pos, datetime(2025, 2, 5), 300.0, 'profit_target')
        assert self.bt.trades[0]['return_pct'] == pytest.approx(50.0, rel=1e-6)

    def test_record_close_fields(self):
        """Trade record should have all required fields."""
        pos = _make_position()
        self.bt._record_close(pos, datetime(2025, 2, 5), 100.0, 'expiration_profit')
        trade = self.bt.trades[0]
        required_fields = [
            'ticker', 'type', 'entry_date', 'exit_date', 'exit_reason',
            'short_strike', 'long_strike', 'credit', 'contracts', 'pnl', 'return_pct',
        ]
        for field in required_fields:
            assert field in trade, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Tests for real pricing with mocked HistoricalOptionsData
# ---------------------------------------------------------------------------

class TestRealPricing:

    def setup_method(self):
        self.mock_hd = _make_mock_historical_data()
        self.bt = Backtester(_make_config(), historical_data=self.mock_hd)
        self.bt.capital = 100000
        self.bt.trades = []

    def test_real_data_mode_enabled(self):
        """Backtester should be in real data mode when historical_data provided."""
        assert self.bt._use_real_data is True

    def test_heuristic_mode_when_none(self):
        """Backtester should be in heuristic mode when no historical_data."""
        bt = Backtester(_make_config())
        assert bt._use_real_data is False

    def test_find_real_spread_uses_historical_data(self):
        """_find_real_spread should call get_available_strikes and get_spread_prices."""
        self.mock_hd.get_available_strikes.return_value = [440, 445, 450, 455, 460]
        self.mock_hd.get_spread_prices.return_value = {
            'short_close': 2.50,
            'long_close': 0.80,
            'spread_value': 1.70,
        }

        result = self.bt._find_real_spread(
            'SPY', datetime(2025, 1, 6), '2025-01-06', 480.0,
            datetime(2025, 2, 10), 5.0, option_type='P',
        )

        assert result is not None
        assert result['type'] == 'bull_put_spread'
        assert result['credit'] == pytest.approx(1.70 - 0.05, rel=1e-6)  # minus slippage
        self.mock_hd.get_available_strikes.assert_called_once()
        self.mock_hd.get_spread_prices.assert_called()

    def test_find_real_spread_skips_low_credit(self):
        """Should skip spreads with credit below 20% of spread width."""
        self.mock_hd.get_available_strikes.return_value = [440, 445, 450]
        self.mock_hd.get_spread_prices.return_value = {
            'short_close': 0.50,
            'long_close': 0.20,
            'spread_value': 0.30,  # 6% of $5 width — below 20% minimum
        }

        result = self.bt._find_real_spread(
            'SPY', datetime(2025, 1, 6), '2025-01-06', 480.0,
            datetime(2025, 2, 10), 5.0, option_type='P',
        )

        assert result is None

    def test_find_real_spread_tries_adjacent_strikes(self):
        """Should try adjacent strikes when primary has no data."""
        self.mock_hd.get_available_strikes.return_value = [440, 445, 450, 455, 460]
        # First call returns None, subsequent call returns data
        self.mock_hd.get_spread_prices.side_effect = [
            None,  # Primary strike
            {'short_close': 2.00, 'long_close': 0.50, 'spread_value': 1.50},  # +1 offset
        ]

        result = self.bt._find_real_spread(
            'SPY', datetime(2025, 1, 6), '2025-01-06', 480.0,
            datetime(2025, 2, 10), 5.0, option_type='P',
        )

        assert result is not None

    def test_find_real_bear_call(self):
        """Should find bear call spreads correctly."""
        self.mock_hd.get_available_strikes.return_value = [500, 505, 510, 515, 520]
        self.mock_hd.get_spread_prices.return_value = {
            'short_close': 2.00,
            'long_close': 0.60,
            'spread_value': 1.40,
        }

        result = self.bt._find_real_spread(
            'SPY', datetime(2025, 1, 6), '2025-01-06', 480.0,
            datetime(2025, 2, 10), 5.0, option_type='C',
        )

        assert result is not None
        assert result['type'] == 'bear_call_spread'
        assert result['short_strike'] == 505  # closest >= 504 (480*1.05)
        assert result['long_strike'] == 510

    def test_manage_positions_real_data_profit_target(self):
        """In real-data mode, should close at profit target using real spread value."""
        pos = _make_position(credit=2.00, max_loss=3.00, contracts=1, commission=1.30)
        pos['option_type'] = 'P'

        # Spread value dropped enough for profit target (credit - value >= profit_target)
        # profit_target = 2.00 * 0.5 = 1.00, so spread_value must be <= 1.00
        self.mock_hd.get_spread_prices.return_value = {
            'short_close': 0.50,
            'long_close': 0.10,
            'spread_value': 0.40,
        }

        remaining = self.bt._manage_positions([pos], datetime(2025, 1, 20), 460.0, 'SPY')

        assert len(remaining) == 0
        assert len(self.bt.trades) == 1
        assert self.bt.trades[0]['exit_reason'] == 'profit_target'
        # PnL = (2.00 - 0.40) * 1 * 100 - 1.30 = 158.70
        assert self.bt.trades[0]['pnl'] == pytest.approx(158.70, rel=1e-4)

    def test_manage_positions_real_data_stop_loss(self):
        """In real-data mode, should close at stop loss."""
        pos = _make_position(credit=1.00, max_loss=4.00, contracts=1, commission=1.30)
        pos['option_type'] = 'P'

        # stop_loss = 1.00 * 2.5 = 2.50
        # loss = spread_value - credit = 4.00 - 1.00 = 3.00 >= 2.50
        self.mock_hd.get_spread_prices.return_value = {
            'short_close': 4.50,
            'long_close': 0.50,
            'spread_value': 4.00,
        }

        remaining = self.bt._manage_positions([pos], datetime(2025, 1, 20), 440.0, 'SPY')

        assert len(remaining) == 0
        assert self.bt.trades[0]['exit_reason'] == 'stop_loss'
        # PnL = (1.00 - 4.00) * 1 * 100 - 1.30 = -301.30
        assert self.bt.trades[0]['pnl'] == pytest.approx(-301.30, rel=1e-4)

    def test_manage_positions_real_data_no_data_keeps_position(self):
        """If no price data available, should keep position open."""
        pos = _make_position(credit=2.00, max_loss=3.00, contracts=1, commission=1.30)
        pos['option_type'] = 'P'

        self.mock_hd.get_spread_prices.return_value = None

        remaining = self.bt._manage_positions([pos], datetime(2025, 1, 20), 460.0, 'SPY')

        assert len(remaining) == 1
        assert len(self.bt.trades) == 0


# ---------------------------------------------------------------------------
# Tests for expiration with real data
# ---------------------------------------------------------------------------

class TestExpirationReal:

    def setup_method(self):
        self.mock_hd = _make_mock_historical_data()
        self.bt = Backtester(_make_config(), historical_data=self.mock_hd)
        self.bt.capital = 100000
        self.bt.trades = []

    def test_expiration_worthless(self):
        """Spread expiring worthless should give max profit."""
        pos = _make_position(credit=1.50, max_loss=3.50, contracts=2, commission=1.30)
        pos['option_type'] = 'P'

        self.mock_hd.get_spread_prices.return_value = {
            'short_close': 0.02,
            'long_close': 0.01,
            'spread_value': 0.01,  # < 0.05 threshold
        }

        self.bt._close_at_expiration_real(pos, datetime(2025, 2, 5))

        assert len(self.bt.trades) == 1
        assert self.bt.trades[0]['exit_reason'] == 'expiration_profit'
        # Full credit: 1.50 * 2 * 100 - 1.30 = 298.70
        assert self.bt.trades[0]['pnl'] == pytest.approx(298.70, rel=1e-4)

    def test_expiration_with_value(self):
        """Spread expiring with value should compute real P&L."""
        pos = _make_position(credit=1.50, max_loss=3.50, contracts=1, commission=1.30)
        pos['option_type'] = 'P'

        self.mock_hd.get_spread_prices.return_value = {
            'short_close': 3.00,
            'long_close': 0.50,
            'spread_value': 2.50,  # > 0.05
        }

        self.bt._close_at_expiration_real(pos, datetime(2025, 2, 5))

        assert len(self.bt.trades) == 1
        assert self.bt.trades[0]['exit_reason'] == 'expiration_loss'
        # PnL = (1.50 - 2.50) * 1 * 100 - 1.30 = -101.30
        assert self.bt.trades[0]['pnl'] == pytest.approx(-101.30, rel=1e-4)

    def test_expiration_no_data_assumes_worthless(self):
        """If no expiration data, assume expired worthless."""
        pos = _make_position(credit=1.50, max_loss=3.50, contracts=1, commission=1.30)
        pos['option_type'] = 'P'

        self.mock_hd.get_spread_prices.return_value = None

        self.bt._close_at_expiration_real(pos, datetime(2025, 2, 5))

        assert self.bt.trades[0]['exit_reason'] == 'expiration_profit'


# ---------------------------------------------------------------------------
# Tests for _calculate_results
# ---------------------------------------------------------------------------

class TestCalculateResults:

    def setup_method(self):
        self.bt = Backtester(_make_config())
        self.bt.capital = 100000
        self.bt.equity_curve = [(datetime(2025, 1, 1), 100000)]

    def test_empty_trades(self):
        """No trades should return minimal results."""
        self.bt.trades = []
        results = self.bt._calculate_results()
        assert results['total_trades'] == 0
        assert results['win_rate'] == 0
        assert results['total_pnl'] == 0
        assert results['bull_put_trades'] == 0
        assert results['bear_call_trades'] == 0

    def test_mixed_trades(self):
        """Mix of winners and losers should produce correct stats."""
        self.bt.trades = [
            {'pnl': 200, 'return_pct': 10, 'type': 'bull_put_spread'},
            {'pnl': -100, 'return_pct': -5, 'type': 'bull_put_spread'},
            {'pnl': 150, 'return_pct': 8, 'type': 'bear_call_spread'},
        ]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 8), 100200),
            (datetime(2025, 1, 15), 100100),
            (datetime(2025, 1, 22), 100250),
        ]

        results = self.bt._calculate_results()
        assert results['total_trades'] == 3
        assert results['winning_trades'] == 2
        assert results['losing_trades'] == 1
        assert results['win_rate'] == pytest.approx(66.67, abs=0.01)
        assert results['total_pnl'] == 250
        assert results['bull_put_trades'] == 2
        assert results['bear_call_trades'] == 1
        assert results['bear_call_win_rate'] == 100.0

    def test_sharpe_ratio(self):
        """Sharpe ratio should be computed from equity curve returns."""
        self.bt.trades = [{'pnl': 100, 'return_pct': 5, 'type': 'bull_put_spread'}]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 2), 100100),
            (datetime(2025, 1, 3), 100200),
            (datetime(2025, 1, 6), 100300),
        ]
        results = self.bt._calculate_results()
        assert 'sharpe_ratio' in results
        assert results['sharpe_ratio'] >= 0

    def test_max_drawdown(self):
        """Max drawdown should capture the peak-to-trough decline."""
        self.bt.trades = [{'pnl': -500, 'return_pct': -10, 'type': 'bull_put_spread'}]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 2), 101000),
            (datetime(2025, 1, 3), 99000),
            (datetime(2025, 1, 6), 99500),
        ]
        results = self.bt._calculate_results()
        assert results['max_drawdown'] < 0

    def test_profit_factor_zero_losers(self):
        """All winners with zero losers should yield infinite profit factor."""
        self.bt.trades = [
            {'pnl': 200, 'return_pct': 10, 'type': 'bull_put_spread'},
            {'pnl': 300, 'return_pct': 15, 'type': 'bull_put_spread'},
        ]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 2), 100200),
            (datetime(2025, 1, 3), 100500),
        ]
        results = self.bt._calculate_results()
        assert results['profit_factor'] == float('inf')

    def test_all_losers(self):
        """All losing trades should produce 0% win rate."""
        self.bt.trades = [
            {'pnl': -100, 'return_pct': -5, 'type': 'bull_put_spread'},
            {'pnl': -200, 'return_pct': -10, 'type': 'bear_call_spread'},
        ]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 2), 99900),
            (datetime(2025, 1, 3), 99700),
        ]
        results = self.bt._calculate_results()
        assert results['win_rate'] == 0
        assert results['total_pnl'] == -300
        assert results['avg_win'] == 0

    def test_results_contain_equity_curve(self):
        """Results should include the equity curve data."""
        self.bt.trades = [{'pnl': 100, 'return_pct': 5, 'type': 'bull_put_spread'}]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 2), 100100),
        ]
        results = self.bt._calculate_results()
        assert 'equity_curve' in results
        assert 'trades' in results
        assert results['starting_capital'] == 100000

    def test_results_contain_strategy_breakdown(self):
        """Results should include per-strategy win rates."""
        self.bt.trades = [
            {'pnl': 200, 'return_pct': 10, 'type': 'bull_put_spread'},
            {'pnl': -50, 'return_pct': -2, 'type': 'bear_call_spread'},
        ]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 2), 100200),
            (datetime(2025, 1, 3), 100150),
        ]
        results = self.bt._calculate_results()
        assert results['bull_put_win_rate'] == 100.0
        assert results['bear_call_win_rate'] == 0.0


# ---------------------------------------------------------------------------
# Tests for HistoricalOptionsData (integration with mocked Polygon)
# ---------------------------------------------------------------------------

class TestHistoricalDataIntegration:

    def test_build_occ_symbol_put(self):
        """Should build correct OCC symbol for puts."""
        from backtest.historical_data import HistoricalOptionsData
        sym = HistoricalOptionsData.build_occ_symbol(
            'SPY', datetime(2025, 3, 21), 450.0, 'P',
        )
        assert sym == 'O:SPY250321P00450000'

    def test_build_occ_symbol_call(self):
        """Should build correct OCC symbol for calls."""
        from backtest.historical_data import HistoricalOptionsData
        sym = HistoricalOptionsData.build_occ_symbol(
            'SPY', datetime(2025, 3, 21), 450.0, 'C',
        )
        assert sym == 'O:SPY250321C00450000'

    def test_build_occ_symbol_fractional_strike(self):
        """Should handle fractional strikes correctly."""
        from backtest.historical_data import HistoricalOptionsData
        sym = HistoricalOptionsData.build_occ_symbol(
            'QQQ', datetime(2025, 6, 20), 375.50, 'put',
        )
        assert sym == 'O:QQQ250620P00375500'

    def test_build_occ_symbol_high_strike(self):
        """Should handle high strike prices."""
        from backtest.historical_data import HistoricalOptionsData
        sym = HistoricalOptionsData.build_occ_symbol(
            'SPY', datetime(2025, 12, 19), 600.0, 'C',
        )
        assert sym == 'O:SPY251219C00600000'

    @patch('backtest.historical_data.requests.Session')
    def test_cache_db_creation(self, mock_session_cls, tmp_path):
        """Cache DB should be created with correct tables."""
        from backtest.historical_data import HistoricalOptionsData
        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))

        # Verify tables exist
        cur = hd._conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert 'option_daily' in tables
        assert 'option_contracts' in tables
        hd.close()

    @patch('backtest.historical_data.requests.Session')
    def test_get_contract_price_cache_hit(self, mock_session_cls, tmp_path):
        """Should return cached price without API call."""
        from backtest.historical_data import HistoricalOptionsData
        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))

        # Insert directly into cache
        hd._conn.execute(
            "INSERT INTO option_daily (contract_symbol, date, close) VALUES (?, ?, ?)",
            ('O:SPY250321P00450000', '2025-01-06', 2.50),
        )
        hd._conn.commit()

        price = hd.get_contract_price('O:SPY250321P00450000', '2025-01-06')
        assert price == 2.50
        assert hd.api_calls_made == 0
        hd.close()

    @patch('backtest.historical_data.requests.Session')
    def test_clear_cache(self, mock_session_cls, tmp_path):
        """clear_cache should empty both tables."""
        from backtest.historical_data import HistoricalOptionsData
        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))

        hd._conn.execute(
            "INSERT INTO option_daily (contract_symbol, date, close) VALUES (?, ?, ?)",
            ('O:SPY250321P00450000', '2025-01-06', 2.50),
        )
        hd._conn.commit()

        hd.clear_cache()

        cur = hd._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM option_daily")
        assert cur.fetchone()[0] == 0
        hd.close()


# ---------------------------------------------------------------------------
# Tests for bear call backtest
# ---------------------------------------------------------------------------

class TestBearCallBacktest:

    def setup_method(self):
        self.bt = Backtester(_make_config())
        self.bt.capital = 100000
        self.bt.trades = []

    def test_bear_call_heuristic_position(self):
        """Heuristic mode should create bear call positions."""
        pos = self.bt._find_heuristic_spread(
            'SPY', datetime(2025, 1, 6), 480.0,
            datetime(2025, 2, 10), 5.0, 'bear_call_spread',
        )

        assert pos is not None
        assert pos['type'] == 'bear_call_spread'
        assert pos['option_type'] == 'C'
        assert pos['short_strike'] > 480.0  # OTM call
        assert pos['long_strike'] == pos['short_strike'] + 5.0

    def test_bear_call_requires_bearish_trend(self):
        """Bear call should only trigger when price < MA20."""
        import pandas as pd
        dates = pd.date_range('2024-11-01', periods=50, freq='B')
        # Downtrending prices
        prices = [500 - i * 0.5 for i in range(50)]
        price_data = pd.DataFrame({'Close': prices}, index=dates)

        result = self.bt._find_bear_call_opportunity(
            'SPY', dates[-1].to_pydatetime(), prices[-1], price_data,
        )
        # Should find opportunity if price < MA20
        # (final price ~ 475.5, MA20 of last 20 is higher)
        # This should not be None since trend is bearish
        assert result is not None or prices[-1] >= price_data['Close'].rolling(20).mean().iloc[-1]

    def test_bear_call_close_position(self):
        """Bear call close should work same as bull put in heuristic mode."""
        pos = _make_position(
            credit=1.50, max_loss=3.50, contracts=1, commission=1.30,
            spread_type='bear_call_spread', option_type='C',
            short_strike=500, long_strike=505,
        )
        self.bt._close_position(pos, datetime(2025, 2, 5), 490, 'expiration_profit')
        assert len(self.bt.trades) == 1
        expected_pnl = 1.50 * 1 * 100 - 1.30
        assert self.bt.trades[0]['pnl'] == pytest.approx(expected_pnl, rel=1e-6)
        assert self.bt.trades[0]['type'] == 'bear_call_spread'
