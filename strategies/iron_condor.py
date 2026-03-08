"""
Iron condor strategy — neutral, range-bound markets.

Sells both a bull put spread and bear call spread simultaneously.
Requires RSI in neutral zone and optionally elevated IV.
"""

import logging
from typing import Any, Dict, List

from strategies.base import (
    BaseStrategy, LegType, MarketSnapshot, ParamDef, PortfolioState,
    Position, PositionAction, Signal, TradeLeg, TradeDirection,
)
from strategies.pricing import (
    bs_price, estimate_spread_value, nearest_friday_expiration, calculate_rsi,
)
from shared.constants import DEFAULT_RISK_FREE_RATE

logger = logging.getLogger(__name__)


class IronCondorStrategy(BaseStrategy):
    """Iron condor: sell put spread + call spread in range-bound markets."""

    def generate_signals(self, market_data: MarketSnapshot) -> List[Signal]:
        signals = []
        weekday = market_data.date.weekday()
        if weekday not in (0, 1):  # Mon/Tue only
            return []

        for ticker, price in market_data.prices.items():
            if ticker.startswith("^"):
                continue

            df = market_data.price_data.get(ticker)
            if df is None or len(df) < 20:
                continue

            # RSI filter
            closes = df["Close"].tolist()
            rsi = calculate_rsi(closes)
            rsi_min = self._p("rsi_min", 30)
            rsi_max = self._p("rsi_max", 70)
            if not (rsi_min <= rsi <= rsi_max):
                continue

            # IV rank filter
            min_iv_rank = self._p("min_iv_rank", 30.0)
            iv_rank = market_data.iv_rank.get(ticker, 25.0)
            if iv_rank < min_iv_rank:
                continue

            sig = self._build_condor(ticker, price, market_data, rsi, iv_rank)
            if sig:
                signals.append(sig)

        return signals

    def _build_condor(
        self, ticker: str, price: float,
        market_data: MarketSnapshot, rsi: float, iv_rank: float,
    ) -> Signal | None:
        target_dte = self._p("target_dte", 35)
        min_dte = self._p("min_dte", 25)
        otm_pct_put = self._p("otm_pct_put", 0.05)
        otm_pct_call = self._p("otm_pct_call", 0.05)
        spread_width = self._p("spread_width", 10.0)
        min_combined_credit_pct = self._p("min_combined_credit_pct", 0.20)

        expiration = nearest_friday_expiration(market_data.date, target_dte, min_dte)
        dte = (expiration - market_data.date).days
        T = dte / 365.0
        iv = market_data.realized_vol.get(ticker, 0.20)

        # Put spread (bull put)
        put_short = round(price * (1 - otm_pct_put), 0)
        put_long = put_short - spread_width

        # Call spread (bear call)
        call_short = round(price * (1 + otm_pct_call), 0)
        call_long = call_short + spread_width

        if put_short >= call_short:
            return None

        # Price all legs
        put_short_price = bs_price(price, put_short, T, DEFAULT_RISK_FREE_RATE, iv, "P")
        put_long_price = bs_price(price, put_long, T, DEFAULT_RISK_FREE_RATE, iv, "P")
        call_short_price = bs_price(price, call_short, T, DEFAULT_RISK_FREE_RATE, iv, "C")
        call_long_price = bs_price(price, call_long, T, DEFAULT_RISK_FREE_RATE, iv, "C")

        put_credit = put_short_price - put_long_price
        call_credit = call_short_price - call_long_price
        combined_credit = put_credit + call_credit

        # Fallback heuristic
        if combined_credit < spread_width * 0.10:
            combined_credit = spread_width * 0.30

        combined_credit -= 0.10  # slippage for 4 legs

        if combined_credit < spread_width * min_combined_credit_pct:
            return None

        max_loss = spread_width - combined_credit
        if max_loss <= 0:
            return None

        legs = [
            TradeLeg(LegType.SHORT_PUT, put_short, expiration, entry_price=put_short_price),
            TradeLeg(LegType.LONG_PUT, put_long, expiration, entry_price=put_long_price),
            TradeLeg(LegType.SHORT_CALL, call_short, expiration, entry_price=call_short_price),
            TradeLeg(LegType.LONG_CALL, call_long, expiration, entry_price=call_long_price),
        ]

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=TradeDirection.NEUTRAL,
            legs=legs,
            net_credit=combined_credit,
            max_loss=max_loss,
            max_profit=combined_credit,
            profit_target_pct=self._p("profit_target_pct", 0.50),
            stop_loss_pct=self._p("stop_loss_multiplier", 2.0),
            score=55.0,
            signal_date=market_data.date,
            expiration=expiration,
            dte=dte,
            metadata={
                "rsi": rsi,
                "iv_rank": iv_rank,
                "put_credit": put_credit,
                "call_credit": call_credit,
                "put_short": put_short,
                "call_short": call_short,
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

        iv = market_data.realized_vol.get(position.ticker, 0.20)
        spread_value = estimate_spread_value(position, price, iv, market_data.date)
        cost_to_close = -spread_value
        credit = position.net_credit

        if credit - cost_to_close >= credit * position.profit_target_pct:
            return PositionAction.CLOSE_PROFIT

        if cost_to_close - credit >= credit * position.stop_loss_pct:
            return PositionAction.CLOSE_STOP

        return PositionAction.HOLD

    def size_position(
        self, signal: Signal, portfolio_state: PortfolioState,
    ) -> int:
        max_risk_pct = self._p("max_risk_pct", 0.02)
        risk_budget = portfolio_state.equity * max_risk_pct
        risk_per_unit = signal.max_loss * 100
        if risk_per_unit <= 0:
            return 0
        if portfolio_state.total_risk >= portfolio_state.equity * portfolio_state.max_portfolio_risk_pct:
            return 0
        return min(max(1, int(risk_budget / risk_per_unit)), 10)

    @classmethod
    def get_param_space(cls) -> List[ParamDef]:
        return [
            ParamDef("rsi_min", "int", 30, low=20, high=45, step=5),
            ParamDef("rsi_max", "int", 70, low=55, high=80, step=5),
            ParamDef("min_iv_rank", "float", 30.0, low=0.0, high=60.0, step=5.0),
            ParamDef("target_dte", "int", 35, low=21, high=60, step=5),
            ParamDef("min_dte", "int", 25, low=7, high=45, step=5),
            ParamDef("otm_pct_put", "float", 0.05, low=0.02, high=0.12, step=0.01),
            ParamDef("otm_pct_call", "float", 0.05, low=0.02, high=0.12, step=0.01),
            ParamDef("spread_width", "float", 10.0, low=2.0, high=15.0, step=1.0),
            ParamDef("min_combined_credit_pct", "float", 0.20, low=0.10, high=0.40, step=0.05),
            ParamDef("profit_target_pct", "float", 0.50, low=0.25, high=0.75, step=0.05),
            ParamDef("stop_loss_multiplier", "float", 2.0, low=1.0, high=3.5, step=0.25),
            ParamDef("max_risk_pct", "float", 0.02, low=0.005, high=0.04, step=0.005),
        ]
