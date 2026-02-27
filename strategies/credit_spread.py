"""
Credit spread strategy — bull puts and bear calls.

Ported from backtest/backtester.py heuristic mode. Uses MA trend filter,
momentum filter, and Black-Scholes pricing.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List

from strategies.base import (
    BaseStrategy, LegType, MarketSnapshot, ParamDef, PortfolioState,
    Position, PositionAction, Signal, TradeLeg, TradeDirection,
)
from strategies.pricing import (
    bs_price, estimate_spread_value, nearest_friday_expiration,
)
from shared.constants import DEFAULT_RISK_FREE_RATE

logger = logging.getLogger(__name__)


class CreditSpreadStrategy(BaseStrategy):
    """Bull put / bear call credit spreads with MA trend filter."""

    def generate_signals(self, market_data: MarketSnapshot) -> List[Signal]:
        signals = []
        weekday = market_data.date.weekday()
        scan_day = self._p("scan_weekday", "monday")

        if scan_day == "monday" and weekday != 0:
            return []
        if scan_day == "mon_wed_fri" and weekday not in (0, 2, 4):
            return []

        direction = self._p("direction", "both")

        for ticker, price in market_data.prices.items():
            if ticker.startswith("^"):
                continue

            df = market_data.price_data.get(ticker)
            if df is None or len(df) < 20:
                continue

            closes = df["Close"].values
            ma_period = self._p("trend_ma_period", 20)
            if len(closes) < ma_period:
                continue
            trend_ma = float(closes[-ma_period:].mean())

            # Momentum filter
            mom_filter = self._p("momentum_filter_pct", 5.0)
            lookback = min(10, len(closes) - 1)
            if lookback > 0:
                mom_pct = (price - float(closes[-lookback - 1])) / float(closes[-lookback - 1]) * 100
            else:
                mom_pct = 0.0

            iv = market_data.realized_vol.get(ticker, 0.20)

            if direction in ("both", "bull_put") and price >= trend_ma:
                if mom_pct >= -abs(mom_filter):
                    sig = self._build_spread(
                        ticker, price, iv, market_data.date, "bull_put",
                    )
                    if sig:
                        signals.append(sig)

            if direction in ("both", "bear_call") and price <= trend_ma:
                sig = self._build_spread(
                    ticker, price, iv, market_data.date, "bear_call",
                )
                if sig:
                    signals.append(sig)

        return signals

    def _build_spread(
        self, ticker: str, price: float, iv: float,
        date: datetime, spread_type: str,
    ) -> Signal | None:
        target_dte = self._p("target_dte", 35)
        min_dte = self._p("min_dte", 25)
        otm_pct = self._p("otm_pct", 0.05)
        spread_width = self._p("spread_width", 10.0)
        credit_fraction = self._p("credit_fraction", 0.35)
        slippage = 0.05

        expiration = nearest_friday_expiration(date, target_dte, min_dte)
        dte = (expiration - date).days
        T = dte / 365.0

        if spread_type == "bull_put":
            short_strike = round(price * (1 - otm_pct), 0)
            long_strike = short_strike - spread_width
            short_leg_type = LegType.SHORT_PUT
            long_leg_type = LegType.LONG_PUT
            opt_type = "P"
        else:
            short_strike = round(price * (1 + otm_pct), 0)
            long_strike = short_strike + spread_width
            short_leg_type = LegType.SHORT_CALL
            long_leg_type = LegType.LONG_CALL
            opt_type = "C"

        short_price = bs_price(price, short_strike, T, DEFAULT_RISK_FREE_RATE, iv, opt_type)
        long_price = bs_price(price, long_strike, T, DEFAULT_RISK_FREE_RATE, iv, opt_type)
        credit = short_price - long_price

        # Fallback: use heuristic credit if BS gives unreasonable result
        min_credit = spread_width * 0.10
        if credit < min_credit:
            credit = spread_width * credit_fraction

        credit -= slippage
        if credit <= 0:
            return None

        max_loss = spread_width - credit
        if max_loss <= 0:
            return None

        legs = [
            TradeLeg(short_leg_type, short_strike, expiration, entry_price=short_price),
            TradeLeg(long_leg_type, long_strike, expiration, entry_price=long_price),
        ]

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=TradeDirection.SHORT,
            legs=legs,
            net_credit=credit,
            max_loss=max_loss,
            max_profit=credit,
            profit_target_pct=self._p("profit_target_pct", 0.50),
            stop_loss_pct=self._p("stop_loss_multiplier", 2.5),
            score=50.0,
            signal_date=date,
            expiration=expiration,
            dte=dte,
            metadata={
                "spread_type": spread_type,
                "short_strike": short_strike,
                "long_strike": long_strike,
                "iv": iv,
            },
        )

    def manage_position(
        self, position: Position, market_data: MarketSnapshot,
    ) -> PositionAction:
        # Expiration check
        if position.legs and market_data.date >= position.legs[0].expiration:
            return PositionAction.CLOSE_EXPIRY

        ticker = position.ticker
        price = market_data.prices.get(ticker)
        if price is None:
            return PositionAction.HOLD

        iv = market_data.realized_vol.get(ticker, 0.20)
        spread_value = estimate_spread_value(position, price, iv, market_data.date)
        # For credit spreads, spread_value is negative (we're short).
        # Cost to close = -spread_value (what we'd pay to buy back)
        cost_to_close = -spread_value

        credit = position.net_credit

        # Profit target: spread has decayed enough
        profit_captured = credit - cost_to_close
        if profit_captured >= credit * position.profit_target_pct:
            return PositionAction.CLOSE_PROFIT

        # Stop loss: spread has moved against us
        loss = cost_to_close - credit
        if loss >= credit * position.stop_loss_pct:
            return PositionAction.CLOSE_STOP

        return PositionAction.HOLD

    def size_position(
        self, signal: Signal, portfolio_state: PortfolioState,
    ) -> int:
        max_risk_pct = self._p("max_risk_pct", 0.02)
        risk_budget = portfolio_state.equity * max_risk_pct

        risk_per_unit = signal.max_loss * 100  # per contract (100 shares)
        if risk_per_unit <= 0:
            return 0

        # Heat cap check
        if portfolio_state.total_risk >= portfolio_state.equity * portfolio_state.max_portfolio_risk_pct:
            return 0

        contracts = max(1, int(risk_budget / risk_per_unit))
        return min(contracts, 10)

    @classmethod
    def get_param_space(cls) -> List[ParamDef]:
        return [
            ParamDef("direction", "choice", "both", choices=["both", "bull_put", "bear_call"]),
            ParamDef("trend_ma_period", "int", 20, low=10, high=100, step=5),
            ParamDef("target_dte", "int", 35, low=14, high=60, step=5),
            ParamDef("min_dte", "int", 25, low=7, high=45, step=5),
            ParamDef("otm_pct", "float", 0.05, low=0.02, high=0.15, step=0.01),
            ParamDef("spread_width", "float", 10.0, low=2.0, high=20.0, step=1.0),
            ParamDef("credit_fraction", "float", 0.35, low=0.15, high=0.50, step=0.05),
            ParamDef("profit_target_pct", "float", 0.50, low=0.25, high=0.80, step=0.05),
            ParamDef("stop_loss_multiplier", "float", 2.5, low=1.5, high=4.0, step=0.25),
            ParamDef("momentum_filter_pct", "float", 5.0, low=2.0, high=10.0, step=1.0),
            ParamDef("scan_weekday", "choice", "monday", choices=["monday", "any", "mon_wed_fri"]),
            ParamDef("max_risk_pct", "float", 0.02, low=0.005, high=0.05, step=0.005),
        ]
