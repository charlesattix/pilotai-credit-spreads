"""
Straddle/strangle strategy — long vol before events, short vol after.

Long mode: buy ATM/NTM call + put before major events.
Short mode: sell call + put after events to capture IV crush.
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


class StraddleStrangleStrategy(BaseStrategy):
    """Long or short vol around economic events."""

    def generate_signals(self, market_data: MarketSnapshot) -> List[Signal]:
        signals = []
        mode = self._p("mode", "long_pre_event")
        event_types = self._p("event_types", "all")

        def _filter_events(events):
            filtered = []
            for event in events:
                et = event.get("event_type", "")
                if event_types == "all":
                    filtered.append(event)
                elif event_types == "fomc_only" and et == "fomc":
                    filtered.append(event)
                elif event_types == "fomc_cpi" and et in ("fomc", "cpi"):
                    filtered.append(event)
            return filtered

        upcoming = _filter_events(market_data.upcoming_events)
        recent = _filter_events(getattr(market_data, "recent_events", []))

        if not upcoming and not recent:
            return []

        for ticker, price in market_data.prices.items():
            if ticker.startswith("^"):
                continue

            iv = market_data.realized_vol.get(ticker, 0.20)

            # Long pre-event: use upcoming events
            if mode in ("long_pre_event", "both"):
                for event in upcoming:
                    sig = self._build_long(ticker, price, iv, market_data.date, event)
                    if sig:
                        signals.append(sig)

            # Short post-event: use recent (just-passed) events
            if mode in ("short_post_event", "both"):
                for event in recent:
                    sig = self._build_short(ticker, price, iv, market_data.date, event)
                    if sig:
                        signals.append(sig)

        return signals

    def _build_long(
        self, ticker: str, price: float, iv: float,
        date, event: Dict,
    ) -> Signal | None:
        """Buy straddle/strangle before event."""
        target_dte = self._p("target_dte", 7)
        otm_pct = self._p("otm_pct", 0.0)
        event_iv_boost = self._p("event_iv_boost", 0.30)

        expiration = nearest_friday_expiration(date, target_dte, min_dte=2)
        dte = max((expiration - date).days, 1)
        T = dte / 365.0

        # Boost IV for pre-event pricing
        boosted_iv = iv * (1 + event_iv_boost)

        call_strike = round(price * (1 + otm_pct), 0)
        put_strike = round(price * (1 - otm_pct), 0)

        call_price = bs_price(price, call_strike, T, DEFAULT_RISK_FREE_RATE, boosted_iv, "C")
        put_price = bs_price(price, put_strike, T, DEFAULT_RISK_FREE_RATE, boosted_iv, "P")

        total_debit = call_price + put_price
        if total_debit <= 0:
            return None

        legs = [
            TradeLeg(LegType.LONG_CALL, call_strike, expiration, entry_price=call_price),
            TradeLeg(LegType.LONG_PUT, put_strike, expiration, entry_price=put_price),
        ]

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=TradeDirection.LONG,
            legs=legs,
            net_credit=-total_debit,
            max_loss=total_debit,
            max_profit=price * 0.15,  # theoretical large move upside
            profit_target_pct=self._p("profit_target_pct", 0.50),
            stop_loss_pct=self._p("stop_loss_pct", 0.50),
            score=45.0,
            signal_date=date,
            expiration=expiration,
            dte=dte,
            metadata={
                "trade_type": "long_straddle" if otm_pct == 0 else "long_strangle",
                "event_type": event.get("event_type", ""),
                "event_date": str(event.get("date", "")),
            },
        )

    def _build_short(
        self, ticker: str, price: float, iv: float,
        date, event: Dict,
    ) -> Signal | None:
        """Sell straddle/strangle after event (IV crush).

        Called with events from recent_events (already occurred), so no
        future-date guard is needed.
        """
        target_dte = self._p("target_dte", 7)
        otm_pct = self._p("otm_pct", 0.0)
        iv_crush_pct = self._p("iv_crush_pct", 0.40)

        expiration = nearest_friday_expiration(date, target_dte, min_dte=2)
        dte = max((expiration - date).days, 1)
        T = dte / 365.0

        # Deflate IV for post-event (what we expect to capture)
        crushed_iv = iv * (1 - iv_crush_pct)

        call_strike = round(price * (1 + otm_pct), 0)
        put_strike = round(price * (1 - otm_pct), 0)

        call_price = bs_price(price, call_strike, T, DEFAULT_RISK_FREE_RATE, iv, "C")
        put_price = bs_price(price, put_strike, T, DEFAULT_RISK_FREE_RATE, iv, "P")

        total_credit = call_price + put_price
        if total_credit <= 0.10:
            return None

        # Max loss is theoretically unlimited for short straddle; cap at 2x credit
        max_loss = total_credit * 3.0

        legs = [
            TradeLeg(LegType.SHORT_CALL, call_strike, expiration, entry_price=call_price),
            TradeLeg(LegType.SHORT_PUT, put_strike, expiration, entry_price=put_price),
        ]

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=TradeDirection.SHORT,
            legs=legs,
            net_credit=total_credit,
            max_loss=max_loss,
            max_profit=total_credit,
            profit_target_pct=self._p("profit_target_pct", 0.50),
            stop_loss_pct=self._p("stop_loss_pct", 0.50),
            score=40.0,
            signal_date=date,
            expiration=expiration,
            dte=dte,
            metadata={
                "trade_type": "short_straddle" if otm_pct == 0 else "short_strangle",
                "event_type": event.get("event_type", ""),
                "iv_at_entry": iv,
                "expected_crushed_iv": crushed_iv,
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

        is_long = position.direction == TradeDirection.LONG
        entry_cost = abs(position.net_credit)

        if is_long:
            # Long: value of our options
            current_value = spread_value
            profit = current_value - entry_cost
            if profit >= entry_cost * position.profit_target_pct:
                return PositionAction.CLOSE_PROFIT
            if entry_cost - current_value >= entry_cost * position.stop_loss_pct:
                return PositionAction.CLOSE_STOP
        else:
            # Short: cost to buy back
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
        return min(max(1, int(risk_budget / risk_per_unit)), 5)

    @classmethod
    def get_param_space(cls) -> List[ParamDef]:
        return [
            ParamDef("mode", "choice", "long_pre_event",
                     choices=["long_pre_event", "short_post_event", "both"]),
            ParamDef("days_before_event", "int", 2, low=1, high=5, step=1),
            ParamDef("target_dte", "int", 7, low=2, high=14, step=1),
            ParamDef("otm_pct", "float", 0.0, low=0.0, high=0.05, step=0.01),
            ParamDef("event_iv_boost", "float", 0.30, low=0.10, high=0.60, step=0.05),
            ParamDef("iv_crush_pct", "float", 0.40, low=0.20, high=0.60, step=0.05),
            ParamDef("profit_target_pct", "float", 0.50, low=0.25, high=1.00, step=0.05),
            ParamDef("stop_loss_pct", "float", 0.50, low=0.25, high=0.75, step=0.05),
            ParamDef("max_risk_pct", "float", 0.02, low=0.005, high=0.04, step=0.005),
            ParamDef("event_types", "choice", "all", choices=["all", "fomc_only", "fomc_cpi"]),
        ]
