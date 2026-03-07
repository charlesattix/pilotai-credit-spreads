"""Tests for the ZeroDTESpreadStrategy.

Covers signal generation (bull put, bear call, iron condor, VIX gate, event
skip, gap filter), spread/condor construction, position management, sizing,
param space, and the paper-trader DTE bypass.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from strategies.base import (
    LegType, MarketSnapshot, ParamDef, PortfolioState,
    Position, PositionAction, Signal, TradeLeg, TradeDirection,
)
from strategies.zero_dte_spread import ZeroDTESpreadStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(
    price: float = 550.0,
    vix: float = 20.0,
    rsi: float = 50.0,
    ticker: str = "SPY",
    date: datetime = None,
    upcoming_events: list = None,
    open_price: float = None,
    iv: float = 0.20,
    num_bars: int = 30,
) -> MarketSnapshot:
    """Build a minimal MarketSnapshot for testing."""
    if date is None:
        # Wednesday (weekday=2)
        date = datetime(2026, 3, 4, tzinfo=timezone.utc)

    # Build price_data with enough history for EMA
    closes = np.linspace(price * 0.98, price, num_bars)
    df = pd.DataFrame({
        "Close": closes,
        "Open": closes,
        "High": closes * 1.001,
        "Low": closes * 0.999,
        "Volume": [1_000_000] * num_bars,
    })

    return MarketSnapshot(
        date=date,
        price_data={ticker: df},
        prices={ticker: price},
        open_prices={ticker: open_price if open_price is not None else price},
        vix=vix,
        rsi={ticker: rsi},
        realized_vol={ticker: iv},
        iv_rank={ticker: 30.0},
        upcoming_events=upcoming_events or [],
        risk_free_rate=0.045,
    )


def _default_params(**overrides) -> dict:
    """Return default params with optional overrides."""
    params = {p.name: p.default for p in ZeroDTESpreadStrategy.get_param_space()}
    params.update(overrides)
    return params


def _make_strategy(**overrides) -> ZeroDTESpreadStrategy:
    return ZeroDTESpreadStrategy(_default_params(**overrides))


# ---------------------------------------------------------------------------
# TestSignalGeneration
# ---------------------------------------------------------------------------

class TestSignalGeneration:
    """Signal generation: mode selection, filters, and gating."""

    def test_bull_put_uptrend(self):
        """Price above EMA → bull_put spread."""
        # Price well above trend line
        strat = _make_strategy()
        snap = _make_snapshot(price=560.0, vix=18.0, rsi=65.0)
        signals = strat.generate_signals(snap)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.metadata["spread_type"] == "bull_put"
        assert sig.metadata["is_zero_dte"] is True

    def test_bear_call_downtrend(self):
        """Price below EMA → bear_call spread."""
        strat = _make_strategy()
        # Build snapshot where price is well below the EMA
        # EMA of closes at 560, current price=540, but open must be near
        # prior close to avoid gap filter
        date = datetime(2026, 3, 4, tzinfo=timezone.utc)
        closes = np.linspace(560.0, 560.0, 30)  # EMA ~560
        df = pd.DataFrame({
            "Close": closes,
            "Open": closes,
            "High": closes * 1.001,
            "Low": closes * 0.999,
            "Volume": [1_000_000] * 30,
        })
        snap = MarketSnapshot(
            date=date,
            price_data={"SPY": df},
            prices={"SPY": 540.0},  # price < EMA
            open_prices={"SPY": 559.0},  # near prior close to pass gap filter
            vix=18.0,
            rsi={"SPY": 35.0},
            realized_vol={"SPY": 0.20},
            upcoming_events=[],
            risk_free_rate=0.045,
        )
        signals = strat.generate_signals(snap)
        assert len(signals) == 1
        assert signals[0].metadata["spread_type"] == "bear_call"

    def test_iron_condor_range_bound(self):
        """VIX > ic_vix_threshold AND RSI in neutral zone → condor."""
        strat = _make_strategy(ic_vix_threshold=20.0, rsi_min_ic=40, rsi_max_ic=60)
        snap = _make_snapshot(price=550.0, vix=25.0, rsi=50.0)
        signals = strat.generate_signals(snap)
        assert len(signals) == 1
        assert signals[0].metadata["spread_type"] == "iron_condor"
        assert signals[0].direction == TradeDirection.NEUTRAL

    def test_vix_gate_too_low(self):
        """VIX below min_vix → no signals."""
        strat = _make_strategy(min_vix=12.0)
        snap = _make_snapshot(vix=10.0)
        assert strat.generate_signals(snap) == []

    def test_vix_gate_too_high(self):
        """VIX above max_vix_skip → no signals."""
        strat = _make_strategy(max_vix_skip=45.0)
        snap = _make_snapshot(vix=50.0)
        assert strat.generate_signals(snap) == []

    def test_skip_non_zero_dte_tickers(self):
        """Tickers not in ZERO_DTE_TICKERS produce no signals."""
        strat = _make_strategy()
        snap = _make_snapshot(ticker="AAPL")
        # SPY/QQQ not in prices → no signals
        assert strat.generate_signals(snap) == []

    def test_skip_weekend(self):
        """Weekends produce no signals."""
        strat = _make_strategy()
        # Saturday
        snap = _make_snapshot(date=datetime(2026, 3, 7, tzinfo=timezone.utc))
        assert strat.generate_signals(snap) == []

    def test_event_day_skip(self):
        """FOMC/CPI event day → no signals."""
        strat = _make_strategy()
        event_date = datetime(2026, 3, 4, tzinfo=timezone.utc)
        snap = _make_snapshot(
            date=event_date,
            upcoming_events=[{"date": event_date, "type": "FOMC"}],
        )
        assert strat.generate_signals(snap) == []

    def test_gap_filter(self):
        """Large overnight gap → skip ticker."""
        strat = _make_strategy(max_gap_pct=0.01)
        # open is 3% higher than prior close (gap > 1%)
        snap = _make_snapshot(price=550.0, open_price=566.5)
        assert strat.generate_signals(snap) == []


# ---------------------------------------------------------------------------
# TestSpreadConstruction
# ---------------------------------------------------------------------------

class TestSpreadConstruction:
    """Verify _build_spread_0dte output properties."""

    def test_expiration_same_day(self):
        """Signal expiration must equal the market date."""
        strat = _make_strategy()
        snap = _make_snapshot(price=550.0, vix=18.0)
        sigs = strat.generate_signals(snap)
        assert len(sigs) >= 1
        assert sigs[0].expiration == snap.date

    def test_dte_zero(self):
        """DTE must be 0."""
        strat = _make_strategy()
        sigs = strat.generate_signals(_make_snapshot(vix=18.0))
        assert sigs[0].dte == 0

    def test_credit_positive(self):
        """Net credit must be positive."""
        strat = _make_strategy()
        sigs = strat.generate_signals(_make_snapshot(vix=18.0))
        assert sigs[0].net_credit > 0

    def test_max_loss_correct(self):
        """max_loss = spread_width - credit."""
        strat = _make_strategy(spread_width=4.0)
        sigs = strat.generate_signals(_make_snapshot(vix=18.0))
        sig = sigs[0]
        assert abs(sig.max_loss - (4.0 - sig.net_credit)) < 1e-9

    def test_spread_width_matches(self):
        """Strike distance equals spread_width param."""
        strat = _make_strategy(spread_width=5.0)
        sigs = strat.generate_signals(_make_snapshot(vix=18.0))
        sig = sigs[0]
        strikes = sorted([leg.strike for leg in sig.legs])
        assert abs(strikes[1] - strikes[0] - 5.0) < 1e-9

    def test_min_credit_filter(self):
        """Spread with credit below min_credit → filtered out."""
        strat = _make_strategy(min_credit=999.0)
        sigs = strat.generate_signals(_make_snapshot(vix=18.0))
        assert sigs == []

    def test_strike_positions_bull_put(self):
        """Bull put: short strike > long strike."""
        strat = _make_strategy()
        snap = _make_snapshot(price=550.0, vix=18.0)
        sigs = strat.generate_signals(snap)
        sig = sigs[0]
        if sig.metadata["spread_type"] == "bull_put":
            short_s = sig.metadata["short_strike"]
            long_s = sig.metadata["long_strike"]
            assert short_s > long_s


# ---------------------------------------------------------------------------
# TestCondor0DTE
# ---------------------------------------------------------------------------

class TestCondor0DTE:
    """Iron condor 0DTE construction."""

    def _get_condor_signal(self):
        strat = _make_strategy(ic_vix_threshold=20.0)
        snap = _make_snapshot(price=550.0, vix=25.0, rsi=50.0)
        sigs = strat.generate_signals(snap)
        assert len(sigs) == 1
        return sigs[0]

    def test_four_legs(self):
        """Condor must have 4 legs."""
        sig = self._get_condor_signal()
        assert len(sig.legs) == 4

    def test_put_below_call(self):
        """Put short < call short."""
        sig = self._get_condor_signal()
        assert sig.metadata["put_short"] < sig.metadata["call_short"]

    def test_combined_credit(self):
        """Combined credit = put_credit + call_credit."""
        sig = self._get_condor_signal()
        expected = sig.metadata["put_credit"] + sig.metadata["call_credit"]
        assert abs(sig.net_credit - expected) < 1e-9

    def test_neutral_direction(self):
        sig = self._get_condor_signal()
        assert sig.direction == TradeDirection.NEUTRAL


# ---------------------------------------------------------------------------
# TestManagePosition
# ---------------------------------------------------------------------------

class TestManagePosition:
    """Position management: profit target, stop loss, expiry, gamma breach."""

    def _make_position(self, credit=1.0, spread_type="bull_put",
                       price=550.0, expiration=None, **meta_overrides):
        if expiration is None:
            expiration = datetime(2026, 3, 4, tzinfo=timezone.utc)
        short_strike = price - 2 if spread_type == "bull_put" else price + 2
        long_strike = short_strike - 4 if spread_type == "bull_put" else short_strike + 4
        short_leg = LegType.SHORT_PUT if spread_type == "bull_put" else LegType.SHORT_CALL
        long_leg = LegType.LONG_PUT if spread_type == "bull_put" else LegType.LONG_CALL
        meta = {"is_zero_dte": True, "spread_type": spread_type}
        meta.update(meta_overrides)
        return Position(
            id="test-pos-1",
            strategy_name="ZeroDTESpreadStrategy",
            ticker="SPY",
            direction=TradeDirection.SHORT,
            legs=[
                TradeLeg(short_leg, short_strike, expiration, entry_price=credit + 0.5),
                TradeLeg(long_leg, long_strike, expiration, entry_price=0.5),
            ],
            contracts=1,
            entry_date=expiration,
            net_credit=credit,
            max_loss_per_unit=4.0 - credit,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            metadata=meta,
        )

    def test_profit_target(self):
        """Close when profit >= credit * profit_target_pct."""
        strat = _make_strategy()
        expiration = datetime(2026, 3, 4, tzinfo=timezone.utc)
        pos = self._make_position(credit=2.0, expiration=expiration)
        # Large price move away from short strike → spread decays → profit
        snap = _make_snapshot(price=560.0, date=expiration)
        action = strat.manage_position(pos, snap)
        # With price far away from put short strike, spread value should be near zero → profit
        assert action == PositionAction.CLOSE_PROFIT

    def test_stop_loss(self):
        """Close when loss >= credit * stop_loss_pct."""
        strat = _make_strategy()
        expiration = datetime(2026, 3, 4, tzinfo=timezone.utc)
        pos = self._make_position(credit=1.0, spread_type="bull_put",
                                  price=550.0, expiration=expiration)
        # Price crashes through the put spread → large loss
        snap = _make_snapshot(price=530.0, date=expiration)
        action = strat.manage_position(pos, snap)
        assert action == PositionAction.CLOSE_STOP

    def test_expiry(self):
        """Close when date > expiration."""
        strat = _make_strategy()
        exp = datetime(2026, 3, 4, tzinfo=timezone.utc)
        pos = self._make_position(expiration=exp)
        snap = _make_snapshot(date=datetime(2026, 3, 5, tzinfo=timezone.utc))
        assert strat.manage_position(pos, snap) == PositionAction.CLOSE_EXPIRY

    def test_gamma_breach_put(self):
        """Price near put short strike → CLOSE_SIGNAL."""
        strat = _make_strategy(gamma_breach_buffer_pct=0.005)
        exp = datetime(2026, 3, 4, tzinfo=timezone.utc)
        pos = self._make_position(credit=1.0, price=550.0, expiration=exp)
        short_strike = pos.legs[0].strike  # put short at 548
        # Price right at the short strike
        snap = _make_snapshot(price=short_strike, date=exp)
        assert strat.manage_position(pos, snap) == PositionAction.CLOSE_SIGNAL

    def test_gamma_breach_call(self):
        """Price near call short strike → CLOSE_SIGNAL."""
        strat = _make_strategy(gamma_breach_buffer_pct=0.005)
        exp = datetime(2026, 3, 4, tzinfo=timezone.utc)
        pos = self._make_position(credit=1.0, spread_type="bear_call",
                                  price=550.0, expiration=exp)
        short_strike = pos.legs[0].strike  # call short at 552
        snap = _make_snapshot(price=short_strike, date=exp)
        assert strat.manage_position(pos, snap) == PositionAction.CLOSE_SIGNAL

    def test_hold(self):
        """No exit condition → HOLD."""
        strat = _make_strategy()
        # Use a few-day-out expiration so BS time value keeps the spread
        # from fully decaying (at 0DTE, any OTM spread decays to ~0 = profit target)
        today = datetime(2026, 3, 4, tzinfo=timezone.utc)
        exp = datetime(2026, 3, 7, tzinfo=timezone.utc)
        pos = self._make_position(credit=1.0, price=550.0, expiration=exp)
        # Price at 550 is 2pts above short_strike=548 — outside gamma breach
        # With 3 DTE, the spread has enough residual value to not hit profit target
        snap = _make_snapshot(price=550.0, date=today)
        action = strat.manage_position(pos, snap)
        assert action == PositionAction.HOLD


# ---------------------------------------------------------------------------
# TestSizePosition
# ---------------------------------------------------------------------------

class TestSizePosition:
    """Position sizing: basic, exposure cap, VIX reduction, heat cap."""

    def _make_signal(self, max_loss=3.0, vix_factor=1.0):
        return Signal(
            strategy_name="ZeroDTESpreadStrategy",
            ticker="SPY",
            direction=TradeDirection.SHORT,
            legs=[],
            net_credit=1.0,
            max_loss=max_loss,
            max_profit=1.0,
            profit_target_pct=0.50,
            stop_loss_pct=2.0,
            dte=0,
            metadata={"is_zero_dte": True, "vix_size_factor": vix_factor},
        )

    def _make_portfolio(self, equity=100_000, open_positions=None, total_risk=0):
        return PortfolioState(
            equity=equity,
            starting_capital=100_000,
            cash=equity,
            open_positions=open_positions or [],
            total_risk=total_risk,
        )

    def test_basic_sizing(self):
        """Standard sizing: contracts = equity * max_risk_pct / (max_loss * 100)."""
        strat = _make_strategy(max_risk_pct=0.02)
        sig = self._make_signal(max_loss=3.0)
        ps = self._make_portfolio(equity=100_000)
        contracts = strat.size_position(sig, ps)
        # 100000 * 0.02 / (3 * 100) = 6.66 → 6
        assert contracts == 6

    def test_zero_dte_exposure_cap(self):
        """0DTE exposure cap: no new contracts when cap reached."""
        strat = _make_strategy(max_zero_dte_exposure_pct=0.10)
        sig = self._make_signal()
        # Existing positions with enough 0DTE risk to hit 10% cap
        existing = Position(
            id="existing-1",
            strategy_name="ZeroDTESpreadStrategy",
            ticker="SPY",
            direction=TradeDirection.SHORT,
            legs=[],
            contracts=10,
            max_loss_per_unit=3.0,
            metadata={"is_zero_dte": True},
        )
        ps = self._make_portfolio(equity=100_000, open_positions=[existing])
        # existing risk: 3.0 * 10 * 100 = 3000, but we only need ≥ 10000
        existing.contracts = 40  # 3.0 * 40 * 100 = 12000 > 10000
        contracts = strat.size_position(sig, ps)
        assert contracts == 0

    def test_vix_reduction(self):
        """VIX size factor < 1 reduces contract count."""
        strat = _make_strategy(max_risk_pct=0.02)
        sig = self._make_signal(max_loss=3.0, vix_factor=0.5)
        ps = self._make_portfolio(equity=100_000)
        contracts = strat.size_position(sig, ps)
        # Base: 6, × 0.5 → 3
        assert contracts == 3

    def test_heat_cap(self):
        """Portfolio heat cap → 0 contracts."""
        strat = _make_strategy()
        sig = self._make_signal()
        ps = self._make_portfolio(equity=100_000, total_risk=50_000)
        ps.max_portfolio_risk_pct = 0.40
        contracts = strat.size_position(sig, ps)
        assert contracts == 0


# ---------------------------------------------------------------------------
# TestParamSpace
# ---------------------------------------------------------------------------

class TestParamSpace:
    """Parameter space completeness."""

    def test_all_params_present(self):
        """All expected params exist."""
        expected = {
            "ema_period", "otm_pct", "spread_width", "profit_target_pct",
            "stop_loss_multiplier", "min_credit", "min_vix", "max_vix_skip",
            "vix_reduce_threshold", "ic_vix_threshold", "rsi_min_ic",
            "rsi_max_ic", "gamma_breach_buffer_pct", "max_risk_pct",
            "max_zero_dte_exposure_pct", "max_gap_pct",
        }
        actual = {p.name for p in ZeroDTESpreadStrategy.get_param_space()}
        assert expected == actual

    def test_defaults_valid(self):
        """Default params produce a valid strategy object."""
        params = ZeroDTESpreadStrategy.get_default_params()
        strat = ZeroDTESpreadStrategy(params)
        assert strat.name == "ZeroDTESpreadStrategy"


# ---------------------------------------------------------------------------
# TestPaperTraderBypass
# ---------------------------------------------------------------------------

class TestPaperTraderBypass:
    """Paper trader management_dte bypass for 0DTE trades."""

    def _make_config(self):
        return {
            'risk': {
                'account_size': 100000,
                'max_risk_per_trade': 2.0,
                'max_positions': 5,
                'profit_target': 50,
                'stop_loss_multiplier': 2.5,
            },
            'alpaca': {'enabled': False},
        }

    @patch('paper_trader.init_db')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.DATA_DIR')
    def test_management_dte_bypassed_for_zero_dte(self, mock_dd, mock_gt, mock_idb, tmp_path):
        """0DTE trade with DTE=3 should NOT trigger management_dte exit."""
        from paper_trader import PaperTrader
        from pathlib import Path
        mock_dd.__truediv__ = lambda s, n: tmp_path / n
        mock_dd.mkdir = MagicMock()
        pt = PaperTrader(self._make_config())

        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 548, 'long_strike': 544,
            'expiration': (datetime.now(timezone.utc) + timedelta(days=0)).strftime('%Y-%m-%d'),
            'contracts': 1, 'credit': 0.50, 'total_credit': 0.50,
            'profit_target_pct': 0.5, 'stop_loss_pct': 2.0,
            'strategy_name': 'ZeroDTESpreadStrategy',
        }
        pnl, reason = pt._evaluate_position(trade, current_price=555, dte=3)
        # Should NOT be "management_dte" — the bypass skips that check
        assert reason != "management_dte"

    @patch('paper_trader.init_db')
    @patch('paper_trader.get_trades', return_value=[])
    @patch('paper_trader.DATA_DIR')
    def test_management_dte_still_fires_for_regular(self, mock_dd, mock_gt, mock_idb, tmp_path):
        """Regular trade with DTE=3 and profit > 0 still triggers management_dte."""
        from paper_trader import PaperTrader
        from pathlib import Path
        mock_dd.__truediv__ = lambda s, n: tmp_path / n
        mock_dd.mkdir = MagicMock()
        pt = PaperTrader(self._make_config())

        trade = {
            'ticker': 'SPY', 'type': 'bull_put_spread',
            'short_strike': 540, 'long_strike': 530,
            'expiration': (datetime.now(timezone.utc) + timedelta(days=20)).strftime('%Y-%m-%d'),
            'contracts': 1, 'credit': 2.0, 'total_credit': 2.0,
            'profit_target_pct': 0.5, 'stop_loss_pct': 2.5,
        }
        pnl, reason = pt._evaluate_position(trade, current_price=560, dte=3)
        # With price far above the put spread at DTE=3 with profit, management_dte should fire
        if pnl > 0:
            assert reason == "management_dte"
