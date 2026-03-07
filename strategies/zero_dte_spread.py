"""
Zero-DTE credit spread strategy — intraday SPY/QQQ credit spreads.

Sells same-day expiration credit spreads (bull put / bear call) or iron
condors, targeting 50% profit capture before close.  Uses 20-EMA trend
filter, VIX regime gating, gap filter, and gamma-breach exit.

Design notes:
- expiration = market_data.date (same-day, SPY/QQQ have daily expirations)
- T = 6h remaining for BS pricing (morning entry assumption)
- Iron condor mode activates when VIX > 20 AND RSI in neutral zone
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from strategies.base import (
    BaseStrategy, LegType, MarketSnapshot, ParamDef, PortfolioState,
    Position, PositionAction, Signal, TradeLeg, TradeDirection,
)
from strategies.pricing import (
    bs_price, calculate_rsi, estimate_spread_value, get_fill_price,
    skew_adjusted_iv,
)
from shared.constants import DEFAULT_RISK_FREE_RATE, ZERO_DTE_TICKERS

logger = logging.getLogger(__name__)

# 6 hours remaining at open — expressed in years for BS pricing
# 6 / (365 * 6.5) ≈ 0.00253
_ZERO_DTE_T = 6.0 / (365.0 * 6.5)


class ZeroDTESpreadStrategy(BaseStrategy):
    """Intraday 0DTE credit spreads on SPY/QQQ."""

    # ------------------------------------------------------------------
    # generate_signals
    # ------------------------------------------------------------------

    def generate_signals(self, market_data: MarketSnapshot) -> List[Signal]:
        signals: List[Signal] = []

        # Skip weekends
        if market_data.date.weekday() >= 5:
            return signals

        # Skip event days (FOMC / CPI)
        if self._is_event_day(market_data):
            return signals

        # VIX gate
        vix = market_data.vix
        min_vix = self._p("min_vix", 12.0)
        max_vix_skip = self._p("max_vix_skip", 45.0)
        if vix < min_vix or vix > max_vix_skip:
            return signals

        ema_period = self._p("ema_period", 20)
        max_gap_pct = self._p("max_gap_pct", 0.01)
        ic_vix_threshold = self._p("ic_vix_threshold", 20.0)
        rsi_min_ic = self._p("rsi_min_ic", 40)
        rsi_max_ic = self._p("rsi_max_ic", 60)

        # VIX size factor stored in metadata for size_position
        vix_reduce_threshold = self._p("vix_reduce_threshold", 30.0)
        vix_size_factor = 0.5 if vix > vix_reduce_threshold else 1.0

        for ticker in ZERO_DTE_TICKERS:
            price = market_data.prices.get(ticker)
            if price is None:
                continue

            df = market_data.price_data.get(ticker)
            if df is None or len(df) < ema_period:
                continue

            closes = df["Close"].values

            # Gap filter
            open_price = market_data.open_prices.get(ticker)
            if open_price is not None and len(closes) >= 2:
                prior_close = float(closes[-2])
                if prior_close > 0:
                    gap_pct = abs(open_price - prior_close) / prior_close
                    if gap_pct > max_gap_pct:
                        continue

            # 20-EMA
            ema_vals = closes[-ema_period:]
            # Exponential weights
            alpha = 2.0 / (ema_period + 1)
            ema = float(ema_vals[0])
            for v in ema_vals[1:]:
                ema = alpha * float(v) + (1 - alpha) * ema

            iv = market_data.realized_vol.get(ticker, 0.20)
            rfr = market_data.risk_free_rate

            # RSI for condor mode
            rsi = market_data.rsi.get(ticker)
            if rsi is None:
                rsi = calculate_rsi(closes.tolist()) if len(closes) > 14 else 50.0

            # Mode selection
            if vix > ic_vix_threshold and rsi_min_ic <= rsi <= rsi_max_ic:
                # Iron condor in range-bound, elevated-VIX
                sig = self._build_condor_0dte(
                    ticker, price, iv, market_data.date,
                    vix=vix, rfr=rfr, vix_size_factor=vix_size_factor,
                )
            elif price > ema:
                # Uptrend — bull put
                sig = self._build_spread_0dte(
                    ticker, price, iv, market_data.date, "bull_put",
                    vix=vix, rfr=rfr, vix_size_factor=vix_size_factor,
                )
            else:
                # Downtrend — bear call
                sig = self._build_spread_0dte(
                    ticker, price, iv, market_data.date, "bear_call",
                    vix=vix, rfr=rfr, vix_size_factor=vix_size_factor,
                )

            if sig:
                signals.append(sig)

        return signals

    # ------------------------------------------------------------------
    # _build_spread_0dte  (bull put or bear call)
    # ------------------------------------------------------------------

    def _build_spread_0dte(
        self,
        ticker: str,
        price: float,
        iv: float,
        date: datetime,
        spread_type: str,
        vix: float = 20.0,
        rfr: float = DEFAULT_RISK_FREE_RATE,
        vix_size_factor: float = 1.0,
    ) -> Optional[Signal]:
        otm_pct = self._p("otm_pct", 0.004)
        spread_width = self._p("spread_width", 4.0)
        min_credit = self._p("min_credit", 0.15)

        expiration = date  # same-day
        T = _ZERO_DTE_T

        if spread_type == "bull_put":
            short_strike = round(price * (1 - otm_pct), 0)
            long_strike = short_strike - spread_width
            short_leg_type = LegType.SHORT_PUT
            long_leg_type = LegType.LONG_PUT
            opt_type = "P"
            direction = TradeDirection.SHORT
        else:
            short_strike = round(price * (1 + otm_pct), 0)
            long_strike = short_strike + spread_width
            short_leg_type = LegType.SHORT_CALL
            long_leg_type = LegType.LONG_CALL
            opt_type = "C"
            direction = TradeDirection.SHORT

        short_iv = skew_adjusted_iv(iv, price, short_strike, opt_type)
        long_iv = skew_adjusted_iv(iv, price, long_strike, opt_type)
        short_mid = bs_price(price, short_strike, T, rfr, short_iv, opt_type)
        long_mid = bs_price(price, long_strike, T, rfr, long_iv, opt_type)

        short_fill = get_fill_price(short_mid, price, short_strike, T, short_iv, "sell", vix=vix)
        long_fill = get_fill_price(long_mid, price, long_strike, T, long_iv, "buy", vix=vix)
        credit = short_fill - long_fill

        if credit < min_credit:
            return None

        max_loss = spread_width - credit
        if max_loss <= 0:
            return None

        legs = [
            TradeLeg(short_leg_type, short_strike, expiration, entry_price=short_fill),
            TradeLeg(long_leg_type, long_strike, expiration, entry_price=long_fill),
        ]

        raw_sl = self._p("stop_loss_multiplier", 2.0)
        max_sl = max_loss / credit if credit > 0 else raw_sl
        capped_sl = min(raw_sl, max_sl)

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=direction,
            legs=legs,
            net_credit=credit,
            max_loss=max_loss,
            max_profit=credit,
            profit_target_pct=self._p("profit_target_pct", 0.50),
            stop_loss_pct=capped_sl,
            score=60.0,
            signal_date=date,
            expiration=expiration,
            dte=0,
            metadata={
                "is_zero_dte": True,
                "spread_type": spread_type,
                "short_strike": short_strike,
                "long_strike": long_strike,
                "vix_size_factor": vix_size_factor,
            },
        )

    # ------------------------------------------------------------------
    # _build_condor_0dte  (iron condor)
    # ------------------------------------------------------------------

    def _build_condor_0dte(
        self,
        ticker: str,
        price: float,
        iv: float,
        date: datetime,
        vix: float = 20.0,
        rfr: float = DEFAULT_RISK_FREE_RATE,
        vix_size_factor: float = 1.0,
    ) -> Optional[Signal]:
        otm_pct = self._p("otm_pct", 0.004)
        spread_width = self._p("spread_width", 4.0)
        min_credit = self._p("min_credit", 0.15)

        expiration = date
        T = _ZERO_DTE_T

        # Put side
        put_short = round(price * (1 - otm_pct), 0)
        put_long = put_short - spread_width

        # Call side
        call_short = round(price * (1 + otm_pct), 0)
        call_long = call_short + spread_width

        # Sanity: put short must be below call short
        if put_short >= call_short:
            return None

        # Price all legs
        ps_iv = skew_adjusted_iv(iv, price, put_short, "P")
        pl_iv = skew_adjusted_iv(iv, price, put_long, "P")
        cs_iv = skew_adjusted_iv(iv, price, call_short, "C")
        cl_iv = skew_adjusted_iv(iv, price, call_long, "C")

        ps_mid = bs_price(price, put_short, T, rfr, ps_iv, "P")
        pl_mid = bs_price(price, put_long, T, rfr, pl_iv, "P")
        cs_mid = bs_price(price, call_short, T, rfr, cs_iv, "C")
        cl_mid = bs_price(price, call_long, T, rfr, cl_iv, "C")

        ps_fill = get_fill_price(ps_mid, price, put_short, T, ps_iv, "sell", vix=vix)
        pl_fill = get_fill_price(pl_mid, price, put_long, T, pl_iv, "buy", vix=vix)
        cs_fill = get_fill_price(cs_mid, price, call_short, T, cs_iv, "sell", vix=vix)
        cl_fill = get_fill_price(cl_mid, price, call_long, T, cl_iv, "buy", vix=vix)

        put_credit = ps_fill - pl_fill
        call_credit = cs_fill - cl_fill
        combined_credit = put_credit + call_credit

        if combined_credit < min_credit:
            return None

        max_loss = spread_width - combined_credit
        if max_loss <= 0:
            return None

        legs = [
            TradeLeg(LegType.SHORT_PUT, put_short, expiration, entry_price=ps_fill),
            TradeLeg(LegType.LONG_PUT, put_long, expiration, entry_price=pl_fill),
            TradeLeg(LegType.SHORT_CALL, call_short, expiration, entry_price=cs_fill),
            TradeLeg(LegType.LONG_CALL, call_long, expiration, entry_price=cl_fill),
        ]

        raw_sl = self._p("stop_loss_multiplier", 2.0)
        max_sl = max_loss / combined_credit if combined_credit > 0 else raw_sl
        capped_sl = min(raw_sl, max_sl)

        return Signal(
            strategy_name=self.name,
            ticker=ticker,
            direction=TradeDirection.NEUTRAL,
            legs=legs,
            net_credit=combined_credit,
            max_loss=max_loss,
            max_profit=combined_credit,
            profit_target_pct=self._p("profit_target_pct", 0.50),
            stop_loss_pct=capped_sl,
            score=65.0,
            signal_date=date,
            expiration=expiration,
            dte=0,
            metadata={
                "is_zero_dte": True,
                "spread_type": "iron_condor",
                "put_short": put_short,
                "call_short": call_short,
                "put_credit": put_credit,
                "call_credit": call_credit,
                "vix_size_factor": vix_size_factor,
            },
        )

    # ------------------------------------------------------------------
    # manage_position
    # ------------------------------------------------------------------

    def manage_position(
        self, position: Position, market_data: MarketSnapshot,
    ) -> PositionAction:
        # Expiration: date past expiration day
        if position.legs and market_data.date > position.legs[0].expiration:
            return PositionAction.CLOSE_EXPIRY

        # Same-day expiration for live trading (backtester handles via dte <= 1)
        if position.legs and market_data.date == position.legs[0].expiration:
            # Still manage intraday — check gamma breach & P/L first
            pass

        price = market_data.prices.get(position.ticker)
        if price is None:
            return PositionAction.HOLD

        # Gamma breach: price near a short strike
        gamma_buffer = self._p("gamma_breach_buffer_pct", 0.002)
        for leg in position.legs:
            if leg.leg_type in (LegType.SHORT_PUT, LegType.SHORT_CALL):
                distance = abs(price - leg.strike) / price if price > 0 else 1.0
                if distance < gamma_buffer:
                    return PositionAction.CLOSE_SIGNAL

        # BS revaluation
        iv = market_data.realized_vol.get(position.ticker, 0.20)
        spread_value = estimate_spread_value(position, price, iv, market_data.date)
        cost_to_close = -spread_value
        credit = position.net_credit

        # Profit target
        profit_captured = credit - cost_to_close
        if profit_captured >= credit * position.profit_target_pct:
            return PositionAction.CLOSE_PROFIT

        # Stop loss
        loss = cost_to_close - credit
        if loss >= credit * position.stop_loss_pct:
            return PositionAction.CLOSE_STOP

        return PositionAction.HOLD

    # ------------------------------------------------------------------
    # size_position
    # ------------------------------------------------------------------

    def size_position(
        self, signal: Signal, portfolio_state: PortfolioState,
    ) -> int:
        from shared.constants import MAX_CONTRACTS_PER_TRADE

        max_risk_pct = self._p("max_risk_pct", 0.02)
        risk_budget = portfolio_state.equity * max_risk_pct

        risk_per_unit = signal.max_loss * 100  # per contract (100 shares)
        if risk_per_unit <= 0:
            return 0

        # Heat cap check
        if portfolio_state.total_risk >= portfolio_state.equity * portfolio_state.max_portfolio_risk_pct:
            return 0

        # 0DTE exposure cap
        max_zero_dte_pct = self._p("max_zero_dte_exposure_pct", 0.10)
        zero_dte_risk = sum(
            p.max_loss_per_unit * p.contracts * 100
            for p in portfolio_state.open_positions
            if p.metadata.get("is_zero_dte")
        )
        if zero_dte_risk >= portfolio_state.equity * max_zero_dte_pct:
            return 0

        contracts = max(1, int(risk_budget / risk_per_unit))

        # VIX size reduction
        vix_factor = signal.metadata.get("vix_size_factor", 1.0)
        if vix_factor < 1.0:
            contracts = max(1, int(contracts * vix_factor))

        return min(contracts, MAX_CONTRACTS_PER_TRADE)

    # ------------------------------------------------------------------
    # get_param_space
    # ------------------------------------------------------------------

    @classmethod
    def get_param_space(cls) -> List[ParamDef]:
        return [
            ParamDef("ema_period", "int", 20, low=10, high=50, step=5),
            ParamDef("otm_pct", "float", 0.004, low=0.002, high=0.008, step=0.001),
            ParamDef("spread_width", "float", 4.0, low=2.0, high=8.0, step=1.0),
            ParamDef("profit_target_pct", "float", 0.50, low=0.30, high=0.75, step=0.05),
            ParamDef("stop_loss_multiplier", "float", 2.0, low=1.0, high=3.0, step=0.25),
            ParamDef("min_credit", "float", 0.15, low=0.05, high=0.50, step=0.05),
            ParamDef("min_vix", "float", 12.0, low=8.0, high=18.0, step=1.0),
            ParamDef("max_vix_skip", "float", 45.0, low=30.0, high=60.0, step=5.0),
            ParamDef("vix_reduce_threshold", "float", 30.0, low=20.0, high=40.0, step=2.0),
            ParamDef("ic_vix_threshold", "float", 20.0, low=15.0, high=30.0, step=1.0),
            ParamDef("rsi_min_ic", "int", 40, low=30, high=50, step=5),
            ParamDef("rsi_max_ic", "int", 60, low=50, high=70, step=5),
            ParamDef("gamma_breach_buffer_pct", "float", 0.002, low=0.001, high=0.005, step=0.001),
            ParamDef("max_risk_pct", "float", 0.02, low=0.005, high=0.05, step=0.005),
            ParamDef("max_zero_dte_exposure_pct", "float", 0.10, low=0.05, high=0.20, step=0.025),
            ParamDef("max_gap_pct", "float", 0.01, low=0.005, high=0.03, step=0.005),
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_event_day(market_data: MarketSnapshot) -> bool:
        """Return True if today is an FOMC/CPI event day."""
        for event in market_data.upcoming_events:
            event_date = event.get("date")
            if event_date is None:
                continue
            # Normalise to date comparison
            if hasattr(event_date, "date"):
                event_date = event_date.date()
            md_date = market_data.date
            if hasattr(md_date, "date"):
                md_date = md_date.date()
            if event_date == md_date:
                return True
        return False
