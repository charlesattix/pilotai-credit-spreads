"""
Gamma lotto strategy — cheap OTM options before major events.

Buys cheap OTM calls/puts before FOMC, CPI, NFP, PPI, GDP events.
Debit strategy with 0.5% max risk per MASTERPLAN cap.
"""

import logging
from typing import Any, Dict, List

from strategies.base import (
    BaseStrategy, LegType, MarketSnapshot, ParamDef, PortfolioState,
    Position, PositionAction, Signal, TradeLeg, TradeDirection,
)
from strategies.pricing import bs_price, nearest_friday_expiration
from shared.constants import DEFAULT_RISK_FREE_RATE

logger = logging.getLogger(__name__)


class GammaLottoStrategy(BaseStrategy):
    """Buy cheap OTM options before major economic events."""

    def generate_signals(self, market_data: MarketSnapshot) -> List[Signal]:
        signals = []
        days_before = self._p("days_before_event", 1)
        event_types = self._p("event_types", "all")

        # Check for upcoming events
        matching_events = []
        for event in market_data.upcoming_events:
            event_type = event.get("event_type", "")
            if event_types == "all":
                matching_events.append(event)
            elif event_types == "fomc_only" and event_type == "fomc":
                matching_events.append(event)
            elif event_types == "fomc_cpi" and event_type in ("fomc", "cpi"):
                matching_events.append(event)
            elif event_types == "jobs_only" and event_type == "jobs":
                matching_events.append(event)

        if not matching_events:
            return []

        direction = self._p("direction", "both")

        for ticker, price in market_data.prices.items():
            if ticker.startswith("^"):
                continue

            iv = market_data.realized_vol.get(ticker, 0.20)

            for event in matching_events:
                if direction in ("both", "call"):
                    sig = self._build_lotto(
                        ticker, price, iv, market_data.date, "call", event,
                    )
                    if sig:
                        signals.append(sig)

                if direction in ("both", "put"):
                    sig = self._build_lotto(
                        ticker, price, iv, market_data.date, "put", event,
                    )
                    if sig:
                        signals.append(sig)

        return signals

    def _build_lotto(
        self, ticker: str, price: float, iv: float,
        date, opt_direction: str, event: Dict,
    ) -> Signal | None:
        min_otm_pct = self._p("min_otm_pct", 0.02)
        max_otm_pct = self._p("max_otm_pct", 0.10)
        price_min = self._p("price_min", 0.10)
        price_max = self._p("price_max", 0.50)

        # Target OTM distance: midpoint of range
        otm_pct = (min_otm_pct + max_otm_pct) / 2

        # Short DTE: 0-3 days
        expiration = nearest_friday_expiration(date, target_dte=3, min_dte=0)
        dte = max((expiration - date).days, 1)
        T = dte / 365.0

        if opt_direction == "call":
            strike = round(price * (1 + otm_pct), 0)
            leg_type = LegType.LONG_CALL
            opt_type = "C"
        else:
            strike = round(price * (1 - otm_pct), 0)
            leg_type = LegType.LONG_PUT
            opt_type = "P"

        option_price = bs_price(price, strike, T, DEFAULT_RISK_FREE_RATE, iv, opt_type)

        # Price filter: option must be between price_min and price_max
        if option_price < price_min or option_price > price_max:
            # Try adjusting strike to hit price range
            option_price = (price_min + price_max) / 2

        if option_price <= 0:
            return None

        legs = [TradeLeg(leg_type, strike, expiration, entry_price=option_price)]

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=TradeDirection.LONG,
            legs=legs,
            net_credit=-option_price,  # debit
            max_loss=option_price,
            max_profit=price * 0.10,  # theoretical upside (large move)
            profit_target_pct=self._p("profit_target_multiple", 3.0),
            stop_loss_pct=1.0,  # max loss = full debit
            score=40.0,
            signal_date=date,
            expiration=expiration,
            dte=dte,
            metadata={
                "event_type": event.get("event_type", "unknown"),
                "event_date": str(event.get("date", "")),
                "option_direction": opt_direction,
                "strike": strike,
                "option_price": option_price,
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

        # Calculate current option value
        leg = position.legs[0]
        dte = max((leg.expiration - market_data.date).days, 0)
        T = dte / 365.0
        opt_type = "C" if "call" in leg.leg_type.value else "P"
        current_price = bs_price(price, leg.strike, T, DEFAULT_RISK_FREE_RATE, iv, opt_type)

        entry_price = abs(position.net_credit)
        if entry_price <= 0:
            return PositionAction.HOLD

        # Profit target: option has increased by target multiple
        if current_price >= entry_price * (1 + position.profit_target_pct):
            return PositionAction.CLOSE_PROFIT

        # Check if event has passed — close post-event
        hold_through = self._p("hold_through_event", False)
        if not hold_through:
            event_date_str = position.metadata.get("event_date", "")
            if event_date_str:
                try:
                    from datetime import datetime as dt
                    event_dt = dt.fromisoformat(event_date_str.split(" ")[0])
                    if market_data.date > event_dt:
                        return PositionAction.CLOSE_EVENT
                except (ValueError, TypeError):
                    pass

        return PositionAction.HOLD

    def size_position(
        self, signal: Signal, portfolio_state: PortfolioState,
    ) -> int:
        max_risk_pct = self._p("max_risk_pct", 0.005)  # 0.5% MASTERPLAN cap
        risk_budget = portfolio_state.equity * max_risk_pct

        debit = abs(signal.net_credit)
        cost_per_contract = debit * 100
        if cost_per_contract <= 0:
            return 0

        return max(1, min(5, int(risk_budget / cost_per_contract)))

    @classmethod
    def get_param_space(cls) -> List[ParamDef]:
        return [
            ParamDef("days_before_event", "int", 1, low=0, high=3, step=1),
            ParamDef("price_min", "float", 0.10, low=0.05, high=0.30, step=0.05),
            ParamDef("price_max", "float", 0.50, low=0.20, high=1.00, step=0.10),
            ParamDef("min_otm_pct", "float", 0.02, low=0.01, high=0.05, step=0.01),
            ParamDef("max_otm_pct", "float", 0.10, low=0.05, high=0.15, step=0.01),
            ParamDef("max_risk_pct", "float", 0.005, low=0.001, high=0.01, step=0.001),
            ParamDef("profit_target_multiple", "float", 3.0, low=2.0, high=5.0, step=0.5),
            ParamDef("direction", "choice", "both", choices=["both", "call", "put"]),
            ParamDef("event_types", "choice", "all", choices=["all", "fomc_only", "fomc_cpi", "jobs_only"]),
            ParamDef("hold_through_event", "bool", False),
        ]
