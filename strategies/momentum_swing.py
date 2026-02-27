"""
Momentum swing strategy — equity or ITM debit spread momentum.

Uses EMA crossover, ADX filter, and RSI confirmation for trend-following.
Equity mode trades the underlying; debit spread mode uses ITM debit spreads.
"""

import logging
from typing import Any, Dict, List

import numpy as np

from strategies.base import (
    BaseStrategy, LegType, MarketSnapshot, ParamDef, PortfolioState,
    Position, PositionAction, Signal, TradeLeg, TradeDirection,
)
from strategies.pricing import (
    bs_price, nearest_friday_expiration, calculate_adx, calculate_rsi,
)
from shared.constants import DEFAULT_RISK_FREE_RATE

logger = logging.getLogger(__name__)


def _ema(values, period: int):
    """Exponential moving average."""
    if len(values) < period:
        return float(np.mean(values))
    multiplier = 2 / (period + 1)
    ema_val = float(np.mean(values[:period]))
    for v in values[period:]:
        ema_val = (float(v) - ema_val) * multiplier + ema_val
    return ema_val


class MomentumSwingStrategy(BaseStrategy):
    """Equity/ITM debit spread momentum following strong trends."""

    def generate_signals(self, market_data: MarketSnapshot) -> List[Signal]:
        signals = []

        for ticker, price in market_data.prices.items():
            if ticker.startswith("^"):
                continue

            df = market_data.price_data.get(ticker)
            if df is None or len(df) < 50:
                continue

            closes = df["Close"].values
            highs = df["High"].values
            lows = df["Low"].values

            ema_fast_period = self._p("ema_fast", 8)
            ema_slow_period = self._p("ema_slow", 21)

            ema_fast = _ema(closes, ema_fast_period)
            ema_slow = _ema(closes, ema_slow_period)

            # ADX filter
            min_adx = self._p("min_adx", 25.0)
            adx = calculate_adx(
                highs.tolist(), lows.tolist(), closes.tolist(),
                period=14,
            )
            if adx < min_adx:
                continue

            # RSI confirmation
            rsi = calculate_rsi(closes.tolist(), period=self._p("rsi_period", 14))

            # Breakout detection
            use_breakout = self._p("use_breakout", True)
            use_ema_cross = self._p("use_ema_cross", True)
            breakout_lookback = self._p("breakout_lookback", 20)

            iv = market_data.realized_vol.get(ticker, 0.20)

            # Bullish signal
            bullish = False
            if use_ema_cross and ema_fast > ema_slow and rsi > 50:
                bullish = True
            if use_breakout and len(closes) >= breakout_lookback:
                high_n = float(np.max(closes[-breakout_lookback:]))
                if price >= high_n:
                    bullish = True

            if bullish:
                sig = self._build_entry(
                    ticker, price, iv, market_data.date, "long",
                    adx=adx, rsi=rsi,
                )
                if sig:
                    signals.append(sig)

            # Bearish signal
            bearish = False
            if use_ema_cross and ema_fast < ema_slow and rsi < 50:
                bearish = True
            if use_breakout and len(closes) >= breakout_lookback:
                low_n = float(np.min(closes[-breakout_lookback:]))
                if price <= low_n:
                    bearish = True

            if bearish:
                sig = self._build_entry(
                    ticker, price, iv, market_data.date, "short",
                    adx=adx, rsi=rsi,
                )
                if sig:
                    signals.append(sig)

        return signals

    def _build_entry(
        self, ticker: str, price: float, iv: float,
        date, direction: str, adx: float = 0, rsi: float = 50,
    ) -> Signal | None:
        mode = self._p("mode", "equity")

        if mode == "equity":
            return self._build_equity(ticker, price, date, direction, adx, rsi)
        else:
            return self._build_itm_debit(ticker, price, iv, date, direction, adx, rsi)

    def _build_equity(
        self, ticker: str, price: float, date,
        direction: str, adx: float, rsi: float,
    ) -> Signal:
        if direction == "long":
            leg_type = LegType.LONG_STOCK
            trade_dir = TradeDirection.LONG
        else:
            leg_type = LegType.SHORT_STOCK
            trade_dir = TradeDirection.SHORT

        trailing_stop = self._p("trailing_stop_pct", 0.03)
        max_loss = price * trailing_stop

        legs = [TradeLeg(leg_type, 0.0, date, entry_price=price)]

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=trade_dir,
            legs=legs,
            net_credit=-price if direction == "long" else price,
            max_loss=max_loss,
            max_profit=price * self._p("profit_target_pct", 0.06),
            profit_target_pct=self._p("profit_target_pct", 0.06),
            stop_loss_pct=trailing_stop,
            score=50.0,
            signal_date=date,
            expiration=date,  # no expiration for equity
            dte=0,
            metadata={
                "mode": "equity",
                "direction": direction,
                "adx": adx,
                "rsi": rsi,
                "entry_price": price,
                "high_water_mark": price,
            },
        )

    def _build_itm_debit(
        self, ticker: str, price: float, iv: float,
        date, direction: str, adx: float, rsi: float,
    ) -> Signal | None:
        target_dte = 21
        spread_width = 10.0

        expiration = nearest_friday_expiration(date, target_dte, min_dte=10)
        dte = max((expiration - date).days, 1)
        T = dte / 365.0

        if direction == "long":
            # ITM bull call: long strike slightly ITM, short strike OTM
            long_strike = round(price - 2, 0)
            short_strike = long_strike + spread_width
            long_type = LegType.LONG_CALL
            short_type = LegType.SHORT_CALL
            opt_type = "C"
        else:
            # ITM bear put: long strike slightly ITM, short strike OTM
            long_strike = round(price + 2, 0)
            short_strike = long_strike - spread_width
            long_type = LegType.LONG_PUT
            short_type = LegType.SHORT_PUT
            opt_type = "P"

        long_price = bs_price(price, long_strike, T, DEFAULT_RISK_FREE_RATE, iv, opt_type)
        short_price = bs_price(price, short_strike, T, DEFAULT_RISK_FREE_RATE, iv, opt_type)

        debit = long_price - short_price
        if debit <= 0 or debit >= spread_width:
            return None

        legs = [
            TradeLeg(long_type, long_strike, expiration, entry_price=long_price),
            TradeLeg(short_type, short_strike, expiration, entry_price=short_price),
        ]

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=TradeDirection.LONG,
            legs=legs,
            net_credit=-debit,
            max_loss=debit,
            max_profit=spread_width - debit,
            profit_target_pct=self._p("profit_target_pct", 0.06),
            stop_loss_pct=self._p("trailing_stop_pct", 0.03),
            score=45.0,
            signal_date=date,
            expiration=expiration,
            dte=dte,
            metadata={
                "mode": "itm_debit_spread",
                "direction": direction,
                "adx": adx,
                "rsi": rsi,
            },
        )

    def manage_position(
        self, position: Position, market_data: MarketSnapshot,
    ) -> PositionAction:
        price = market_data.prices.get(position.ticker)
        if price is None:
            return PositionAction.HOLD

        mode = position.metadata.get("mode", "equity")
        direction = position.metadata.get("direction", "long")

        if mode == "equity":
            return self._manage_equity(position, price, market_data)
        else:
            return self._manage_debit(position, price, market_data)

    def _manage_equity(
        self, position: Position, price: float, market_data: MarketSnapshot,
    ) -> PositionAction:
        entry_price = position.metadata.get("entry_price", abs(position.net_credit))
        direction = position.metadata.get("direction", "long")
        trailing_stop = self._p("trailing_stop_pct", 0.03)
        max_hold = self._p("max_hold_days", 20)

        # Time stop
        if position.entry_date:
            days_held = (market_data.date - position.entry_date).days
            if days_held >= max_hold:
                return PositionAction.CLOSE_TIME

        # Profit target
        profit_target = self._p("profit_target_pct", 0.06)
        if direction == "long":
            pnl_pct = (price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - price) / entry_price

        if pnl_pct >= profit_target:
            return PositionAction.CLOSE_PROFIT

        # Trailing stop
        hwm = position.metadata.get("high_water_mark", entry_price)
        if direction == "long":
            hwm = max(hwm, price)
            drawdown = (hwm - price) / hwm
        else:
            hwm = min(hwm, price)
            drawdown = (price - hwm) / hwm if hwm > 0 else 0

        position.metadata["high_water_mark"] = hwm

        if drawdown >= trailing_stop:
            return PositionAction.CLOSE_STOP

        # EMA cross reversal
        df = market_data.price_data.get(position.ticker)
        if df is not None and len(df) >= 21:
            closes = df["Close"].values
            fast = _ema(closes, self._p("ema_fast", 8))
            slow = _ema(closes, self._p("ema_slow", 21))
            if direction == "long" and fast < slow:
                return PositionAction.CLOSE_SIGNAL
            if direction == "short" and fast > slow:
                return PositionAction.CLOSE_SIGNAL

        return PositionAction.HOLD

    def _manage_debit(
        self, position: Position, price: float, market_data: MarketSnapshot,
    ) -> PositionAction:
        if position.legs and market_data.date >= position.legs[0].expiration:
            return PositionAction.CLOSE_EXPIRY

        max_hold = self._p("max_hold_days", 20)
        if position.entry_date:
            days_held = (market_data.date - position.entry_date).days
            if days_held >= max_hold:
                return PositionAction.CLOSE_TIME

        from strategies.pricing import estimate_spread_value
        iv = market_data.realized_vol.get(position.ticker, 0.20)
        spread_value = estimate_spread_value(position, price, iv, market_data.date)

        entry_debit = abs(position.net_credit)
        if entry_debit <= 0:
            return PositionAction.HOLD

        profit = spread_value - entry_debit
        if profit >= entry_debit * position.profit_target_pct:
            return PositionAction.CLOSE_PROFIT

        loss = entry_debit - spread_value
        if loss >= entry_debit * position.stop_loss_pct:
            return PositionAction.CLOSE_STOP

        return PositionAction.HOLD

    def size_position(
        self, signal: Signal, portfolio_state: PortfolioState,
    ) -> int:
        max_risk_pct = self._p("max_risk_pct", 0.03)
        risk_budget = portfolio_state.equity * max_risk_pct

        mode = signal.metadata.get("mode", "equity")
        if mode == "equity":
            # Shares: risk_budget / (price * trailing_stop)
            entry_price = signal.metadata.get("entry_price", abs(signal.net_credit))
            trailing = self._p("trailing_stop_pct", 0.03)
            risk_per_share = entry_price * trailing
            if risk_per_share <= 0:
                return 0
            shares = int(risk_budget / risk_per_share)
            return max(1, min(shares, 100))
        else:
            cost_per_unit = abs(signal.net_credit) * 100
            if cost_per_unit <= 0:
                return 0
            return min(max(1, int(risk_budget / cost_per_unit)), 10)

    @classmethod
    def get_param_space(cls) -> List[ParamDef]:
        return [
            ParamDef("mode", "choice", "equity", choices=["equity", "itm_debit_spread"]),
            ParamDef("ema_fast", "int", 8, low=5, high=15, step=1),
            ParamDef("ema_slow", "int", 21, low=15, high=50, step=1),
            ParamDef("min_adx", "float", 25.0, low=15.0, high=35.0, step=2.0),
            ParamDef("rsi_period", "int", 14, low=7, high=21, step=1),
            ParamDef("breakout_lookback", "int", 20, low=10, high=50, step=5),
            ParamDef("trailing_stop_pct", "float", 0.03, low=0.01, high=0.08, step=0.005),
            ParamDef("max_hold_days", "int", 20, low=5, high=40, step=5),
            ParamDef("profit_target_pct", "float", 0.06, low=0.02, high=0.15, step=0.01),
            ParamDef("max_risk_pct", "float", 0.03, low=0.01, high=0.06, step=0.005),
            ParamDef("use_breakout", "bool", True),
            ParamDef("use_ema_cross", "bool", True),
        ]
