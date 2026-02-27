"""
Calendar spread strategy — time decay across expirations.

Buy far-dated option, sell near-dated option at the same strike.
Profits from the faster time decay of the near-dated leg.
Prefers low-volatility environments.
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


class CalendarSpreadStrategy(BaseStrategy):
    """Calendar spread: sell front-month, buy back-month at same strike."""

    def generate_signals(self, market_data: MarketSnapshot) -> List[Signal]:
        signals = []

        for ticker, price in market_data.prices.items():
            if ticker.startswith("^"):
                continue

            # IV rank filter: prefer low vol (calendar spreads lose in vol spikes)
            max_iv_rank = self._p("max_iv_rank", 40.0)
            iv_rank = market_data.iv_rank.get(ticker, 25.0)
            if iv_rank > max_iv_rank:
                continue

            # Only enter once per week (Monday)
            if market_data.date.weekday() != 0:
                continue

            iv = market_data.realized_vol.get(ticker, 0.20)

            sig = self._build_calendar(ticker, price, iv, market_data.date)
            if sig:
                signals.append(sig)

        return signals

    def _build_calendar(
        self, ticker: str, price: float, iv: float, date,
    ) -> Signal | None:
        front_dte = self._p("front_dte", 7)
        back_dte = self._p("back_dte", 35)
        strike_selection = self._p("strike_selection", "atm")
        otm_offset = self._p("otm_offset_pct", 0.02)
        option_type = self._p("option_type", "put")

        front_exp = nearest_friday_expiration(date, front_dte, min_dte=3)
        back_exp = nearest_friday_expiration(date, back_dte, min_dte=front_dte + 7)

        front_days = max((front_exp - date).days, 1)
        back_days = max((back_exp - date).days, 1)

        # Must have meaningful time separation
        if back_days - front_days < 14:
            return None

        T_front = front_days / 365.0
        T_back = back_days / 365.0

        # Strike selection
        if strike_selection == "atm":
            strike = round(price, 0)
        else:
            if option_type == "put":
                strike = round(price * (1 - otm_offset), 0)
            else:
                strike = round(price * (1 + otm_offset), 0)

        opt = option_type[0].upper()

        front_price = bs_price(price, strike, T_front, DEFAULT_RISK_FREE_RATE, iv, opt)
        back_price = bs_price(price, strike, T_back, DEFAULT_RISK_FREE_RATE, iv, opt)

        # Debit = back leg cost - front leg credit
        debit = back_price - front_price
        if debit <= 0:
            return None

        # Max loss ≈ debit paid (spread can't go below zero in worst case)
        max_loss = debit
        # Max profit ≈ when front expires worthless and back retains value
        max_profit = back_price * 0.30  # approximate, depends on movement

        if option_type == "put":
            front_leg_type = LegType.SHORT_PUT
            back_leg_type = LegType.LONG_PUT
        else:
            front_leg_type = LegType.SHORT_CALL
            back_leg_type = LegType.LONG_CALL

        legs = [
            TradeLeg(front_leg_type, strike, front_exp, entry_price=front_price),
            TradeLeg(back_leg_type, strike, back_exp, entry_price=back_price),
        ]

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=TradeDirection.NEUTRAL,
            legs=legs,
            net_credit=-debit,
            max_loss=max_loss,
            max_profit=max_profit,
            profit_target_pct=self._p("profit_target_pct", 0.30),
            stop_loss_pct=self._p("stop_loss_pct", 0.40),
            score=35.0,
            signal_date=date,
            expiration=front_exp,
            dte=front_days,
            metadata={
                "strike": strike,
                "front_exp": str(front_exp.date()),
                "back_exp": str(back_exp.date()),
                "front_price": front_price,
                "back_price": back_price,
                "debit": debit,
            },
        )

    def manage_position(
        self, position: Position, market_data: MarketSnapshot,
    ) -> PositionAction:
        price = market_data.prices.get(position.ticker)
        if price is None:
            return PositionAction.HOLD

        iv = market_data.realized_vol.get(position.ticker, 0.20)

        # Close when front month expires — use CLOSE_SIGNAL (not CLOSE_EXPIRY)
        # so the backtester values the back leg via BS instead of intrinsic-only.
        front_leg = position.legs[0] if position.legs else None
        if front_leg and market_data.date >= front_leg.expiration:
            return PositionAction.CLOSE_SIGNAL

        # Also close if the back leg expires
        back_leg = position.legs[1] if len(position.legs) > 1 else None
        if back_leg and market_data.date >= back_leg.expiration:
            return PositionAction.CLOSE_EXPIRY

        spread_value = estimate_spread_value(position, price, iv, market_data.date)

        entry_debit = abs(position.net_credit)
        if entry_debit <= 0:
            return PositionAction.HOLD

        # Profit: calendar has widened
        profit = spread_value - entry_debit
        if profit >= entry_debit * position.profit_target_pct:
            return PositionAction.CLOSE_PROFIT

        # Stop: calendar has narrowed
        loss = entry_debit - spread_value
        if loss >= entry_debit * position.stop_loss_pct:
            return PositionAction.CLOSE_STOP

        # Vol spike exit: calendar spreads lose when vol rises sharply
        if market_data.vix > 35:
            return PositionAction.CLOSE_SIGNAL

        return PositionAction.HOLD

    def size_position(
        self, signal: Signal, portfolio_state: PortfolioState,
    ) -> int:
        max_risk_pct = self._p("max_risk_pct", 0.015)
        risk_budget = portfolio_state.equity * max_risk_pct
        cost_per_unit = abs(signal.net_credit) * 100
        if cost_per_unit <= 0:
            return 0
        if portfolio_state.total_risk >= portfolio_state.equity * portfolio_state.max_portfolio_risk_pct:
            return 0
        return min(max(1, int(risk_budget / cost_per_unit)), 5)

    @classmethod
    def get_param_space(cls) -> List[ParamDef]:
        return [
            ParamDef("front_dte", "int", 7, low=3, high=14, step=1),
            ParamDef("back_dte", "int", 35, low=21, high=60, step=5),
            ParamDef("strike_selection", "choice", "atm", choices=["atm", "slightly_otm"]),
            ParamDef("otm_offset_pct", "float", 0.02, low=0.0, high=0.05, step=0.01),
            ParamDef("option_type", "choice", "put", choices=["put", "call"]),
            ParamDef("max_iv_rank", "float", 40.0, low=15.0, high=60.0, step=5.0),
            ParamDef("profit_target_pct", "float", 0.30, low=0.15, high=0.60, step=0.05),
            ParamDef("stop_loss_pct", "float", 0.40, low=0.20, high=0.60, step=0.05),
            ParamDef("max_risk_pct", "float", 0.015, low=0.005, high=0.03, step=0.005),
        ]
