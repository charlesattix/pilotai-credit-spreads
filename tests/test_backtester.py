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


# ---------------------------------------------------------------------------
# Tests for intraday backtesting (14 scan times per day)
# ---------------------------------------------------------------------------

class TestNearestFridayExpiration:
    """Tests for the Friday-snapping expiration helper."""

    def test_monday_target_snaps_to_prior_friday(self):
        """date + 35 days = Monday → should return the preceding Friday."""
        from backtest.backtester import _nearest_friday_expiration
        # Jan 6 (Mon) + 35 = Feb 10 (Mon) → nearest Friday = Feb 7
        result = _nearest_friday_expiration(datetime(2025, 1, 6))
        assert result.weekday() == 4  # Friday
        assert result == datetime(2025, 2, 7)

    def test_friday_target_is_unchanged(self):
        """date + 35 days already a Friday → return it as-is."""
        from backtest.backtester import _nearest_friday_expiration
        # Jan 10 (Fri) + 35 = Feb 14 (Fri)
        result = _nearest_friday_expiration(datetime(2025, 1, 10))
        assert result.weekday() == 4
        assert result == datetime(2025, 2, 14)

    def test_thursday_target_snaps_forward(self):
        """date + 35 days = Thursday → forward to next Friday is closer."""
        from backtest.backtester import _nearest_friday_expiration
        # Jan 9 (Thu) + 35 = Feb 13 (Thu) → Friday after = Feb 14
        result = _nearest_friday_expiration(datetime(2025, 1, 9))
        assert result.weekday() == 4
        assert result == datetime(2025, 2, 14)

    def test_wednesday_target_snaps_to_closer_friday(self):
        """date + 35 days = Wednesday → Friday before (2 days) is closer."""
        from backtest.backtester import _nearest_friday_expiration
        # Jan 8 (Wed) + 35 = Feb 12 (Wed) → Friday before = Feb 7 (5 days earlier)
        # Friday after = Feb 14 (2 days later) → should pick Feb 14
        result = _nearest_friday_expiration(datetime(2025, 1, 8))
        assert result.weekday() == 4
        assert result == datetime(2025, 2, 14)

    def test_result_satisfies_min_dte(self):
        """Result must always be at least min_dte days from entry date."""
        from backtest.backtester import _nearest_friday_expiration
        entry = datetime(2025, 1, 6)
        result = _nearest_friday_expiration(entry, target_dte=35, min_dte=25)
        assert (result - entry).days >= 25


class TestIntradayBacktest:
    """Tests for the intraday simulation rewrite (P0 #1)."""

    def setup_method(self):
        self.mock_hd = _make_mock_historical_data()
        self.bt = Backtester(_make_config(), historical_data=self.mock_hd)
        self.bt.capital = 100000
        self.bt.trades = []

    def test_find_real_spread_uses_intraday_when_scan_time_given(self):
        """_find_real_spread should call get_intraday_spread_prices when scan_hour/minute set."""
        self.mock_hd.get_available_strikes.return_value = [440, 445, 450, 455, 460]
        self.mock_hd.get_intraday_spread_prices.return_value = {
            'short_close': 2.50,
            'long_close': 0.80,
            'spread_value': 1.70,
            'slippage': 0.12,
        }

        result = self.bt._find_real_spread(
            'SPY', datetime(2025, 1, 6), '2025-01-06', 480.0,
            datetime(2025, 2, 10), 5.0, option_type='P',
            scan_hour=9, scan_minute=45,
        )

        assert result is not None
        self.mock_hd.get_intraday_spread_prices.assert_called_once()
        # Daily fallback should NOT be called
        self.mock_hd.get_spread_prices.assert_not_called()

    def test_find_real_spread_slippage_from_intraday_bar(self):
        """Credit should be reduced by the bar-modeled slippage, not flat 0.05."""
        self.mock_hd.get_available_strikes.return_value = [440, 445, 450]
        intraday_slippage = 0.18  # wider than flat 0.05
        self.mock_hd.get_intraday_spread_prices.return_value = {
            'short_close': 2.50,
            'long_close': 0.80,
            'spread_value': 1.70,
            'slippage': intraday_slippage,
        }

        result = self.bt._find_real_spread(
            'SPY', datetime(2025, 1, 6), '2025-01-06', 480.0,
            datetime(2025, 2, 10), 5.0, option_type='P',
            scan_hour=10, scan_minute=0,
        )

        assert result is not None
        assert result['credit'] == pytest.approx(1.70 - intraday_slippage, rel=1e-6)
        assert result['slippage_applied'] == pytest.approx(intraday_slippage, rel=1e-6)

    def test_find_real_spread_falls_back_to_daily_when_no_scan_time(self):
        """Without scan_hour/minute, should use daily get_spread_prices."""
        self.mock_hd.get_available_strikes.return_value = [440, 445, 450]
        self.mock_hd.get_spread_prices.return_value = {
            'short_close': 2.00,
            'long_close': 0.60,
            'spread_value': 1.40,
        }

        result = self.bt._find_real_spread(
            'SPY', datetime(2025, 1, 6), '2025-01-06', 480.0,
            datetime(2025, 2, 10), 5.0, option_type='P',
        )

        assert result is not None
        self.mock_hd.get_spread_prices.assert_called_once()
        self.mock_hd.get_intraday_spread_prices.assert_not_called()

    def test_find_real_spread_records_entry_scan_time(self):
        """Position should record the intraday scan time used for entry."""
        self.mock_hd.get_available_strikes.return_value = [440, 445, 450]
        self.mock_hd.get_intraday_spread_prices.return_value = {
            'short_close': 2.00, 'long_close': 0.50,
            'spread_value': 1.50, 'slippage': 0.08,
        }

        result = self.bt._find_real_spread(
            'SPY', datetime(2025, 1, 6), '2025-01-06', 480.0,
            datetime(2025, 2, 10), 5.0, option_type='P',
            scan_hour=11, scan_minute=30,
        )

        assert result is not None
        assert result['entry_scan_time'] == '11:30'

    def test_intraday_scan_times_count_is_14(self):
        """Live schedule must define exactly 14 scan times to match backtester."""
        from shared.scheduler import SCAN_TIMES
        assert len(SCAN_TIMES) == 14

    def test_find_real_spread_skips_intraday_for_pre_open_scan(self):
        """9:15 scan (pre-open) should fall back to daily pricing, not intraday."""
        self.mock_hd.get_available_strikes.return_value = [440, 445, 450]
        self.mock_hd.get_spread_prices.return_value = {
            'short_close': 2.00, 'long_close': 0.60, 'spread_value': 1.40,
        }

        result = self.bt._find_real_spread(
            'SPY', datetime(2025, 1, 6), '2025-01-06', 480.0,
            datetime(2025, 2, 7), 5.0, option_type='P',
            scan_hour=9, scan_minute=15,  # pre-open
        )

        assert result is not None
        self.mock_hd.get_spread_prices.assert_called_once()
        self.mock_hd.get_intraday_spread_prices.assert_not_called()

    def test_backtester_attempts_all_scan_times_on_trading_day(self):
        """In real-data mode, backtester should attempt all 14 scan times per day."""
        from shared.scheduler import SCAN_TIMES
        import pandas as pd

        # Need >= 20 rows so the MA20 check passes on the target date.
        # Uptrending so price > MA20 (triggers bull put scans).
        dates = pd.date_range('2024-11-18', periods=35, freq='B')
        prices = [450.0 + i * 2 for i in range(len(dates))]  # steadily rising
        price_data = pd.DataFrame(
            {'Close': prices, 'Open': prices, 'High': prices, 'Low': prices,
             'Volume': [1_000_000] * len(dates)},
            index=dates,
        )

        # No strikes available — all scans return None (no position opened)
        self.mock_hd.get_available_strikes.return_value = []

        start = datetime(2025, 1, 6)
        end = datetime(2025, 1, 6)

        # The target date must be in the price_data index
        target_ts = pd.Timestamp('2025-01-06')
        if target_ts not in set(price_data.index):
            extra_dates = pd.date_range('2025-01-06', periods=1, freq='B')
            extra_prices = [prices[-1] + 2]
            extra_df = pd.DataFrame(
                {'Close': extra_prices, 'Open': extra_prices, 'High': extra_prices,
                 'Low': extra_prices, 'Volume': [1_000_000]},
                index=extra_dates,
            )
            price_data = pd.concat([price_data, extra_df])

        with __import__('unittest.mock', fromlist=['patch']).patch.object(
            self.bt, '_get_historical_data', return_value=price_data
        ):
            self.bt.run_backtest('SPY', start, end)

        # Each of the 14 scan times should trigger at least a bull put attempt
        # (price is above MA20 on the target day)
        assert self.mock_hd.get_available_strikes.call_count >= 14


# ---------------------------------------------------------------------------
# Tests for HistoricalOptionsData intraday methods
# ---------------------------------------------------------------------------

class TestIntradayHistoricalData:
    """Tests for get_intraday_bar, _fetch_and_cache_intraday, get_intraday_spread_prices."""

    @patch('backtest.historical_data.requests.Session')
    def test_get_intraday_bar_cache_hit(self, mock_session_cls, tmp_path):
        """Returns bar from cache without API call."""
        from backtest.historical_data import HistoricalOptionsData
        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))

        hd._conn.execute(
            "INSERT INTO option_intraday (contract_symbol, date, bar_time, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ('O:SPY250321P00450000', '2025-01-06', '09:45', 2.40, 2.60, 2.20, 2.50, 100),
        )
        hd._conn.commit()

        bar = hd.get_intraday_bar('O:SPY250321P00450000', '2025-01-06', 9, 45)
        assert bar is not None
        assert bar['close'] == 2.50
        assert bar['high'] == 2.60
        assert hd.api_calls_made == 0
        hd.close()

    @patch('backtest.historical_data.requests.Session')
    def test_get_intraday_bar_returns_closest_earlier_bar(self, mock_session_cls, tmp_path):
        """Falls back to closest earlier bar when exact time not present."""
        from backtest.historical_data import HistoricalOptionsData
        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))

        # Insert bars at 09:30 and 09:35 but not 09:45
        for bt, close in [('09:30', 2.30), ('09:35', 2.35)]:
            hd._conn.execute(
                "INSERT INTO option_intraday (contract_symbol, date, bar_time, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ('O:SPY250321P00450000', '2025-01-06', bt, close, close + 0.1, close - 0.1, close, 50),
            )
        hd._conn.commit()

        bar = hd.get_intraday_bar('O:SPY250321P00450000', '2025-01-06', 9, 45)
        assert bar is not None
        assert bar['close'] == 2.35  # Most recent bar before 09:45
        hd.close()

    @patch('backtest.historical_data.requests.Session')
    def test_get_intraday_bar_sentinel_returns_none(self, mock_session_cls, tmp_path):
        """When sentinel FETCHED row exists, returns None without new API call."""
        from backtest.historical_data import HistoricalOptionsData
        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))

        hd._conn.execute(
            "INSERT INTO option_intraday (contract_symbol, date, bar_time) VALUES (?, ?, 'FETCHED')",
            ('O:SPY250321P00450000', '2025-01-06'),
        )
        hd._conn.commit()

        bar = hd.get_intraday_bar('O:SPY250321P00450000', '2025-01-06', 9, 15)
        assert bar is None
        assert hd.api_calls_made == 0
        hd.close()

    @patch('backtest.historical_data.requests.Session')
    def test_fetch_and_cache_intraday_stores_bars(self, mock_session_cls, tmp_path):
        """Intraday bars are converted from UTC ms timestamps to ET and cached."""
        import pytz
        from datetime import timezone as tz
        from backtest.historical_data import HistoricalOptionsData

        # 2025-01-06 09:45 ET = 14:45 UTC = 1736171100000 ms
        ts_ms = int(datetime(2025, 1, 6, 14, 45, 0, tzinfo=tz.utc).timestamp() * 1000)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'results': [
                {'t': ts_ms, 'o': 2.40, 'h': 2.60, 'l': 2.20, 'c': 2.50, 'v': 100},
            ]
        }
        mock_session_cls.return_value.get.return_value = mock_resp

        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))
        hd._fetch_and_cache_intraday('O:SPY250321P00450000', '2025-01-06')

        cur = hd._conn.cursor()
        cur.execute(
            "SELECT bar_time, close FROM option_intraday "
            "WHERE contract_symbol = ? AND date = ?",
            ('O:SPY250321P00450000', '2025-01-06'),
        )
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == '09:45'
        assert rows[0][1] == 2.50
        hd.close()

    @patch('backtest.historical_data.requests.Session')
    def test_fetch_and_cache_intraday_sentinel_on_no_data(self, mock_session_cls, tmp_path):
        """When API returns empty results, sentinel row inserted."""
        from backtest.historical_data import HistoricalOptionsData

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'results': []}
        mock_session_cls.return_value.get.return_value = mock_resp

        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))
        hd._fetch_and_cache_intraday('O:SPY250321P00450000', '2025-01-06')

        cur = hd._conn.cursor()
        cur.execute(
            "SELECT bar_time FROM option_intraday "
            "WHERE contract_symbol = ? AND date = ?",
            ('O:SPY250321P00450000', '2025-01-06'),
        )
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 'FETCHED'
        hd.close()

    @patch('backtest.historical_data.requests.Session')
    def test_get_intraday_spread_prices_computes_slippage(self, mock_session_cls, tmp_path):
        """Slippage equals sum of half-spread (high-low/2) for both legs."""
        from backtest.historical_data import HistoricalOptionsData

        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))

        sym_short = 'O:SPY250321P00455000'
        sym_long = 'O:SPY250321P00450000'
        date_str = '2025-01-06'

        # Short leg: high=2.60, low=2.20 → half-spread = 0.20
        hd._conn.execute(
            "INSERT INTO option_intraday (contract_symbol, date, bar_time, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sym_short, date_str, '09:45', 2.40, 2.60, 2.20, 2.50, 100),
        )
        # Long leg: high=1.20, low=0.80 → half-spread = 0.20
        hd._conn.execute(
            "INSERT INTO option_intraday (contract_symbol, date, bar_time, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sym_long, date_str, '09:45', 0.90, 1.20, 0.80, 1.00, 80),
        )
        hd._conn.commit()

        result = hd.get_intraday_spread_prices(
            'SPY', datetime(2025, 3, 21), 455.0, 450.0, 'P',
            date_str, 9, 45,
        )

        assert result is not None
        assert result['spread_value'] == pytest.approx(1.50, rel=1e-6)   # 2.50 - 1.00
        assert result['slippage'] == pytest.approx(0.40, rel=1e-6)        # 0.20 + 0.20

        hd.close()

    @patch('backtest.historical_data.requests.Session')
    def test_get_intraday_spread_prices_returns_none_if_leg_missing(self, mock_session_cls, tmp_path):
        """Returns None when either leg has no intraday data."""
        from backtest.historical_data import HistoricalOptionsData

        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))

        # Only short leg cached — long leg will trigger fetch which returns nothing
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'results': []}
        mock_session_cls.return_value.get.return_value = mock_resp

        sym_short = 'O:SPY250321P00455000'
        hd._conn.execute(
            "INSERT INTO option_intraday (contract_symbol, date, bar_time, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sym_short, '2025-01-06', '09:45', 2.40, 2.60, 2.20, 2.50, 100),
        )
        hd._conn.commit()

        result = hd.get_intraday_spread_prices(
            'SPY', datetime(2025, 3, 21), 455.0, 450.0, 'P',
            '2025-01-06', 9, 45,
        )

        assert result is None
        hd.close()

    @patch('backtest.historical_data.requests.Session')
    def test_clear_cache_removes_intraday_table(self, mock_session_cls, tmp_path):
        """clear_cache should empty option_intraday table too."""
        from backtest.historical_data import HistoricalOptionsData

        hd = HistoricalOptionsData('test_key', cache_dir=str(tmp_path))
        hd._conn.execute(
            "INSERT INTO option_intraday (contract_symbol, date, bar_time, close) "
            "VALUES ('O:SPY250321P00450000', '2025-01-06', '09:45', 2.50)",
        )
        hd._conn.commit()

        hd.clear_cache()

        cur = hd._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM option_intraday")
        assert cur.fetchone()[0] == 0
        hd.close()
