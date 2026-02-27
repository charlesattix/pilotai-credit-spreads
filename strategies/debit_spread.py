"""
Debit spread strategy — directional, trend-following.

Buy bull call debit spreads in uptrends, bear put debit spreads in downtrends.
Shorter DTE than credit spreads (needs directional move faster).
"""

import logging
from typing import Any, Dict, List

from strategies.base import (
    BaseStrategy, LegType, MarketSnapshot, ParamDef, PortfolioState,
    Position, PositionAction, Signal, TradeLeg, TradeDirection,
)
from strategies.pricing import bs_price, nearest_friday_expiration, estimate_spread_value
from shared.constants import DEFAULT_RISK_FREE_RATE

logger = logging.getLogger(__name__)


class DebitSpreadStrategy(BaseStrategy):
    """Directional debit spreads following momentum/trend."""

    def generate_signals(self, market_data: MarketSnapshot) -> List[Signal]:
        signals = []
        direction = self._p("direction", "trend_following")

        for ticker, price in market_data.prices.items():
            if ticker.startswith("^"):
                continue

            df = market_data.price_data.get(ticker)
            if df is None or len(df) < 30:
                continue

            closes = df["Close"].values
            ma_period = self._p("trend_ma_period", 20)
            if len(closes) < ma_period:
                continue

            trend_ma = float(closes[-ma_period:].mean())

            # Momentum filter
            lookback = self._p("momentum_lookback", 10)
            lookback = min(lookback, len(closes) - 1)
            if lookback <= 0:
                continue
            mom_pct = (price - float(closes[-lookback - 1])) / float(closes[-lookback - 1]) * 100
            min_mom = self._p("min_momentum_pct", 2.0)

            iv = market_data.realized_vol.get(ticker, 0.20)

            # Bull call debit spread
            if direction in ("trend_following", "bull_only"):
                if price > trend_ma and mom_pct >= min_mom:
                    sig = self._build_debit(
                        ticker, price, iv, market_data.date, "bull_call",
                    )
                    if sig:
                        signals.append(sig)

            # Bear put debit spread
            if direction in ("trend_following", "bear_only"):
                if price < trend_ma and mom_pct <= -min_mom:
                    sig = self._build_debit(
                        ticker, price, iv, market_data.date, "bear_put",
                    )
                    if sig:
                        signals.append(sig)

        return signals

    def _build_debit(
        self, ticker: str, price: float, iv: float,
        date, spread_type: str,
    ) -> Signal | None:
        target_dte = self._p("target_dte", 14)
        spread_width = self._p("spread_width", 5.0)

        expiration = nearest_friday_expiration(date, target_dte, min_dte=5)
        dte = max((expiration - date).days, 1)
        T = dte / 365.0

        if spread_type == "bull_call":
            # Buy near-ATM call, sell OTM call
            long_strike = round(price, 0)  # ATM
            short_strike = long_strike + spread_width
            long_type = LegType.LONG_CALL
            short_type = LegType.SHORT_CALL
            opt_type = "C"
            trade_dir = TradeDirection.LONG
        else:
            # Buy near-ATM put, sell OTM put
            long_strike = round(price, 0)  # ATM
            short_strike = long_strike - spread_width
            long_type = LegType.LONG_PUT
            short_type = LegType.SHORT_PUT
            opt_type = "P"
            trade_dir = TradeDirection.LONG

        long_price = bs_price(price, long_strike, T, DEFAULT_RISK_FREE_RATE, iv, opt_type)
        short_price = bs_price(price, short_strike, T, DEFAULT_RISK_FREE_RATE, iv, opt_type)

        debit = long_price - short_price
        if debit <= 0 or debit >= spread_width:
            return None

        max_profit = spread_width - debit
        if max_profit <= 0:
            return None

        legs = [
            TradeLeg(long_type, long_strike, expiration, entry_price=long_price),
            TradeLeg(short_type, short_strike, expiration, entry_price=short_price),
        ]

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=trade_dir,
            legs=legs,
            net_credit=-debit,
            max_loss=debit,
            max_profit=max_profit,
            profit_target_pct=self._p("profit_target_pct", 1.0),
            stop_loss_pct=self._p("stop_loss_pct", 0.50),
            score=45.0,
            signal_date=date,
            expiration=expiration,
            dte=dte,
            metadata={
                "spread_type": spread_type,
                "long_strike": long_strike,
                "short_strike": short_strike,
                "debit": debit,
            },
        )

    def manage_position(
        self, position: Position, market_data: MarketSnapshot,
    ) -> PositionAction:
        if position.legs and market_data.date >= position.legs[0].expiration:
            return PositionAction.CLOSE_EXPIRY

        price = market_data.prices.get(position.ticker)
        if price is None:
            return PositionAction.HOLD

        # Time-based exit
        min_dte_exit = self._p("min_dte_exit", 3)
        if position.legs:
            remaining_dte = (position.legs[0].expiration - market_data.date).days
            if remaining_dte <= min_dte_exit:
                return PositionAction.CLOSE_TIME

        iv = market_data.realized_vol.get(position.ticker, 0.20)
        spread_value = estimate_spread_value(position, price, iv, market_data.date)

        entry_debit = abs(position.net_credit)
        if entry_debit <= 0:
            return PositionAction.HOLD

        # For debit spreads, spread_value is positive (we own the legs)
        profit = spread_value - entry_debit
        if profit >= entry_debit * position.profit_target_pct:
            return PositionAction.CLOSE_PROFIT

        loss = entry_debit - spread_value
        if loss >= entry_debit * position.stop_loss_pct:
            return PositionAction.CLOSE_STOP

        # Trend reversal exit
        df = market_data.price_data.get(position.ticker)
        if df is not None and len(df) >= 20:
            ma = float(df["Close"].values[-20:].mean())
            spread_type = position.metadata.get("spread_type", "")
            if spread_type == "bull_call" and price < ma:
                return PositionAction.CLOSE_SIGNAL
            if spread_type == "bear_put" and price > ma:
                return PositionAction.CLOSE_SIGNAL

        return PositionAction.HOLD

    def size_position(
        self, signal: Signal, portfolio_state: PortfolioState,
    ) -> int:
        max_risk_pct = self._p("max_risk_pct", 0.02)
        risk_budget = portfolio_state.equity * max_risk_pct
        cost_per_unit = abs(signal.net_credit) * 100
        if cost_per_unit <= 0:
            return 0
        if portfolio_state.total_risk >= portfolio_state.equity * portfolio_state.max_portfolio_risk_pct:
            return 0
        return min(max(1, int(risk_budget / cost_per_unit)), 10)

    @classmethod
    def get_param_space(cls) -> List[ParamDef]:
        return [
            ParamDef("direction", "choice", "trend_following",
                     choices=["trend_following", "bull_only", "bear_only"]),
            ParamDef("trend_ma_period", "int", 20, low=8, high=50, step=2),
            ParamDef("momentum_lookback", "int", 10, low=5, high=20, step=1),
            ParamDef("min_momentum_pct", "float", 2.0, low=0.5, high=5.0, step=0.5),
            ParamDef("target_dte", "int", 14, low=7, high=30, step=1),
            ParamDef("spread_width", "float", 5.0, low=2.0, high=15.0, step=1.0),
            ParamDef("profit_target_pct", "float", 1.0, low=0.50, high=2.0, step=0.10),
            ParamDef("stop_loss_pct", "float", 0.50, low=0.25, high=0.75, step=0.05),
            ParamDef("min_dte_exit", "int", 3, low=1, high=7, step=1),
            ParamDef("max_risk_pct", "float", 0.02, low=0.005, high=0.04, step=0.005),
        ]
