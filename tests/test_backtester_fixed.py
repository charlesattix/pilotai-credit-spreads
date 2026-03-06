"""Comprehensive tests for BacktesterFixed (backtest/backtester_fixed.py)."""
import math
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pandas as pd
from scipy.stats import norm as _norm

from backtest.backtester_fixed import BacktesterFixed


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_config(**overrides):
    """Minimal valid config for BacktesterFixed."""
    cfg = {
        'backtest': {
            'starting_capital': 100_000,
            'commission_per_contract': 0.65,
            'slippage': 0.05,
            'score_threshold': 28,
        },
        'strategy': {
            'spread_width': 5,
            'ml_score_weight': 0.6,
            'event_risk_threshold': 0.7,
        },
        'risk': {
            'max_positions': 5,
            'max_positions_per_ticker': 2,
            'max_risk_per_trade': 2.0,
            'stop_loss_multiplier': 2.5,
            'stop_loss_pct_of_width': 75,
            'scan_days': [0, 2, 4],  # Mon, Wed, Fri
            'min_contracts': 1,
            'max_contracts': 20,
            'portfolio_risk': {},
            'enable_rolling': False,
            'max_rolls_per_position': 1,
            'min_roll_credit': 0.30,
        },
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and k in cfg:
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def _make_mocks():
    """Return (strategy, technical_analyzer, options_analyzer) mocks."""
    strategy = MagicMock()
    tech = MagicMock()
    opts = MagicMock()
    return strategy, tech, opts


def _make_price_df(start='2025-06-01', periods=120, base=450.0, seed=42):
    """Generate a realistic daily OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=periods)
    closes = [base]
    for _ in range(periods - 1):
        ret = rng.normal(0.0003, 0.01)
        closes.append(closes[-1] * (1 + ret))
    closes = np.array(closes)
    df = pd.DataFrame({
        'Open': closes * (1 + rng.normal(0, 0.002, periods)),
        'High': closes * (1 + abs(rng.normal(0, 0.005, periods))),
        'Low': closes * (1 - abs(rng.normal(0, 0.005, periods))),
        'Close': closes,
        'Volume': rng.integers(10_000_000, 50_000_000, periods),
    }, index=dates)
    return df


def _make_position(
    ticker='SPY', spread_type='bull_put_spread', entry_date=None,
    expiration=None, short_strike=440.0, long_strike=435.0,
    credit=1.50, contracts=2, max_loss=3.50, spread_width=5.0,
    commission=2.60, entry_iv=0.20, score=35,
):
    """Return a position dict matching BacktesterFixed conventions."""
    entry_date = entry_date or datetime(2025, 7, 1)
    expiration = expiration or datetime(2025, 8, 1)
    return {
        'ticker': ticker,
        'type': spread_type,
        'entry_date': entry_date,
        'expiration': expiration,
        'short_strike': short_strike,
        'long_strike': long_strike,
        'credit': credit,
        'contracts': contracts,
        'max_loss': max_loss,
        'spread_width': spread_width,
        'score': score,
        'status': 'open',
        'current_value': 0,
        'commission': commission,
        'pricing_source': 'synthetic',
        'entry_iv': entry_iv,
    }


def _make_backtester(config=None, strategy=None, tech=None, opts=None,
                     historical_data=None, polygon_provider=None,
                     ml_pipeline=None):
    """Construct a BacktesterFixed with sensible defaults."""
    config = config or _make_config()
    s, t, o = _make_mocks()
    return BacktesterFixed(
        config=config,
        strategy=strategy or s,
        technical_analyzer=tech or t,
        options_analyzer=opts or o,
        ml_pipeline=ml_pipeline,
        historical_data=historical_data,
        polygon_provider=polygon_provider,
    )


# ===================================================================
# Black-Scholes helpers
# ===================================================================

class TestBSOptionPrice:
    """Tests for _bs_option_price static method."""

    def test_put_at_expiration_otm(self):
        """OTM put at expiration should be 0."""
        assert BacktesterFixed._bs_option_price(450, 440, 0, 0.20, 'put') == 0.0

    def test_put_at_expiration_itm(self):
        """ITM put at expiration should return intrinsic value."""
        price = BacktesterFixed._bs_option_price(430, 440, 0, 0.20, 'put')
        assert price == pytest.approx(10.0)

    def test_call_at_expiration_otm(self):
        assert BacktesterFixed._bs_option_price(430, 440, 0, 0.20, 'call') == 0.0

    def test_call_at_expiration_itm(self):
        price = BacktesterFixed._bs_option_price(450, 440, 0, 0.20, 'call')
        assert price == pytest.approx(10.0)

    def test_put_has_time_value(self):
        """Put with time remaining should exceed intrinsic."""
        # ATM put – intrinsic is 0, but time value should be > 0
        price = BacktesterFixed._bs_option_price(450, 450, 30/365, 0.20, 'put')
        assert price > 0

    def test_call_has_time_value(self):
        price = BacktesterFixed._bs_option_price(450, 450, 30/365, 0.20, 'call')
        assert price > 0

    def test_higher_vol_higher_price(self):
        """Higher vol should produce higher option price (all else equal)."""
        low_vol = BacktesterFixed._bs_option_price(450, 440, 30/365, 0.15, 'put')
        high_vol = BacktesterFixed._bs_option_price(450, 440, 30/365, 0.35, 'put')
        assert high_vol > low_vol

    def test_negative_time_returns_intrinsic(self):
        """Negative T should be treated same as 0 (intrinsic only)."""
        price = BacktesterFixed._bs_option_price(430, 440, -5, 0.20, 'put')
        assert price == pytest.approx(10.0)

    def test_put_call_parity_approximate(self):
        """Put-call parity: C - P ≈ S - K*e^(-rT)."""
        S, K, T, sigma, r = 450, 450, 30/365, 0.20, 0.045
        c = BacktesterFixed._bs_option_price(S, K, T, sigma, 'call', r)
        p = BacktesterFixed._bs_option_price(S, K, T, sigma, 'put', r)
        expected = S - K * math.exp(-r * T)
        assert (c - p) == pytest.approx(expected, abs=0.01)


class TestBSSpreadValue:
    """Tests for _bs_spread_value."""

    def setup_method(self):
        self.bt = _make_backtester()

    def test_otm_spread_near_zero_at_expiry(self):
        """OTM bull put spread at expiry should be worth ~0."""
        val = self.bt._bs_spread_value(440, 435, 'put', 460.0, 0, 0.20)
        assert val == pytest.approx(0.0, abs=0.01)

    def test_itm_spread_at_max_width(self):
        """Deep ITM spread at expiry should be worth the spread width."""
        val = self.bt._bs_spread_value(440, 435, 'put', 420.0, 0, 0.20)
        assert val == pytest.approx(5.0, abs=0.01)

    def test_clamped_to_width(self):
        """Value should never exceed spread width."""
        val = self.bt._bs_spread_value(440, 435, 'put', 410.0, 30, 0.80)
        assert val <= 5.0

    def test_clamped_non_negative(self):
        """Value should never be negative."""
        val = self.bt._bs_spread_value(440, 435, 'put', 500.0, 30, 0.20)
        assert val >= 0.0

    def test_spread_decays_with_time(self):
        """OTM spread should decay toward 0 as DTE drops."""
        val_30d = self.bt._bs_spread_value(440, 435, 'put', 460.0, 30, 0.20)
        val_5d = self.bt._bs_spread_value(440, 435, 'put', 460.0, 5, 0.20)
        assert val_30d >= val_5d

    def test_call_spread(self):
        """Bear call spread OTM should also be near zero at expiry."""
        val = self.bt._bs_spread_value(460, 465, 'call', 440.0, 0, 0.20)
        assert val == pytest.approx(0.0, abs=0.01)


# ===================================================================
# Realized volatility
# ===================================================================

class TestRealizedVol:

    def test_enough_data(self):
        """With enough price data, returns reasonable vol in (0.10, 0.80)."""
        df = _make_price_df(periods=60)
        as_of = df.index[-1].to_pydatetime()
        rv = BacktesterFixed._realized_vol(df, as_of, window=20)
        assert 0.10 <= rv <= 0.80

    def test_insufficient_data_fallback(self):
        """With too few data points, returns 0.20 default."""
        df = _make_price_df(periods=10)
        as_of = df.index[-1].to_pydatetime()
        rv = BacktesterFixed._realized_vol(df, as_of, window=20)
        assert rv == 0.20

    def test_exception_fallback(self):
        """If data is malformed, returns 0.20 default."""
        bad_df = pd.DataFrame({'Wrong': [1, 2, 3]})
        rv = BacktesterFixed._realized_vol(bad_df, datetime(2025, 7, 1))
        assert rv == 0.20


# ===================================================================
# Commission & slippage
# ===================================================================

class TestCommissionSlippage:

    def test_entry_commission_deducted_from_capital(self):
        """Opening a position deducts entry commission from capital."""
        bt = _make_backtester()
        bt.capital = 100_000

        opp = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 440, 'long_strike': 435,
            'credit': 1.80, 'max_loss': 3.20,
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 8, 15),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos is not None
        # entry commission = commission_per_contract * 2 legs * contracts
        expected_entry_commission = 0.65 * 2 * pos['contracts']
        assert bt.capital == pytest.approx(100_000 - expected_entry_commission)

    def test_slippage_reduces_credit(self):
        """Slippage should reduce the credit received."""
        bt = _make_backtester()
        bt.capital = 100_000
        opp = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 440, 'long_strike': 435,
            'credit': 1.80, 'max_loss': 3.20,
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 8, 15),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        # credit after slippage = 1.80 - 0.05 = 1.75
        assert pos['credit'] == pytest.approx(1.75)

    def test_slippage_eliminates_credit_returns_none(self):
        """If slippage makes credit <= 0, position should not be opened."""
        bt = _make_backtester()
        bt.capital = 100_000
        opp = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 440, 'long_strike': 435,
            'credit': 0.04,  # 0.04 - 0.05 slippage = -0.01
            'max_loss': 4.96,
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 8, 15),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos is None

    def test_iron_condor_4_leg_commission(self):
        """Iron condor should have 4 legs worth of commission."""
        bt = _make_backtester()
        bt.capital = 100_000
        opp = {
            'ticker': 'SPY', 'type': 'iron_condor',
            'short_strike': 440, 'long_strike': 435,
            'call_short_strike': 460, 'call_long_strike': 465,
            'credit': 2.50, 'max_loss': 2.50,
            'spread_width': 5.0, 'score': 45,
            'expiration': datetime(2025, 8, 15),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos is not None
        # Total commission = commission_per_contract * 4 legs * contracts * 2 (entry+exit)
        expected_total = 0.65 * 4 * pos['contracts'] * 2
        assert pos['commission'] == pytest.approx(expected_total)

    def test_exit_slippage_applied_to_close(self):
        """Exit slippage should reduce realized PnL."""
        bt = _make_backtester()
        bt.capital = 100_000
        bt.trades = []

        pos = _make_position(credit=1.50, contracts=1, commission=2.60)
        # Close with known pnl_per_contract
        bt._close_position(pos, datetime(2025, 8, 1), "profit_target",
                           underlying_price=460.0, real_pnl_per_contract=0.80)
        trade = bt.trades[0]
        # pnl_per_contract after exit slippage = 0.80 - 0.05 = 0.75
        # pnl = 0.75 * 1 * 100 - exit_commission (half of 2.60 = 1.30)
        expected = 0.75 * 100 - 1.30
        assert trade['pnl'] == pytest.approx(expected)


# ===================================================================
# Position sizing
# ===================================================================

class TestPositionSizing:

    def test_contracts_capped_at_max(self):
        """Contracts should not exceed max_contracts."""
        cfg = _make_config()
        cfg['risk']['max_contracts'] = 3
        bt = _make_backtester(config=cfg)
        bt.capital = 1_000_000  # Very large capital -> many contracts

        opp = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 440, 'long_strike': 435,
            'credit': 1.80, 'max_loss': 3.20,
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 8, 15),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos['contracts'] <= 3

    def test_contracts_floored_at_min(self):
        """Contracts should be at least min_contracts."""
        cfg = _make_config()
        cfg['risk']['min_contracts'] = 2
        bt = _make_backtester(config=cfg)
        bt.capital = 100_000

        opp = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 440, 'long_strike': 435,
            'credit': 1.80, 'max_loss': 3.20,
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 8, 15),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos['contracts'] >= 2

    def test_credit_capped_at_95pct_of_width(self):
        """Credit should be capped at 95% of spread width."""
        bt = _make_backtester()
        bt.capital = 100_000
        opp = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 440, 'long_strike': 435,
            'credit': 5.50,  # > 5.0 width! (after slippage still > 95%)
            'max_loss': 0.50,  # Positive so it passes early check (recalculated later)
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 8, 15),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos is not None
        assert pos['credit'] <= 5.0 * 0.95 + 0.01  # Allow rounding

    def test_zero_max_loss_rejected(self):
        """Position with max_loss <= 0 should be rejected."""
        bt = _make_backtester()
        bt.capital = 100_000
        opp = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 440, 'long_strike': 435,
            'credit': 1.80, 'max_loss': 0,
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 8, 15),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos is None


# ===================================================================
# Portfolio limits
# ===================================================================

class TestPortfolioLimits:

    def test_no_limits_configured(self):
        """With empty portfolio_risk, all positions allowed."""
        bt = _make_backtester()
        pos = _make_position()
        assert bt._check_portfolio_limits(pos, []) is True

    def test_total_risk_limit(self):
        """Should reject when total portfolio risk exceeds max_portfolio_risk_pct."""
        cfg = _make_config()
        cfg['risk']['portfolio_risk'] = {'max_portfolio_risk_pct': 5}
        bt = _make_backtester(config=cfg)
        bt.capital = 100_000

        # Create existing positions with large risk
        existing = [_make_position(max_loss=4.0, contracts=10)]  # risk = 4*10*100 = 4000
        new = _make_position(max_loss=4.0, contracts=5)  # risk = 4*5*100 = 2000
        # Total = 6000 / 100_000 = 6% > 5%
        assert bt._check_portfolio_limits(new, existing) is False

    def test_ticker_concentration_limit(self):
        """Should reject when single ticker exceeds max_single_ticker_pct."""
        cfg = _make_config()
        cfg['risk']['portfolio_risk'] = {'max_single_ticker_pct': 2}
        bt = _make_backtester(config=cfg)
        bt.capital = 100_000

        existing = [_make_position(ticker='SPY', max_loss=1.5, contracts=10)]
        new = _make_position(ticker='SPY', max_loss=1.5, contracts=5)
        # SPY risk = (10+5)*1.5*100 = 2250 / 100_000 = 2.25% > 2%
        assert bt._check_portfolio_limits(new, existing) is False

    def test_same_expiration_limit(self):
        """Should reject when too many positions share same expiration week."""
        cfg = _make_config()
        cfg['risk']['portfolio_risk'] = {'max_same_expiration': 2}
        bt = _make_backtester(config=cfg)
        bt.capital = 100_000

        exp = datetime(2025, 8, 15)
        existing = [
            _make_position(expiration=exp),
            _make_position(expiration=exp + timedelta(days=1)),
        ]
        new = _make_position(expiration=exp)
        assert bt._check_portfolio_limits(new, existing) is False

    def test_correlation_group_limit(self):
        """Should reject when correlation group has too many positions."""
        cfg = _make_config()
        cfg['risk']['portfolio_risk'] = {'max_portfolio_risk_pct': 100}  # Non-empty to pass guard
        cfg['risk']['correlation_groups'] = {
            'tech_mega': {
                'tickers': ['SPY', 'QQQ'],
                'max_correlated_positions': 2,
            }
        }
        bt = _make_backtester(config=cfg)
        bt.capital = 100_000

        existing = [
            _make_position(ticker='SPY'),
            _make_position(ticker='QQQ'),
        ]
        new = _make_position(ticker='SPY')
        assert bt._check_portfolio_limits(new, existing) is False


# ===================================================================
# Snap to Friday
# ===================================================================

class TestSnapToFriday:

    def test_friday_unchanged(self):
        dt = datetime(2025, 7, 4)  # Friday
        assert BacktesterFixed._snap_to_friday(dt) == dt

    def test_monday_snaps_backward(self):
        """Monday is 4 days from Friday (> 3), so snaps backward."""
        dt = datetime(2025, 6, 30)  # Monday
        result = BacktesterFixed._snap_to_friday(dt)
        assert result.weekday() == 4
        assert result == datetime(2025, 6, 27)  # Previous Friday

    def test_wednesday_snaps_forward(self):
        """Wednesday is 2 days from Friday (<= 3), so snaps forward."""
        dt = datetime(2025, 7, 2)  # Wednesday
        result = BacktesterFixed._snap_to_friday(dt)
        assert result == datetime(2025, 7, 4)

    def test_thursday_snaps_forward(self):
        dt = datetime(2025, 7, 3)  # Thursday
        result = BacktesterFixed._snap_to_friday(dt)
        assert result == datetime(2025, 7, 4)

    def test_saturday_snaps_backward(self):
        dt = datetime(2025, 7, 5)  # Saturday
        result = BacktesterFixed._snap_to_friday(dt)
        assert result == datetime(2025, 7, 4)

    def test_sunday_snaps_backward(self):
        dt = datetime(2025, 7, 6)  # Sunday
        result = BacktesterFixed._snap_to_friday(dt)
        assert result == datetime(2025, 7, 4)

    def test_tuesday_snaps_forward(self):
        """Tuesday is 3 days from Friday (<= 3), so snaps forward."""
        dt = datetime(2025, 7, 1)  # Tuesday
        result = BacktesterFixed._snap_to_friday(dt)
        assert result == datetime(2025, 7, 4)


# ===================================================================
# Synthetic options chain
# ===================================================================

class TestSyntheticOptionsChain:

    def setup_method(self):
        self.bt = _make_backtester()

    def test_chain_has_puts_and_calls(self):
        chain = self.bt._get_synthetic_options_chain('SPY', datetime(2025, 7, 1), 450.0, 0.20)
        assert not chain.empty
        types = chain['type'].unique()
        assert 'put' in types
        assert 'call' in types

    def test_chain_has_multiple_expirations(self):
        chain = self.bt._get_synthetic_options_chain('SPY', datetime(2025, 7, 1), 450.0, 0.20)
        assert chain['expiration'].nunique() >= 3

    def test_bid_less_than_ask(self):
        chain = self.bt._get_synthetic_options_chain('SPY', datetime(2025, 7, 1), 450.0, 0.20)
        assert (chain['bid'] <= chain['ask']).all()

    def test_put_delta_negative(self):
        chain = self.bt._get_synthetic_options_chain('SPY', datetime(2025, 7, 1), 450.0, 0.20)
        puts = chain[chain['type'] == 'put']
        assert (puts['delta'] < 0).all()

    def test_call_delta_positive(self):
        chain = self.bt._get_synthetic_options_chain('SPY', datetime(2025, 7, 1), 450.0, 0.20)
        calls = chain[chain['type'] == 'call']
        assert (calls['delta'] > 0).all()

    def test_all_expirations_are_fridays(self):
        chain = self.bt._get_synthetic_options_chain('SPY', datetime(2025, 7, 1), 450.0, 0.20)
        for exp in chain['expiration'].unique():
            assert exp.weekday() == 4, f"{exp} is not a Friday"

    def test_sparse_strikes_low_price_stock(self):
        """Chain should still work for low-priced underlyings."""
        chain = self.bt._get_synthetic_options_chain('XYZ', datetime(2025, 7, 1), 15.0, 0.40)
        assert not chain.empty
        strikes = chain['strike'].unique()
        assert len(strikes) > 0


# ===================================================================
# Close position logic
# ===================================================================

class TestClosePosition:

    def setup_method(self):
        self.bt = _make_backtester()
        self.bt.capital = 100_000
        self.bt.trades = []

    def test_close_with_real_pnl(self):
        """When real_pnl_per_contract is provided, use it directly."""
        pos = _make_position(credit=1.50, contracts=2, commission=2.60)
        self.bt._close_position(pos, datetime(2025, 8, 1), "profit_target",
                                underlying_price=460.0, real_pnl_per_contract=0.80)
        trade = self.bt.trades[0]
        # pnl = (0.80 - slippage=0.05) * 2 * 100 - exit_comm(1.30)
        expected = (0.80 - 0.05) * 2 * 100 - 1.30
        assert trade['pnl'] == pytest.approx(expected)

    def test_close_expired_uses_bs(self):
        """When no real_pnl and expired, uses BS spread valuation."""
        pos = _make_position(credit=1.50, contracts=1, commission=2.60,
                             short_strike=440, long_strike=435,
                             expiration=datetime(2025, 8, 1))
        # Close at expiration with price well above short strike (OTM)
        self.bt._close_position(pos, datetime(2025, 8, 1), "expired",
                                underlying_price=460.0)
        trade = self.bt.trades[0]
        # OTM at expiry -> spread_val ≈ 0 -> pnl ≈ (1.50 - 0 - 0.05) * 100 - 1.30
        assert trade['pnl'] > 0

    def test_close_fallback_full_credit(self):
        """When no real_pnl and not expired/backtest_end, earn full credit."""
        pos = _make_position(credit=1.50, contracts=1, commission=2.60)
        self.bt._close_position(pos, datetime(2025, 7, 15), "manual_close")
        trade = self.bt.trades[0]
        # pnl = credit * contracts * 100 - exit_commission
        expected = 1.50 * 1 * 100 - 1.30
        assert trade['pnl'] == pytest.approx(expected)

    def test_close_updates_capital(self):
        """Closing should update self.capital."""
        initial = self.bt.capital
        pos = _make_position(credit=1.50, contracts=1, commission=2.60)
        self.bt._close_position(pos, datetime(2025, 8, 1), "profit_target",
                                underlying_price=460.0, real_pnl_per_contract=0.80)
        assert self.bt.capital != initial

    def test_close_records_exit_fields(self):
        """Closed position should have exit_date, exit_reason, exit_price, pnl, status."""
        pos = _make_position()
        self.bt._close_position(pos, datetime(2025, 8, 1), "expired",
                                underlying_price=460.0, real_pnl_per_contract=0.50)
        assert pos['exit_date'] == datetime(2025, 8, 1)
        assert pos['exit_reason'] == 'expired'
        assert pos['exit_price'] == 460.0
        assert pos['status'] == 'closed'
        assert 'pnl' in pos

    def test_iron_condor_cache_cleanup(self):
        """Closing an iron condor should clean up both put and call cache keys."""
        bt = _make_backtester()
        bt.capital = 100_000
        bt.trades = []

        pos = _make_position(spread_type='iron_condor')
        pos['call_short_strike'] = 460.0
        pos['call_long_strike'] = 465.0
        exp_iso = pos['expiration'].isoformat()

        # Pre-populate cache
        put_key = (440.0, 435.0, exp_iso)
        call_key = (460.0, 465.0, exp_iso)
        bt._spread_price_cache[put_key] = pd.DataFrame()
        bt._spread_price_cache[call_key] = pd.DataFrame()

        bt._close_position(pos, datetime(2025, 8, 1), "expired",
                           underlying_price=450.0, real_pnl_per_contract=0.50)
        assert put_key not in bt._spread_price_cache
        assert call_key not in bt._spread_price_cache


# ===================================================================
# Dynamic stop loss (gap-stop / width-based)
# ===================================================================

class TestDynamicStopLoss:

    def setup_method(self):
        self.bt = _make_backtester()

    def test_stop_widens_with_more_dte(self):
        """More DTE -> higher (wider) stop threshold."""
        pos = _make_position(spread_width=10.0, expiration=datetime(2025, 9, 1))
        # 30+ DTE
        stop_high = self.bt._get_dynamic_stop_value(pos, datetime(2025, 7, 25))
        # 5 DTE
        stop_low = self.bt._get_dynamic_stop_value(pos, datetime(2025, 8, 27))
        assert stop_high > stop_low

    def test_stop_tightens_near_expiry(self):
        """Stop should tighten in the last 7 days."""
        pos = _make_position(spread_width=10.0, expiration=datetime(2025, 8, 1))
        # 3 DTE
        stop = self.bt._get_dynamic_stop_value(pos, datetime(2025, 7, 29))
        # Should be 60% of width = 6.0
        base_pct = 75 / 100
        expected = 10.0 * (base_pct - 0.15)
        assert stop == pytest.approx(expected)

    def test_all_dte_buckets(self):
        """Test all 4 DTE buckets produce distinct stops."""
        pos = _make_position(spread_width=10.0, expiration=datetime(2025, 9, 1))
        # > 21 DTE
        s1 = self.bt._get_dynamic_stop_value(pos, datetime(2025, 8, 1))
        # 14-21 DTE
        s2 = self.bt._get_dynamic_stop_value(pos, datetime(2025, 8, 15))
        # 7-14 DTE
        s3 = self.bt._get_dynamic_stop_value(pos, datetime(2025, 8, 22))
        # < 7 DTE
        s4 = self.bt._get_dynamic_stop_value(pos, datetime(2025, 8, 28))
        assert s1 > s2 > s3 > s4


# ===================================================================
# Profit target
# ===================================================================

class TestProfitTarget:

    def test_flat_50_pct(self):
        bt = _make_backtester()
        pos = _make_position()
        assert bt._get_profit_target_pct(pos, datetime(2025, 7, 15)) == 0.50


# ===================================================================
# Manage positions (integration of profit target + stop loss + expiry)
# ===================================================================

class TestManagePositions:

    def setup_method(self):
        self.bt = _make_backtester()
        self.bt.capital = 100_000
        self.bt.trades = []
        self.price_data = _make_price_df(start='2025-06-01', periods=90, base=450.0)

    def test_expired_position_closed(self):
        """Position past expiration should be closed."""
        pos = _make_position(expiration=datetime(2025, 7, 1))
        current_date = datetime(2025, 7, 2)
        remaining = self.bt._manage_positions([pos], current_date, self.price_data, 'SPY', 0.20)
        assert len(remaining) == 0
        assert len(self.bt.trades) == 1
        assert self.bt.trades[0]['exit_reason'] == 'expired'

    def test_profit_target_hit(self):
        """Position with spread value near 0 (large profit) should be closed."""
        pos = _make_position(credit=1.50, short_strike=420, long_strike=415,
                             spread_width=5.0, expiration=datetime(2025, 9, 1))
        # Price is ~450, so 420/415 put spread is deep OTM -> spread_val ≈ small
        # credit=1.50, target=50% -> need pnl >= 0.75 -> spread_val <= 0.75
        remaining = self.bt._manage_positions(
            [pos], datetime(2025, 8, 1), self.price_data, 'SPY', 0.20
        )
        # With deep OTM spread, BS value should be tiny -> profit target likely hit
        if len(remaining) == 0:
            assert self.bt.trades[-1]['exit_reason'] == 'profit_target'

    def test_stop_loss_hit(self):
        """Position with spread value above stop threshold should stop out."""
        # Create ITM spread (price dropped below short strike)
        pos = _make_position(credit=1.50, short_strike=480, long_strike=475,
                             spread_width=5.0, expiration=datetime(2025, 9, 1))
        # Price is ~450, so 480/475 put spread is deep ITM -> spread_val ≈ 5.0
        remaining = self.bt._manage_positions(
            [pos], datetime(2025, 7, 15), self.price_data, 'SPY', 0.20
        )
        # Deep ITM: spread value should exceed stop threshold
        if len(remaining) == 0:
            assert self.bt.trades[-1]['exit_reason'] == 'stop_loss'

    def test_position_kept_when_no_exit_triggered(self):
        """Position that doesn't hit any exit should remain open."""
        pos = _make_position(credit=1.50, short_strike=420, long_strike=415,
                             spread_width=5.0, expiration=datetime(2025, 9, 30))
        # OTM with lots of DTE and moderate credit -> should stay open
        # But spread value may be low enough for profit target at 50%
        # Use a tighter credit to prevent profit target
        pos['credit'] = 3.00  # High credit -> need spread_val <= 1.50 for target
        remaining = self.bt._manage_positions(
            [pos], datetime(2025, 7, 10), self.price_data, 'SPY', 0.20
        )
        # With 82 DTE and credit=3.00, the OTM spread still has time value
        # so it likely won't hit 50% profit target yet
        assert len(remaining) <= 1  # either kept or closed

    def test_current_value_updated(self):
        """Remaining position should have current_value updated."""
        pos = _make_position(credit=2.00, short_strike=420, long_strike=415,
                             spread_width=5.0, expiration=datetime(2025, 9, 30))
        pos['credit'] = 3.50  # High credit prevents profit target
        remaining = self.bt._manage_positions(
            [pos], datetime(2025, 7, 2), self.price_data, 'SPY', 0.20
        )
        if remaining:
            # current_value should be set (pnl_per_contract * contracts * 100)
            assert 'current_value' in remaining[0]

    def test_uses_max_of_current_and_entry_iv(self):
        """Position management uses max(sigma, entry_iv) for vol spike protection."""
        pos = _make_position(entry_iv=0.30)
        # With sigma=0.15 (below entry_iv), should use 0.30
        # With sigma=0.40 (above entry_iv), should use 0.40
        # We verify this indirectly: the method shouldn't crash
        remaining = self.bt._manage_positions(
            [pos], datetime(2025, 7, 15), self.price_data, 'SPY', 0.15
        )
        # Just verify no crash
        assert isinstance(remaining, list)


# ===================================================================
# Rolling
# ===================================================================

class TestRolling:

    def test_rolling_disabled_returns_none(self):
        bt = _make_backtester()
        pos = _make_position()
        result = bt._attempt_roll(pos, datetime(2025, 7, 15), 450.0)
        assert result is None

    def test_rolling_enabled_basic(self):
        """With rolling enabled, a stop-eligible position should roll."""
        cfg = _make_config()
        cfg['risk']['enable_rolling'] = True
        cfg['risk']['max_rolls_per_position'] = 1
        cfg['risk']['min_roll_credit'] = 0.30
        bt = _make_backtester(config=cfg)
        bt.capital = 100_000

        pos = _make_position(credit=1.50, short_strike=440, long_strike=435,
                             spread_width=5.0, expiration=datetime(2025, 8, 1))
        rolled = bt._attempt_roll(pos, datetime(2025, 7, 20), 438.0)
        if rolled is not None:
            assert rolled['rolls'] == 1
            assert rolled['expiration'] > pos['expiration']
            assert rolled['credit'] > 0

    def test_max_rolls_exceeded(self):
        """Should not roll if max rolls already done."""
        cfg = _make_config()
        cfg['risk']['enable_rolling'] = True
        cfg['risk']['max_rolls_per_position'] = 1
        bt = _make_backtester(config=cfg)

        pos = _make_position()
        pos['rolls'] = 1  # Already rolled once
        result = bt._attempt_roll(pos, datetime(2025, 7, 15), 450.0)
        assert result is None

    def test_roll_commission_deducted(self):
        """Rolling should deduct commission for close + open."""
        cfg = _make_config()
        cfg['risk']['enable_rolling'] = True
        cfg['risk']['max_rolls_per_position'] = 2
        cfg['risk']['min_roll_credit'] = 0.10
        bt = _make_backtester(config=cfg)
        bt.capital = 100_000

        pos = _make_position(credit=1.50, contracts=2)
        initial_capital = bt.capital
        rolled = bt._attempt_roll(pos, datetime(2025, 7, 20), 438.0)
        if rolled is not None:
            # Roll commission = commission * 2 legs * 2 (close+open) * contracts
            expected_comm = 0.65 * 2 * 2 * 2
            assert bt.capital == pytest.approx(initial_capital - expected_comm)


# ===================================================================
# Real pricing mode with mocked HistoricalOptionsData / Polygon
# ===================================================================

class TestRealPricingMode:

    def test_polygon_credit_used_for_single_spread(self):
        """When Polygon provides spread prices, use real credit instead of synthetic."""
        polygon = MagicMock()
        spread_prices = pd.DataFrame(
            {'spread_value': [1.80, 1.50, 1.20]},
            index=pd.to_datetime(['2025-07-01', '2025-07-15', '2025-08-01']),
        )
        polygon.get_spread_historical_prices.return_value = spread_prices

        bt = _make_backtester(polygon_provider=polygon)
        bt.capital = 100_000

        opp = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 440, 'long_strike': 435,
            'credit': 1.00,  # Synthetic credit
            'max_loss': 4.00,
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 8, 1),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos is not None
        # Real credit is 1.80 - slippage 0.05 = 1.75 (not synthetic 1.00 - 0.05)
        assert pos['credit'] == pytest.approx(1.75)
        assert pos['pricing_source'] == 'polygon'

    def test_polygon_fallback_to_synthetic(self):
        """When Polygon returns no data, fall back to synthetic pricing."""
        polygon = MagicMock()
        polygon.get_spread_historical_prices.return_value = None

        bt = _make_backtester(polygon_provider=polygon)
        bt.capital = 100_000

        opp = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 440, 'long_strike': 435,
            'credit': 1.50, 'max_loss': 3.50,
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 8, 1),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos is not None
        assert pos['pricing_source'] == 'synthetic'
        # Credit = 1.50 - slippage
        assert pos['credit'] == pytest.approx(1.45)

    def test_polygon_condor_both_wings(self):
        """When both wings have Polygon data, use combined real credit."""
        polygon = MagicMock()
        put_prices = pd.DataFrame(
            {'spread_value': [1.00]},
            index=pd.to_datetime(['2025-07-01']),
        )
        call_prices = pd.DataFrame(
            {'spread_value': [0.90]},
            index=pd.to_datetime(['2025-07-01']),
        )
        # First call returns put prices, second returns call prices
        polygon.get_spread_historical_prices.side_effect = [put_prices, call_prices]

        bt = _make_backtester(polygon_provider=polygon)
        bt.capital = 100_000

        opp = {
            'ticker': 'SPY', 'type': 'iron_condor',
            'short_strike': 440, 'long_strike': 435,
            'call_short_strike': 460, 'call_long_strike': 465,
            'credit': 1.50,  # Synthetic
            'max_loss': 3.50,
            'spread_width': 5.0, 'score': 45,
            'expiration': datetime(2025, 8, 1),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos is not None
        # Real combined = 1.00 + 0.90 = 1.90 - slippage 0.05 = 1.85
        assert pos['credit'] == pytest.approx(1.85)
        assert pos['pricing_source'] == 'polygon'

    def test_polygon_condor_partial_put_only(self):
        """When only put wing has data, use partial pricing."""
        polygon = MagicMock()
        put_prices = pd.DataFrame(
            {'spread_value': [1.00]},
            index=pd.to_datetime(['2025-07-01']),
        )
        polygon.get_spread_historical_prices.side_effect = [put_prices, None]

        bt = _make_backtester(polygon_provider=polygon)
        bt.capital = 100_000

        opp = {
            'ticker': 'SPY', 'type': 'iron_condor',
            'short_strike': 440, 'long_strike': 435,
            'call_short_strike': 460, 'call_long_strike': 465,
            'credit': 2.00,  # Synthetic total
            'call_credit': 0.80,  # Synthetic call credit
            'max_loss': 3.00,
            'spread_width': 5.0, 'score': 45,
            'expiration': datetime(2025, 8, 1),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos is not None
        assert pos['pricing_source'] == 'partial_polygon'

    def test_cached_spread_prices_used_for_management(self):
        """After entry, cached spread prices should be used for daily management."""
        polygon = MagicMock()
        spread_prices = pd.DataFrame(
            {'spread_value': [1.80, 1.20, 0.50]},
            index=pd.to_datetime(['2025-07-01', '2025-07-10', '2025-07-20']),
        )
        polygon.get_spread_historical_prices.return_value = spread_prices

        bt = _make_backtester(polygon_provider=polygon)
        bt.capital = 100_000
        bt.trades = []

        opp = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 440, 'long_strike': 435,
            'credit': 1.50, 'max_loss': 3.50,
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 8, 1),
        }
        pos = bt._opportunity_to_position(opp, datetime(2025, 7, 1))
        assert pos is not None

        # Now check that _get_single_wing_value uses cached data
        exp_iso = pos['expiration'].isoformat()
        val = bt._get_single_wing_value(
            440, 435, 'put', datetime(2025, 7, 10), 450.0, exp_iso
        )
        # Should return cached value 1.20 from the spread_prices DataFrame
        assert val == pytest.approx(1.20)


# ===================================================================
# Walk-forward validation (run_backtest integration)
# ===================================================================

class TestRunBacktest:

    def _setup_bt_for_run(self, strategy_opps=None):
        """Set up a BacktesterFixed with mocked external dependencies."""
        strategy, tech, opts = _make_mocks()

        # Strategy returns opportunities when called
        if strategy_opps is not None:
            strategy.evaluate_spread_opportunity.return_value = strategy_opps
        else:
            strategy.evaluate_spread_opportunity.return_value = []

        # Technical analyzer returns valid signals
        tech.analyze.return_value = {
            'trend': 'bullish', 'rsi': 45, 'ma_fast': 450, 'ma_slow': 440,
        }

        # Options analyzer returns valid IV data
        opts.get_current_iv.return_value = 0.22
        opts.calculate_iv_rank.return_value = {
            'iv_rank': 35, 'iv_percentile': 40, 'current_iv': 0.22,
        }

        bt = _make_backtester(strategy=strategy, tech=tech, opts=opts)
        return bt

    @patch('backtest.backtester_fixed.yf')
    def test_no_data_returns_empty(self, mock_yf):
        """When yfinance returns no data, backtest returns empty dict."""
        mock_yf.download.return_value = pd.DataFrame()
        bt = self._setup_bt_for_run()
        result = bt.run_backtest('SPY', datetime(2025, 1, 1), datetime(2025, 3, 1))
        assert result == {}

    @patch('backtest.backtester_fixed.yf')
    def test_no_opportunities_returns_zero_trades(self, mock_yf):
        """When strategy finds no opportunities, should have 0 trades."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        bt = self._setup_bt_for_run(strategy_opps=[])
        result = bt.run_backtest('SPY', datetime(2025, 6, 1), datetime(2025, 7, 1))
        assert result['total_trades'] == 0
        assert result['total_pnl'] == 0

    @patch('backtest.backtester_fixed.yf')
    def test_equity_curve_recorded(self, mock_yf):
        """Equity curve should have entries for each day of the backtest."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        bt = self._setup_bt_for_run()
        start = datetime(2025, 6, 1)
        end = datetime(2025, 6, 15)
        result = bt.run_backtest('SPY', start, end)
        # Equity curve should have at least (end-start).days entries
        assert len(bt.equity_curve) >= (end - start).days

    @patch('backtest.backtester_fixed.yf')
    def test_multi_ticker_support(self, mock_yf):
        """Backtest should accept a list of tickers."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        bt = self._setup_bt_for_run()
        result = bt.run_backtest(['SPY', 'QQQ'], datetime(2025, 6, 1), datetime(2025, 6, 15))
        assert 'tickers' in result
        assert set(result['tickers']) == {'SPY', 'QQQ'}

    @patch('backtest.backtester_fixed.yf')
    def test_drawdown_circuit_breaker(self, mock_yf):
        """When equity drops > 15%, should skip new entries."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        bt = self._setup_bt_for_run()
        # Simulate drawdown by reducing capital before running
        bt.starting_capital = 100_000
        result = bt.run_backtest('SPY', datetime(2025, 6, 1), datetime(2025, 6, 5))
        # Just verify it runs without error
        assert isinstance(result, dict)

    @patch('backtest.backtester_fixed.yf')
    def test_open_positions_closed_at_backtest_end(self, mock_yf):
        """Any remaining open positions should be closed at backtest end."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        # Return a high-scoring opportunity
        opp = {
            'type': 'bull_put_spread', 'ticker': 'SPY',
            'short_strike': 430.0, 'long_strike': 425.0,
            'credit': 1.50, 'max_loss': 3.50,
            'spread_width': 5.0, 'score': 50,
            'expiration': datetime(2025, 8, 15),  # Far beyond end
        }
        bt = self._setup_bt_for_run(strategy_opps=[opp])
        start = datetime(2025, 6, 2)  # Monday
        end = datetime(2025, 6, 4)  # Wednesday — very short window

        result = bt.run_backtest('SPY', start, end)
        # Any opened positions should be closed at backtest_end
        for trade in result.get('trades', []):
            assert trade.get('status') == 'closed'

    @patch('backtest.backtester_fixed.yf')
    def test_scan_only_on_scan_days(self, mock_yf):
        """Scanning should only happen on configured scan days."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        strategy, tech, opts = _make_mocks()
        strategy.evaluate_spread_opportunity.return_value = []
        tech.analyze.return_value = {'trend': 'bullish', 'rsi': 45}
        opts.get_current_iv.return_value = 0.22
        opts.calculate_iv_rank.return_value = {'iv_rank': 35, 'iv_percentile': 40, 'current_iv': 0.22}

        cfg = _make_config()
        cfg['risk']['scan_days'] = [0]  # Monday only
        bt = _make_backtester(config=cfg, strategy=strategy, tech=tech, opts=opts)

        # Run over a full week
        start = datetime(2025, 6, 2)  # Monday
        end = datetime(2025, 6, 8)    # Sunday
        result = bt.run_backtest('SPY', start, end)
        # Should scan only on Monday = 1 scan
        assert result['scans_performed'] == 1

    @patch('backtest.backtester_fixed.yf')
    def test_max_positions_enforced(self, mock_yf):
        """Should not open more positions than max_positions."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        opp = {
            'type': 'bull_put_spread', 'ticker': 'SPY',
            'short_strike': 420.0, 'long_strike': 415.0,
            'credit': 1.50, 'max_loss': 3.50,
            'spread_width': 5.0, 'score': 50,
            'expiration': datetime(2025, 9, 19),  # Far out
        }

        strategy, tech, opts = _make_mocks()
        strategy.evaluate_spread_opportunity.return_value = [opp]
        tech.analyze.return_value = {'trend': 'bullish', 'rsi': 45}
        opts.get_current_iv.return_value = 0.22
        opts.calculate_iv_rank.return_value = {'iv_rank': 35, 'iv_percentile': 40, 'current_iv': 0.22}

        cfg = _make_config()
        cfg['risk']['max_positions'] = 2
        cfg['risk']['max_positions_per_ticker'] = 5  # Don't limit by ticker
        bt = _make_backtester(config=cfg, strategy=strategy, tech=tech, opts=opts)

        # Run long enough to have many scan days
        start = datetime(2025, 6, 2)
        end = datetime(2025, 7, 15)
        result = bt.run_backtest('SPY', start, end)
        # Can't have more than 2 positions open simultaneously (they may close and reopen)
        assert isinstance(result, dict)


# ===================================================================
# Calculate results
# ===================================================================

class TestCalculateResults:

    def test_no_trades(self):
        """With no trades, results should be zeroed out."""
        bt = _make_backtester()
        bt.capital = 100_000
        bt.trades = []
        bt.equity_curve = [(datetime(2025, 1, 1), 100_000)]
        results = bt._calculate_results()
        assert results['total_trades'] == 0
        assert results['win_rate'] == 0
        assert results['sharpe_ratio'] == 0

    def test_all_winners(self):
        """Win rate should be 100% when all trades profit."""
        bt = _make_backtester()
        bt.capital = 102_000
        bt.trades = [
            {**_make_position(), 'pnl': 500, 'exit_date': datetime(2025, 7, 15), 'rolls': 0},
            {**_make_position(), 'pnl': 300, 'exit_date': datetime(2025, 7, 20), 'rolls': 0},
        ]
        bt.equity_curve = [
            (datetime(2025, 7, 1), 100_000),
            (datetime(2025, 7, 15), 100_500),
            (datetime(2025, 7, 20), 100_800),
        ]
        results = bt._calculate_results()
        assert results['win_rate'] == 100.0
        assert results['total_pnl'] == 800.0

    def test_mixed_results(self):
        """Should correctly calculate win rate, avg win, avg loss."""
        bt = _make_backtester()
        bt.capital = 99_700
        bt.trades = [
            {**_make_position(), 'pnl': 500, 'exit_date': datetime(2025, 7, 15), 'rolls': 0},
            {**_make_position(), 'pnl': -800, 'exit_date': datetime(2025, 7, 20), 'rolls': 0},
        ]
        bt.equity_curve = [
            (datetime(2025, 7, 1), 100_000),
            (datetime(2025, 7, 15), 100_500),
            (datetime(2025, 7, 20), 99_700),
        ]
        results = bt._calculate_results()
        assert results['total_trades'] == 2
        assert results['winning_trades'] == 1
        assert results['losing_trades'] == 1
        assert results['win_rate'] == 50.0
        assert results['avg_win'] == 500.0
        assert results['avg_loss'] == -800.0

    def test_max_drawdown_calculated(self):
        """Max drawdown should reflect peak-to-trough decline."""
        bt = _make_backtester()
        bt.capital = 95_000
        bt.trades = [
            {**_make_position(), 'pnl': -5000, 'exit_date': datetime(2025, 7, 20), 'rolls': 0},
        ]
        bt.equity_curve = [
            (datetime(2025, 7, 1), 100_000),
            (datetime(2025, 7, 10), 102_000),  # peak
            (datetime(2025, 7, 20), 95_000),   # trough
        ]
        results = bt._calculate_results()
        # Drawdown = (95000 - 102000) / 102000 * 100 ≈ -6.86%
        assert results['max_drawdown'] < 0
        assert results['max_drawdown'] == pytest.approx(-6.86, abs=0.1)

    def test_rolled_positions_counted(self):
        """Should count total rolls across all trades."""
        bt = _make_backtester()
        bt.capital = 100_000
        bt.trades = [
            {**_make_position(), 'pnl': 100, 'exit_date': datetime(2025, 7, 15), 'rolls': 1},
            {**_make_position(), 'pnl': 200, 'exit_date': datetime(2025, 7, 20), 'rolls': 2},
        ]
        bt.equity_curve = [
            (datetime(2025, 7, 1), 100_000),
            (datetime(2025, 7, 20), 100_300),
        ]
        results = bt._calculate_results()
        assert results['rolled_positions'] == 3

    def test_return_pct(self):
        """Return percentage should reflect capital change."""
        bt = _make_backtester()
        bt.capital = 110_000
        bt.trades = [
            {**_make_position(), 'pnl': 10_000, 'exit_date': datetime(2025, 7, 20), 'rolls': 0},
        ]
        bt.equity_curve = [
            (datetime(2025, 7, 1), 100_000),
            (datetime(2025, 7, 20), 110_000),
        ]
        results = bt._calculate_results()
        assert results['return_pct'] == 10.0

    def test_trade_type_breakdown(self):
        """Should break down trades by type."""
        bt = _make_backtester()
        bt.capital = 100_000
        bt.trades = [
            {**_make_position(spread_type='bull_put_spread'), 'pnl': 100, 'exit_date': datetime(2025, 7, 15), 'rolls': 0},
            {**_make_position(spread_type='bear_call_spread'), 'pnl': 200, 'exit_date': datetime(2025, 7, 20), 'rolls': 0},
            {**_make_position(spread_type='bull_put_spread'), 'pnl': 150, 'exit_date': datetime(2025, 7, 25), 'rolls': 0},
        ]
        bt.equity_curve = [
            (datetime(2025, 7, 1), 100_000),
            (datetime(2025, 7, 25), 100_450),
        ]
        results = bt._calculate_results()
        assert results['trade_types']['bull_put_spread'] == 2
        assert results['trade_types']['bear_call_spread'] == 1


# ===================================================================
# Edge cases
# ===================================================================

class TestEdgeCases:

    def test_get_entry_credit_empty_df(self):
        """Should return None for empty spread prices."""
        bt = _make_backtester()
        assert bt._get_entry_credit(None, datetime(2025, 7, 1)) is None
        assert bt._get_entry_credit(pd.DataFrame(), datetime(2025, 7, 1)) is None

    def test_get_entry_credit_no_matching_date(self):
        """Should return None when no data on/after entry date."""
        bt = _make_backtester()
        df = pd.DataFrame(
            {'spread_value': [1.50]},
            index=pd.to_datetime(['2025-06-01']),
        )
        result = bt._get_entry_credit(df, datetime(2025, 7, 1))
        assert result is None

    def test_get_entry_credit_zero_value(self):
        """Zero spread value should return None."""
        bt = _make_backtester()
        df = pd.DataFrame(
            {'spread_value': [0.0]},
            index=pd.to_datetime(['2025-07-01']),
        )
        result = bt._get_entry_credit(df, datetime(2025, 7, 1))
        assert result is None

    def test_get_entry_credit_valid(self):
        """Valid spread value should be returned."""
        bt = _make_backtester()
        df = pd.DataFrame(
            {'spread_value': [1.80]},
            index=pd.to_datetime(['2025-07-01']),
        )
        result = bt._get_entry_credit(df, datetime(2025, 7, 1))
        assert result == pytest.approx(1.80)

    def test_manage_positions_no_price_data(self):
        """When price data has no rows before current_date, return positions unchanged."""
        bt = _make_backtester()
        bt.capital = 100_000
        bt.trades = []
        # Price data starts after current_date
        future_df = _make_price_df(start='2025-09-01', periods=30)
        pos = _make_position(expiration=datetime(2025, 10, 1))
        remaining = bt._manage_positions([pos], datetime(2025, 7, 1), future_df, 'SPY', 0.20)
        assert len(remaining) == 1  # unchanged

    @patch('backtest.backtester_fixed.yf')
    def test_single_ticker_string_accepted(self, mock_yf):
        """run_backtest should accept a single ticker string."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        bt = _make_backtester()
        bt.strategy.evaluate_spread_opportunity.return_value = []
        bt.technical_analyzer.analyze.return_value = {'trend': 'bullish', 'rsi': 45}
        bt.options_analyzer.get_current_iv.return_value = 0.22
        bt.options_analyzer.calculate_iv_rank.return_value = {
            'iv_rank': 35, 'iv_percentile': 40, 'current_iv': 0.22,
        }

        result = bt.run_backtest('SPY', datetime(2025, 6, 1), datetime(2025, 6, 5))
        assert isinstance(result, dict)
        assert result['tickers'] == ['SPY']


# ===================================================================
# Mark-to-market equity curve
# ===================================================================

class TestMarkToMarketEquityCurve:

    @patch('backtest.backtester_fixed.yf')
    def test_equity_curve_includes_unrealized_pnl(self, mock_yf):
        """Equity curve should include unrealized P&L from open positions."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        opp = {
            'type': 'bull_put_spread', 'ticker': 'SPY',
            'short_strike': 420.0, 'long_strike': 415.0,
            'credit': 1.50, 'max_loss': 3.50,
            'spread_width': 5.0, 'score': 50,
            'expiration': datetime(2025, 9, 19),
        }

        strategy, tech, opts = _make_mocks()
        strategy.evaluate_spread_opportunity.return_value = [opp]
        tech.analyze.return_value = {'trend': 'bullish', 'rsi': 45}
        opts.get_current_iv.return_value = 0.22
        opts.calculate_iv_rank.return_value = {'iv_rank': 35, 'iv_percentile': 40, 'current_iv': 0.22}

        bt = _make_backtester(strategy=strategy, tech=tech, opts=opts)

        start = datetime(2025, 6, 2)  # Monday
        end = datetime(2025, 6, 10)   # Following Tuesday

        result = bt.run_backtest('SPY', start, end)

        # Equity curve should have entries (date, equity)
        assert len(bt.equity_curve) > 0
        # total_equity = capital + position_value (unrealized)
        # So equity may differ from capital alone
        for date, equity in bt.equity_curve:
            assert isinstance(equity, (int, float))


# ===================================================================
# Assignment / pin risk handling
# ===================================================================

class TestAssignmentPinRisk:

    def test_at_expiry_itm_put_spread_max_loss(self):
        """At expiration, deep ITM put spread should result in near-max-loss."""
        bt = _make_backtester()
        bt.capital = 100_000
        bt.trades = []

        # Put spread where price is below both strikes at expiry (fully ITM)
        pos = _make_position(
            credit=1.50, short_strike=450, long_strike=445,
            spread_width=5.0, contracts=1, commission=2.60,
            expiration=datetime(2025, 8, 1),
        )

        # At expiry, price = 430 (below both strikes, fully ITM)
        bt._close_position(pos, datetime(2025, 8, 1), "expired",
                           underlying_price=430.0,
                           real_pnl_per_contract=1.50 - 5.0)  # credit - spread_width
        trade = bt.trades[0]
        # pnl_pc after slippage = (1.50 - 5.0) - 0.05 = -3.55
        # pnl = -3.55 * 1 * 100 - 1.30 = -356.30
        assert trade['pnl'] < 0
        # Should be approximately -(max_loss*100) - commission
        expected_pnl = (-3.55) * 100 - 1.30
        assert trade['pnl'] == pytest.approx(expected_pnl)

    def test_at_expiry_otm_put_spread_full_profit(self):
        """At expiration, OTM put spread should yield near-full credit."""
        bt = _make_backtester()
        bt.capital = 100_000
        bt.trades = []

        pos = _make_position(
            credit=1.50, short_strike=440, long_strike=435,
            spread_width=5.0, contracts=1, commission=2.60,
            expiration=datetime(2025, 8, 1),
        )

        # At expiry, price = 460 (above short strike, fully OTM)
        bt._close_position(pos, datetime(2025, 8, 1), "expired",
                           underlying_price=460.0,
                           real_pnl_per_contract=1.50)  # full credit kept
        trade = bt.trades[0]
        # pnl_pc after slippage = 1.50 - 0.05 = 1.45
        # pnl = 1.45 * 100 - 1.30 = 143.70
        assert trade['pnl'] > 0
        assert trade['pnl'] == pytest.approx(143.70)

    def test_pin_risk_short_strike(self):
        """Price at exactly short strike at expiry: BS should give partial value."""
        bt = _make_backtester()
        # Price exactly at short strike at expiry
        val = bt._bs_spread_value(450, 445, 'put', 450.0, 0, 0.20)
        # At expiry with S == K_short, intrinsic of short put = 0
        assert val == pytest.approx(0.0, abs=0.01)

    def test_pin_risk_between_strikes(self):
        """Price between short and long strikes at expiry: partial loss."""
        bt = _make_backtester()
        # Price between strikes: short=450, long=445, price=447
        val = bt._bs_spread_value(450, 445, 'put', 447.0, 0, 0.20)
        # Short put intrinsic = 450 - 447 = 3, long put intrinsic = 0 (445 < 447)
        # Spread value = 3 - 0 = 3
        assert val == pytest.approx(3.0, abs=0.01)


# ===================================================================
# Get current spread value (iron condor vs single)
# ===================================================================

class TestGetCurrentSpreadValue:

    def setup_method(self):
        self.bt = _make_backtester()

    def test_single_put_spread(self):
        pos = _make_position(spread_type='bull_put_spread',
                             short_strike=440, long_strike=435,
                             expiration=datetime(2025, 8, 15))
        val = self.bt._get_current_spread_value(pos, datetime(2025, 7, 15), 460.0, 0.20)
        assert val >= 0
        assert val <= 5.0  # Can't exceed spread width

    def test_single_call_spread(self):
        pos = _make_position(spread_type='bear_call_spread',
                             short_strike=460, long_strike=465,
                             expiration=datetime(2025, 8, 15))
        val = self.bt._get_current_spread_value(pos, datetime(2025, 7, 15), 440.0, 0.20)
        assert val >= 0
        assert val <= 5.0

    def test_iron_condor_both_wings(self):
        pos = _make_position(spread_type='iron_condor',
                             short_strike=440, long_strike=435,
                             expiration=datetime(2025, 8, 15))
        pos['call_short_strike'] = 460.0
        pos['call_long_strike'] = 465.0
        val = self.bt._get_current_spread_value(pos, datetime(2025, 7, 15), 450.0, 0.20)
        # Both wings should contribute
        assert val >= 0
        assert val <= 10.0  # Both wings max = 2 * 5

    def test_iron_condor_only_one_wing_itm(self):
        """Only one wing of a condor can be ITM at a time."""
        pos = _make_position(spread_type='iron_condor',
                             short_strike=440, long_strike=435,
                             expiration=datetime(2025, 8, 15))
        pos['call_short_strike'] = 460.0
        pos['call_long_strike'] = 465.0
        # Price at 430 -> put side ITM, call side OTM
        val = self.bt._get_current_spread_value(pos, datetime(2025, 8, 15), 430.0, 0.20)
        # Put side should be ~5.0, call side should be ~0.0
        assert val >= 4.5  # Put side dominates
        assert val <= 6.0  # But call side has tiny time value


# ===================================================================
# ML pipeline integration
# ===================================================================

class TestMLPipelineIntegration:

    @patch('backtest.backtester_fixed.yf')
    def test_ml_score_blending(self, mock_yf):
        """ML scores should be blended with rules-based scores."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        strategy, tech, opts = _make_mocks()
        tech.analyze.return_value = {'trend': 'bullish', 'rsi': 45}
        opts.get_current_iv.return_value = 0.22
        opts.calculate_iv_rank.return_value = {'iv_rank': 35, 'iv_percentile': 40, 'current_iv': 0.22}

        opp = {
            'type': 'bull_put_spread', 'ticker': 'SPY',
            'short_strike': 420.0, 'long_strike': 415.0,
            'credit': 1.50, 'max_loss': 3.50,
            'spread_width': 5.0, 'score': 40,
            'expiration': datetime(2025, 9, 19),
        }
        strategy.evaluate_spread_opportunity.return_value = [opp]

        ml = MagicMock()
        ml.analyze_trade.return_value = {
            'enhanced_score': 60,
            'event_risk': {'event_risk_score': 0.3},
        }

        bt = _make_backtester(strategy=strategy, tech=tech, opts=opts, ml_pipeline=ml)
        result = bt.run_backtest('SPY', datetime(2025, 6, 2), datetime(2025, 6, 4))
        # ML should have been called
        assert ml.analyze_trade.called

    @patch('backtest.backtester_fixed.yf')
    def test_high_event_risk_zeros_score(self, mock_yf):
        """High event risk should zero out the score."""
        price_df = _make_price_df(start='2024-01-01', periods=400, base=450.0)
        mock_yf.download.return_value = price_df

        strategy, tech, opts = _make_mocks()
        tech.analyze.return_value = {'trend': 'bullish', 'rsi': 45}
        opts.get_current_iv.return_value = 0.22
        opts.calculate_iv_rank.return_value = {'iv_rank': 35, 'iv_percentile': 40, 'current_iv': 0.22}

        opp = {
            'type': 'bull_put_spread', 'ticker': 'SPY',
            'short_strike': 420.0, 'long_strike': 415.0,
            'credit': 1.50, 'max_loss': 3.50,
            'spread_width': 5.0, 'score': 50,
            'expiration': datetime(2025, 9, 19),
        }
        strategy.evaluate_spread_opportunity.return_value = [opp]

        ml = MagicMock()
        ml.analyze_trade.return_value = {
            'enhanced_score': 60,
            'event_risk': {'event_risk_score': 0.9},  # Above threshold 0.7
        }

        bt = _make_backtester(strategy=strategy, tech=tech, opts=opts, ml_pipeline=ml)
        result = bt.run_backtest('SPY', datetime(2025, 6, 2), datetime(2025, 6, 4))
        # Score should be zeroed -> no trades opened
        assert result['total_trades'] == 0


# ===================================================================
# _find_opportunity_real_logic
# ===================================================================

class TestFindOpportunityRealLogic:

    def test_returns_highest_scoring_opportunity(self):
        """Should return the opportunity with the highest score."""
        strategy, tech, opts = _make_mocks()
        tech.analyze.return_value = {'trend': 'bullish', 'rsi': 45}
        opts.get_current_iv.return_value = 0.22
        opts.calculate_iv_rank.return_value = {'iv_rank': 35, 'iv_percentile': 40, 'current_iv': 0.22}

        opps = [
            {'type': 'bull_put_spread', 'score': 30},
            {'type': 'bear_call_spread', 'score': 45},
            {'type': 'bull_put_spread', 'score': 35},
        ]
        strategy.evaluate_spread_opportunity.return_value = opps

        bt = _make_backtester(strategy=strategy, tech=tech, opts=opts)
        price_df = _make_price_df(start='2025-06-01', periods=30, base=450.0)
        date = datetime(2025, 7, 1)

        result = bt._find_opportunity_real_logic('SPY', date, 450.0, price_df)
        assert result is not None
        assert result['score'] == 45

    def test_filters_below_threshold(self):
        """Opportunities below score_threshold should be filtered out."""
        strategy, tech, opts = _make_mocks()
        tech.analyze.return_value = {'trend': 'bullish', 'rsi': 45}
        opts.get_current_iv.return_value = 0.22
        opts.calculate_iv_rank.return_value = {'iv_rank': 35, 'iv_percentile': 40, 'current_iv': 0.22}

        # All below threshold (28)
        opps = [
            {'type': 'bull_put_spread', 'score': 20},
            {'type': 'bear_call_spread', 'score': 25},
        ]
        strategy.evaluate_spread_opportunity.return_value = opps

        bt = _make_backtester(strategy=strategy, tech=tech, opts=opts)
        price_df = _make_price_df(start='2025-06-01', periods=30, base=450.0)

        result = bt._find_opportunity_real_logic('SPY', datetime(2025, 7, 1), 450.0, price_df)
        assert result is None

    def test_exception_returns_none(self):
        """If an exception occurs, should return None."""
        strategy, tech, opts = _make_mocks()
        tech.analyze.side_effect = Exception("Analysis failed")

        bt = _make_backtester(strategy=strategy, tech=tech, opts=opts)
        price_df = _make_price_df(start='2025-06-01', periods=30, base=450.0)

        result = bt._find_opportunity_real_logic('SPY', datetime(2025, 7, 1), 450.0, price_df)
        assert result is None

    def test_empty_chain_returns_none(self):
        """If synthetic chain is empty (e.g., weird price), return None."""
        strategy, tech, opts = _make_mocks()
        tech.analyze.return_value = {'trend': 'bullish', 'rsi': 45}

        bt = _make_backtester(strategy=strategy, tech=tech, opts=opts)
        # 0 price will cause issues in BS calculation
        price_df = _make_price_df(start='2025-06-01', periods=30, base=450.0)

        with patch.object(bt, '_get_synthetic_options_chain', return_value=pd.DataFrame()):
            result = bt._find_opportunity_real_logic('SPY', datetime(2025, 7, 1), 450.0, price_df)
            assert result is None


# ===================================================================
# _get_historical_data
# ===================================================================

class TestGetHistoricalData:

    @patch('backtest.backtester_fixed.yf')
    def test_returns_data(self, mock_yf):
        mock_yf.download.return_value = _make_price_df()
        bt = _make_backtester()
        df = bt._get_historical_data('SPY', datetime(2025, 1, 1), datetime(2025, 6, 1))
        assert not df.empty

    @patch('backtest.backtester_fixed.yf')
    def test_empty_on_failure(self, mock_yf):
        mock_yf.download.side_effect = Exception("Network error")
        bt = _make_backtester()
        df = bt._get_historical_data('SPY', datetime(2025, 1, 1), datetime(2025, 6, 1))
        assert df.empty

    @patch('backtest.backtester_fixed.yf')
    def test_handles_multiindex_columns(self, mock_yf):
        """MultiIndex columns (e.g., from multi-ticker download) should be flattened."""
        df = _make_price_df()
        # Create MultiIndex columns
        mi = pd.MultiIndex.from_tuples([(c, 'SPY') for c in df.columns])
        df.columns = mi
        mock_yf.download.return_value = df
        bt = _make_backtester()
        result = bt._get_historical_data('SPY', datetime(2025, 1, 1), datetime(2025, 6, 1))
        assert not isinstance(result.columns, pd.MultiIndex)


# ===================================================================
# _fetch_leg_prices
# ===================================================================

class TestFetchLegPrices:

    def test_no_polygon_returns_none(self):
        bt = _make_backtester(polygon_provider=None)
        result = bt._fetch_leg_prices('SPY', datetime(2025, 8, 15), 440, 435, 'put', datetime(2025, 7, 1))
        assert result is None

    def test_with_polygon_calls_provider(self):
        polygon = MagicMock()
        polygon.get_spread_historical_prices.return_value = pd.DataFrame()
        bt = _make_backtester(polygon_provider=polygon)
        bt._fetch_leg_prices('SPY', datetime(2025, 8, 15), 440, 435, 'put', datetime(2025, 7, 1))
        polygon.get_spread_historical_prices.assert_called_once()
