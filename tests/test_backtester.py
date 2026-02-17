"""Tests for the Backtester class."""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

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
):
    """Return a minimal position dict for testing."""
    entry_date = entry_date or datetime(2025, 1, 1)
    expiration = expiration or datetime(2025, 2, 5)
    return {
        'ticker': 'SPY',
        'type': 'bull_put_spread',
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
    }


# ---------------------------------------------------------------------------
# Tests for _estimate_spread_value
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


# ---------------------------------------------------------------------------
# Tests for _close_position
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

    def test_mixed_trades(self):
        """Mix of winners and losers should produce correct stats."""
        self.bt.trades = [
            {'pnl': 200, 'return_pct': 10},
            {'pnl': -100, 'return_pct': -5},
            {'pnl': 150, 'return_pct': 8},
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

    def test_sharpe_ratio(self):
        """Sharpe ratio should be computed from equity curve returns."""
        self.bt.trades = [{'pnl': 100, 'return_pct': 5}]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 2), 100100),
            (datetime(2025, 1, 3), 100200),
            (datetime(2025, 1, 6), 100300),
        ]
        results = self.bt._calculate_results()
        assert 'sharpe_ratio' in results
        # With consistently positive returns, Sharpe should be positive
        assert results['sharpe_ratio'] >= 0

    def test_max_drawdown(self):
        """Max drawdown should capture the peak-to-trough decline."""
        self.bt.trades = [{'pnl': -500, 'return_pct': -10}]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 2), 101000),
            (datetime(2025, 1, 3), 99000),
            (datetime(2025, 1, 6), 99500),
        ]
        results = self.bt._calculate_results()
        assert results['max_drawdown'] < 0  # Drawdown is negative

    def test_profit_factor_zero_losers(self):
        """All winners with zero losers should yield infinite profit factor."""
        self.bt.trades = [
            {'pnl': 200, 'return_pct': 10},
            {'pnl': 300, 'return_pct': 15},
        ]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 2), 100200),
            (datetime(2025, 1, 3), 100500),
        ]
        results = self.bt._calculate_results()
        # No losers means infinite profit factor
        assert results['profit_factor'] == float('inf')

    def test_all_losers(self):
        """All losing trades should produce 0% win rate."""
        self.bt.trades = [
            {'pnl': -100, 'return_pct': -5},
            {'pnl': -200, 'return_pct': -10},
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
        self.bt.trades = [{'pnl': 100, 'return_pct': 5}]
        self.bt.equity_curve = [
            (datetime(2025, 1, 1), 100000),
            (datetime(2025, 1, 2), 100100),
        ]
        results = self.bt._calculate_results()
        assert 'equity_curve' in results
        assert 'trades' in results
        assert results['starting_capital'] == 100000
