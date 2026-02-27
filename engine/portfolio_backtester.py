"""
Portfolio-level backtester that runs multiple strategies simultaneously
with shared equity, position limits, and combined performance metrics.

Generalizes backtest/backtester.py to work with any combination of the
7 pluggable strategy modules from strategies/.
"""

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from engine.regime import RegimeClassifier
from shared.constants import DEFAULT_RISK_FREE_RATE, get_risk_free_rate
from shared.economic_calendar import EconomicCalendar
from shared.indicators import calculate_iv_rank as _calc_ivr
from strategies.base import (
    BaseStrategy,
    LegType,
    MarketSnapshot,
    Position,
    PortfolioState,
    PositionAction,
    Signal,
)
from shared.strike_selector import bs_delta
from strategies.pricing import bs_price, calculate_rsi, estimate_spread_value, estimate_spread_value_with_friction

logger = logging.getLogger(__name__)


class PortfolioBacktester:
    """Run any combination of strategies simultaneously with shared equity."""

    def __init__(
        self,
        strategies: List[Tuple[str, BaseStrategy]],
        tickers: List[str],
        start_date: datetime,
        end_date: datetime,
        starting_capital: float = 100_000,
        commission_per_leg: float = 0.65,
        max_positions: int = 10,
        max_positions_per_strategy: int = 5,
        max_portfolio_risk_pct: float = 0.40,
        gap_threshold: float = 0.005,
        options_cache=None,
        max_abs_delta: float = 50.0,
    ):
        self.strategies = strategies
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.starting_capital = starting_capital
        self.commission_per_leg = commission_per_leg
        self.max_positions = max_positions
        self.max_positions_per_strategy = max_positions_per_strategy
        self.max_portfolio_risk_pct = max_portfolio_risk_pct
        self.gap_threshold = gap_threshold
        self._options_cache = options_cache  # Optional[HistoricalOptionsData]
        self._cache_hits = 0
        self._cache_misses = 0
        self.max_abs_delta = max_abs_delta  # portfolio-level delta cap

        # State
        self.capital = starting_capital
        self.open_positions: List[Position] = []
        self.closed_trades: List[Position] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self._last_prices: Dict[str, float] = {}
        self._last_vols: Dict[str, float] = {}
        self._last_rfr: float = DEFAULT_RISK_FREE_RATE
        self._last_date: datetime = start_date

        # Pre-computed data (populated in _load_data)
        self._price_data: Dict[str, pd.DataFrame] = {}
        self._vix_series: Optional[pd.Series] = None
        self._iv_rank_by_date: Dict[pd.Timestamp, float] = {}
        self._realized_vol_by_date: Dict[str, Dict[pd.Timestamp, float]] = {}
        self._rsi_by_date: Dict[str, Dict[pd.Timestamp, float]] = {}
        self._calendar: Optional[EconomicCalendar] = None
        self._regime_classifier = RegimeClassifier()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> Dict:
        """Run the backtest and return results dict."""
        logger.info(
            "Starting portfolio backtest: %d strategies, %d tickers, %s to %s",
            len(self.strategies),
            len(self.tickers),
            self.start_date.strftime("%Y-%m-%d"),
            self.end_date.strftime("%Y-%m-%d"),
        )

        self._load_data()

        # Build union of all trading dates across tickers
        all_dates: set = set()
        for ticker, pdf in self._price_data.items():
            all_dates.update(pdf.index.tolist())
        trading_dates = sorted(
            d for d in all_dates
            if self.start_date <= d.to_pydatetime().replace(tzinfo=None) <= self.end_date
        )

        if not trading_dates:
            logger.warning("No trading dates found in range")
            return self._calculate_results()

        logger.info("Processing %d trading dates", len(trading_dates))

        for date_ts in trading_dates:
            date_dt = date_ts.to_pydatetime().replace(tzinfo=None)
            snapshot = self._build_market_snapshot(date_ts, date_dt)

            # Cache snapshot data for delta computation
            self._last_prices = snapshot.prices
            self._last_vols = snapshot.realized_vol
            self._last_rfr = snapshot.risk_free_rate
            self._last_date = date_dt

            # --- Gap-stop check: close positions gapped through stops ---
            if snapshot.gaps:
                for pos in list(self.open_positions):
                    if pos.ticker in snapshot.gaps and self._gap_triggers_stop(pos, snapshot):
                        self._close_position_at_gap(pos, snapshot)

            # --- Assignment risk: force-close positions with deep ITM short legs near expiry ---
            for pos in list(self.open_positions):
                if self._has_assignment_risk(pos, snapshot):
                    self._close_position(pos, PositionAction.CLOSE_SIGNAL, snapshot)

            # --- Exit check: each strategy manages its own positions ---
            positions_to_close: List[Tuple[Position, PositionAction]] = []
            for name, strategy in self.strategies:
                for pos in self._positions_for(strategy.name):
                    action = strategy.manage_position(pos, snapshot)
                    if action != PositionAction.HOLD:
                        positions_to_close.append((pos, action))

            for pos, action in positions_to_close:
                self._close_position(pos, action, snapshot)

            # --- Entry: each strategy generates signals ---
            all_signals: List[Signal] = []
            for name, strategy in self.strategies:
                try:
                    signals = strategy.generate_signals(snapshot)
                    for sig in signals:
                        sig.signal_date = date_dt
                    all_signals.extend(signals)
                except Exception as e:
                    logger.debug("Strategy %s signal error on %s: %s", name, date_dt, e)

            # Sort by score (best first), accept within limits
            all_signals.sort(key=lambda s: s.score, reverse=True)
            for signal in all_signals:
                if not self._can_accept(signal):
                    continue
                strategy = self._strategy_by_name(signal.strategy_name)
                if strategy is None:
                    continue
                contracts = strategy.size_position(signal, self._portfolio_state())
                if contracts > 0:
                    self._open_position(signal, contracts, date_dt)

            # --- Record equity ---
            self._record_equity(date_dt, snapshot)

        # Close any remaining open positions at backtest end
        if self.open_positions:
            last_date = trading_dates[-1]
            last_dt = last_date.to_pydatetime().replace(tzinfo=None)
            last_snapshot = self._build_market_snapshot(last_date, last_dt)
            for pos in list(self.open_positions):
                self._close_position(pos, PositionAction.CLOSE_EXPIRY, last_snapshot)

        results = self._calculate_results()

        # Log cache stats if options cache was used
        if self._options_cache is not None:
            total_lookups = self._cache_hits + self._cache_misses
            hit_rate = (self._cache_hits / total_lookups * 100) if total_lookups else 0
            results["cache_stats"] = {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "hit_rate_pct": round(hit_rate, 1),
            }
            logger.info(
                "Cache stats: %d hits, %d misses (%.1f%% hit rate)",
                self._cache_hits, self._cache_misses, hit_rate,
            )

        logger.info(
            "Backtest complete: %d trades, %.2f%% return, %.2f Sharpe",
            results["combined"]["total_trades"],
            results["combined"]["return_pct"],
            results["combined"]["sharpe_ratio"],
        )
        return results

    # ------------------------------------------------------------------
    # Data Loading
    # ------------------------------------------------------------------

    def _load_data(self) -> None:
        """Download OHLCV, VIX, build IV rank + realized vol + RSI series."""
        warmup_days = 60
        fetch_start = self.start_date - timedelta(days=warmup_days)

        # OHLCV per ticker
        for ticker in self.tickers:
            try:
                raw = yf.download(
                    ticker,
                    start=fetch_start.strftime("%Y-%m-%d"),
                    end=(self.end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
                    progress=False,
                    auto_adjust=True,
                )
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                if raw.index.tz is not None:
                    raw.index = raw.index.tz_localize(None)
                self._price_data[ticker] = raw
                logger.info("Loaded %d rows for %s", len(raw), ticker)
            except Exception as e:
                logger.error("Failed to load %s: %s", ticker, e)

        # VIX + IV rank
        self._iv_rank_by_date = self._build_iv_rank_series(fetch_start, self.end_date)

        # Realized vol per ticker
        for ticker, pdf in self._price_data.items():
            self._realized_vol_by_date[ticker] = self._build_realized_vol_series(pdf)

        # RSI per ticker
        for ticker, pdf in self._price_data.items():
            self._rsi_by_date[ticker] = self._build_rsi_series(pdf)

        # Economic calendar
        years = list(range(self.start_date.year, self.end_date.year + 1))
        self._calendar = EconomicCalendar(years=years)

    def _build_iv_rank_series(
        self, start_date: datetime, end_date: datetime,
    ) -> Dict[pd.Timestamp, float]:
        """Build {Timestamp: iv_rank} using VIX and 252-day rolling window."""
        try:
            fetch_start = start_date - timedelta(days=300)
            raw = yf.download(
                "^VIX",
                start=fetch_start.strftime("%Y-%m-%d"),
                end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
            )
            if raw.empty:
                logger.warning("VIX data unavailable — using default iv_rank=25")
                return {}

            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)

            vix = raw["Close"].dropna()
            if vix.index.tz is not None:
                vix.index = vix.index.tz_localize(None)

            # Store VIX series for snapshots
            self._vix_series = vix

            iv_rank_map: Dict[pd.Timestamp, float] = {}
            for ts in vix.index:
                window = vix.loc[:ts].tail(252)
                if len(window) < 20:
                    iv_rank_map[ts] = 25.0
                    continue
                result = _calc_ivr(window, float(vix.loc[ts]))
                iv_rank_map[ts] = result["iv_rank"]

            logger.info(
                "IV rank series: %d dates, range %.0f–%.0f",
                len(iv_rank_map),
                min(iv_rank_map.values()) if iv_rank_map else 0,
                max(iv_rank_map.values()) if iv_rank_map else 0,
            )
            return iv_rank_map
        except Exception as e:
            logger.warning("Failed to build IV rank series: %s", e)
            return {}

    def _build_realized_vol_series(
        self, price_data: pd.DataFrame,
    ) -> Dict[pd.Timestamp, float]:
        """Build {Timestamp: realized_vol} from ATR-based proxy.

        Formula: sigma = ATR(20) / Close * sqrt(252), clipped [0.10, 1.00].
        """
        try:
            high = price_data["High"]
            low = price_data["Low"]
            close = price_data["Close"]
            prev_close = close.shift(1)

            tr = pd.concat(
                [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
                axis=1,
            ).max(axis=1)

            atr20 = tr.rolling(20, min_periods=5).mean()
            rv = (atr20 / close * math.sqrt(252)).clip(lower=0.10, upper=1.00)
            rv = rv.fillna(0.25)

            if rv.index.tz is not None:
                rv.index = rv.index.tz_localize(None)

            return rv.to_dict()
        except Exception as e:
            logger.warning("Failed to build realized vol series: %s", e)
            return {}

    def _build_rsi_series(
        self, price_data: pd.DataFrame,
    ) -> Dict[pd.Timestamp, float]:
        """Pre-compute 14-period RSI per day."""
        try:
            closes = price_data["Close"]
            rsi_map: Dict[pd.Timestamp, float] = {}
            close_list = closes.tolist()
            dates = closes.index.tolist()

            for i in range(len(close_list)):
                window = close_list[: i + 1]
                rsi_map[dates[i]] = calculate_rsi(window, period=14)

            return rsi_map
        except Exception as e:
            logger.warning("Failed to build RSI series: %s", e)
            return {}

    # ------------------------------------------------------------------
    # Market Snapshot
    # ------------------------------------------------------------------

    def _build_market_snapshot(
        self, date_ts: pd.Timestamp, date_dt: datetime,
    ) -> MarketSnapshot:
        """Build a MarketSnapshot for the given trading day."""
        # Per-ticker price data (history up to this date)
        price_data: Dict[str, pd.DataFrame] = {}
        prices: Dict[str, float] = {}
        open_prices: Dict[str, float] = {}
        gaps: Dict[str, float] = {}
        iv_rank: Dict[str, float] = {}
        realized_vol: Dict[str, float] = {}
        rsi: Dict[str, float] = {}

        for ticker in self.tickers:
            pdf = self._price_data.get(ticker)
            if pdf is None or pdf.empty:
                continue
            # Slice up to current date
            mask = pdf.index <= date_ts
            sliced = pdf.loc[mask]
            if sliced.empty:
                continue
            price_data[ticker] = sliced
            prices[ticker] = float(sliced["Close"].iloc[-1])

            # Open price and gap detection
            if "Open" in sliced.columns:
                open_prices[ticker] = float(sliced["Open"].iloc[-1])
            if len(sliced) >= 2 and "Open" in sliced.columns:
                today_open = float(sliced["Open"].iloc[-1])
                prev_close = float(sliced["Close"].iloc[-2])
                if prev_close > 0:
                    gap_pct = (today_open - prev_close) / prev_close
                    if abs(gap_pct) >= self.gap_threshold:
                        gaps[ticker] = gap_pct

            # IV rank — use the global VIX-based rank for all tickers
            iv_rank[ticker] = self._iv_rank_by_date.get(date_ts, 25.0)

            # Realized vol per ticker
            rv_map = self._realized_vol_by_date.get(ticker, {})
            realized_vol[ticker] = rv_map.get(date_ts, 0.25)

            # RSI per ticker
            rsi_map = self._rsi_by_date.get(ticker, {})
            rsi[ticker] = rsi_map.get(date_ts, 50.0)

        # VIX current value
        vix_val = 20.0
        if self._vix_series is not None and date_ts in self._vix_series.index:
            vix_val = float(self._vix_series.loc[date_ts])

        # VIX history up to this date
        vix_history = None
        if self._vix_series is not None:
            vix_history = self._vix_series.loc[self._vix_series.index <= date_ts]

        # Upcoming economic events
        ref_date = date_dt.replace(tzinfo=timezone.utc)
        upcoming_events = (
            self._calendar.get_upcoming_events(days_ahead=3, reference_date=ref_date)
            if self._calendar
            else []
        )

        # Recent past events (for post-event strategies like short straddles)
        recent_events = (
            self._calendar.get_recent_events(days_back=2, reference_date=ref_date)
            if self._calendar
            else []
        )

        # Regime classification (use SPY prices if available, else first ticker)
        regime_val = None
        spy_key = next((t for t in self.tickers if t.upper() == "SPY"), None)
        regime_ticker = spy_key or (self.tickers[0] if self.tickers else None)
        if regime_ticker and regime_ticker in price_data:
            spy_close = price_data[regime_ticker]["Close"]
            regime_val = self._regime_classifier.classify(
                vix_val, spy_close, date_ts,
            ).value

        return MarketSnapshot(
            date=date_dt,
            price_data=price_data,
            prices=prices,
            open_prices=open_prices,
            gaps=gaps,
            vix=vix_val,
            vix_history=vix_history,
            iv_rank=iv_rank,
            realized_vol=realized_vol,
            rsi=rsi,
            upcoming_events=upcoming_events,
            recent_events=recent_events,
            risk_free_rate=get_risk_free_rate(date_dt),
            regime=regime_val,
        )

    # ------------------------------------------------------------------
    # Position Management
    # ------------------------------------------------------------------

    def _positions_for(self, strategy_name: str) -> List[Position]:
        """Return open positions belonging to a strategy."""
        return [p for p in self.open_positions if p.strategy_name == strategy_name]

    def _strategy_by_name(self, name: str) -> Optional[BaseStrategy]:
        """Lookup strategy instance by class name or registry name."""
        for reg_name, strategy in self.strategies:
            if strategy.name == name or reg_name == name:
                return strategy
        return None

    def _portfolio_state(self) -> PortfolioState:
        """Build current PortfolioState for sizing decisions."""
        total_risk = sum(
            p.max_loss_per_unit * p.contracts * 100 for p in self.open_positions
        )
        # Margin requirement: spread width × contracts × 100 for defined-risk
        margin_used = sum(
            p.max_loss_per_unit * p.contracts * 100 for p in self.open_positions
        )
        buying_power = max(0.0, self.capital - margin_used)

        return PortfolioState(
            equity=self.capital,
            starting_capital=self.starting_capital,
            cash=self.capital,
            open_positions=list(self.open_positions),
            total_risk=total_risk,
            max_portfolio_risk_pct=self.max_portfolio_risk_pct,
            net_delta=self._compute_portfolio_delta(),
            buying_power=buying_power,
        )

    def _compute_portfolio_delta(self) -> float:
        """Compute aggregate portfolio delta across all open positions.

        Each option leg contributes: sign * bs_delta * contracts * 100.
        Long legs have positive sign, short legs negative.
        Uses the most recent snapshot data for pricing.
        """
        total_delta = 0.0
        for pos in self.open_positions:
            price = self._last_prices.get(pos.ticker, 0)
            if price <= 0:
                continue
            iv = self._last_vols.get(pos.ticker, 0.20)
            rfr = self._last_rfr

            for leg in pos.legs:
                if leg.leg_type == LegType.LONG_STOCK:
                    total_delta += pos.contracts
                    continue
                elif leg.leg_type == LegType.SHORT_STOCK:
                    total_delta -= pos.contracts
                    continue

                is_call = "call" in leg.leg_type.value
                is_long = "long" in leg.leg_type.value
                opt_type = "C" if is_call else "P"

                dte = max((leg.expiration - self._last_date).days, 0) if leg.expiration else 0
                T = max(dte / 365.0, 0.001)

                d = bs_delta(price, leg.strike, T, rfr, iv, opt_type)
                sign = 1.0 if is_long else -1.0
                total_delta += sign * d * pos.contracts * 100

        return round(total_delta, 1)

    def _compute_signal_delta(
        self, signal: Signal, contracts: int, price: float, iv: float,
        rfr: float, current_date: datetime,
    ) -> float:
        """Compute the delta contribution of a potential new position."""
        delta = 0.0
        for leg in signal.legs:
            if leg.leg_type in (LegType.LONG_STOCK, LegType.SHORT_STOCK):
                sign = 1.0 if leg.leg_type == LegType.LONG_STOCK else -1.0
                delta += sign * contracts
                continue

            is_call = "call" in leg.leg_type.value
            is_long = "long" in leg.leg_type.value
            opt_type = "C" if is_call else "P"

            dte = max((leg.expiration - current_date).days, 0) if leg.expiration else 0
            T = max(dte / 365.0, 0.001)

            d = bs_delta(price, leg.strike, T, rfr, iv, opt_type)
            sign = 1.0 if is_long else -1.0
            delta += sign * d * contracts * 100

        return delta

    @staticmethod
    def _compute_margin_requirement(signal: Signal, contracts: int) -> float:
        """Compute Reg-T style margin for a defined-risk options position.

        For spreads: margin = spread width × contracts × 100.
        For naked options: margin = max_loss × contracts × 100.
        For debit trades: margin = debit paid (already reserved as cash).
        """
        if signal.net_credit < 0:
            # Debit: margin = cost (already deducted from cash)
            return abs(signal.net_credit) * contracts * 100

        # Credit spread: margin = spread_width × contracts × 100
        return signal.max_loss * contracts * 100

    def _can_accept(self, signal: Signal) -> bool:
        """Check position limits before accepting a new signal."""
        # 1. Max concurrent positions
        if len(self.open_positions) >= self.max_positions:
            return False

        # 2. Max per strategy
        strategy_count = sum(
            1 for p in self.open_positions if p.strategy_name == signal.strategy_name
        )
        if strategy_count >= self.max_positions_per_strategy:
            return False

        # 3. Max total risk (heat cap)
        total_risk = sum(
            p.max_loss_per_unit * p.contracts * 100 for p in self.open_positions
        )
        signal_risk = signal.max_loss * 100  # 1 contract for now; sized later
        if total_risk + signal_risk > self.capital * self.max_portfolio_risk_pct:
            return False

        # 4. No duplicate ticker+strategy combo
        for p in self.open_positions:
            if p.ticker == signal.ticker and p.strategy_name == signal.strategy_name:
                return False

        # 5. Debit trades: reject if cost > 10% of capital
        if signal.net_credit < 0:
            debit_cost = abs(signal.net_credit) * 100  # 1 contract estimate
            if debit_cost > self.capital * 0.10:
                return False

        # 6. Delta cap: reject if adding this trade would push portfolio delta
        #    beyond the absolute delta limit
        price = self._last_prices.get(signal.ticker, 0)
        if price > 0:
            iv = self._last_vols.get(signal.ticker, 0.20)
            signal_delta = self._compute_signal_delta(
                signal, 1, price, iv, self._last_rfr, self._last_date,
            )
            current_delta = self._compute_portfolio_delta()
            new_delta = abs(current_delta + signal_delta)
            if new_delta > self.max_abs_delta:
                return False

        # 7. Margin/buying power: reject if insufficient
        margin_needed = self._compute_margin_requirement(signal, 1)
        margin_used = sum(
            p.max_loss_per_unit * p.contracts * 100 for p in self.open_positions
        )
        if margin_used + margin_needed > self.capital:
            return False

        return True

    def _open_position(
        self, signal: Signal, contracts: int, date: datetime,
    ) -> Position:
        """Open a new position from a signal."""
        num_legs = len(signal.legs)
        entry_commission = self.commission_per_leg * num_legs * contracts
        self.capital -= entry_commission

        pos = Position(
            id=str(uuid.uuid4())[:8],
            strategy_name=signal.strategy_name,
            ticker=signal.ticker,
            direction=signal.direction,
            legs=signal.legs,
            contracts=contracts,
            entry_date=date,
            net_credit=signal.net_credit,
            max_loss_per_unit=signal.max_loss,
            max_profit_per_unit=signal.max_profit,
            profit_target_pct=signal.profit_target_pct,
            stop_loss_pct=signal.stop_loss_pct,
            commission_paid=entry_commission,
            metadata=dict(signal.metadata),
        )

        # Debit reservation: deduct cash for debit trades at entry
        if signal.net_credit < 0:
            debit_reserved = abs(signal.net_credit) * contracts * 100
            self.capital -= debit_reserved
            pos.metadata["_debit_reserved"] = debit_reserved

        self.open_positions.append(pos)
        return pos

    def _close_position(
        self, pos: Position, action: PositionAction, snapshot: MarketSnapshot,
    ) -> None:
        """Close a position, compute P&L, and record the trade."""
        price = snapshot.prices.get(pos.ticker, 0)
        iv = snapshot.realized_vol.get(pos.ticker, 0.20)

        if action == PositionAction.CLOSE_EXPIRY:
            pnl = self._settle_at_expiration(pos, price)
        else:
            pnl = self._compute_exit_pnl(pos, action, price, iv, snapshot.date,
                                        vix=snapshot.vix, r=snapshot.risk_free_rate)

        # Exit commission
        num_legs = len(pos.legs)
        exit_commission = self.commission_per_leg * num_legs * pos.contracts
        pnl -= exit_commission

        # Credit back debit reservation before adding P&L
        debit_reserved = pos.metadata.pop("_debit_reserved", 0.0)
        self.capital += debit_reserved

        self.capital += pnl
        pos.realized_pnl = pnl
        pos.exit_date = snapshot.date
        pos.exit_reason = action.value

        if pos in self.open_positions:
            self.open_positions.remove(pos)
        self.closed_trades.append(pos)

    def _gap_triggers_stop(
        self, pos: Position, snapshot: MarketSnapshot,
    ) -> bool:
        """Check if the gap open price would trigger this position's stop.

        Mirrors strategy stop logic using estimate_spread_value (no friction)
        at the open price instead of the close price.
        """
        open_price = snapshot.open_prices.get(pos.ticker)
        if open_price is None:
            return False

        iv = snapshot.realized_vol.get(pos.ticker, 0.20)
        spread_value = estimate_spread_value(
            pos, open_price, iv, snapshot.date, snapshot.risk_free_rate,
        )

        is_credit = pos.net_credit > 0

        if is_credit:
            cost_to_close = -spread_value
            credit = pos.net_credit
            loss = cost_to_close - credit
            return loss >= credit * pos.stop_loss_pct
        else:
            entry_debit = abs(pos.net_credit)
            if entry_debit <= 0:
                return False
            loss = entry_debit - spread_value
            return loss >= entry_debit * pos.stop_loss_pct

    def _close_position_at_gap(
        self, pos: Position, snapshot: MarketSnapshot,
    ) -> None:
        """Close a position at the gap open price (stop gapped through).

        Uses open price with friction for realistic fill. Exit reason is
        'close_gap_stop' to distinguish from normal stop losses.
        """
        open_price = snapshot.open_prices.get(pos.ticker, 0)
        iv = snapshot.realized_vol.get(pos.ticker, 0.20)

        pnl = self._compute_exit_pnl(
            pos, PositionAction.CLOSE_STOP, open_price, iv, snapshot.date,
            vix=snapshot.vix, r=snapshot.risk_free_rate,
        )

        # Exit commission
        num_legs = len(pos.legs)
        exit_commission = self.commission_per_leg * num_legs * pos.contracts
        pnl -= exit_commission

        # Credit back debit reservation before adding P&L
        debit_reserved = pos.metadata.pop("_debit_reserved", 0.0)
        self.capital += debit_reserved

        self.capital += pnl
        pos.realized_pnl = pnl
        pos.exit_date = snapshot.date
        pos.exit_reason = "close_gap_stop"

        if pos in self.open_positions:
            self.open_positions.remove(pos)
        self.closed_trades.append(pos)

    def _has_assignment_risk(
        self, pos: Position, snapshot: MarketSnapshot,
    ) -> bool:
        """Check if any short leg has assignment risk.

        Triggers when a short option is ≥1% ITM with ≤2 DTE.
        This models real brokerage behavior where deep ITM shorts
        near expiration get assigned, creating unwanted stock positions.
        """
        price = snapshot.prices.get(pos.ticker)
        if price is None or price <= 0:
            return False

        for leg in pos.legs:
            if leg.leg_type in (LegType.LONG_STOCK, LegType.SHORT_STOCK,
                                LegType.LONG_CALL, LegType.LONG_PUT):
                continue

            if leg.expiration is None:
                continue

            dte = (leg.expiration - snapshot.date).days
            if dte > 2:
                continue

            # Check if short leg is ≥1% ITM
            is_call = "call" in leg.leg_type.value
            if is_call:
                itm_pct = (price - leg.strike) / price
            else:
                itm_pct = (leg.strike - price) / price

            if itm_pct >= 0.01:
                return True

        return False

    def _settle_at_expiration(self, pos: Position, underlying_price: float) -> float:
        """Compute P&L at expiration based on whether legs are ITM/OTM."""
        total_pnl = 0.0

        for leg in pos.legs:
            if leg.leg_type in (LegType.LONG_STOCK, LegType.SHORT_STOCK):
                if leg.leg_type == LegType.LONG_STOCK:
                    total_pnl += (underlying_price - leg.entry_price) * pos.contracts
                else:
                    total_pnl += (leg.entry_price - underlying_price) * pos.contracts
                continue

            is_call = "call" in leg.leg_type.value
            is_long = "long" in leg.leg_type.value

            if is_call:
                intrinsic = max(underlying_price - leg.strike, 0)
            else:
                intrinsic = max(leg.strike - underlying_price, 0)

            if is_long:
                # Long leg: we paid entry_price, receive intrinsic
                leg_pnl = (intrinsic - leg.entry_price) * pos.contracts * 100
            else:
                # Short leg: we received entry_price, pay intrinsic
                leg_pnl = (leg.entry_price - intrinsic) * pos.contracts * 100

            total_pnl += leg_pnl

        return total_pnl

    def _get_cached_spread_value(self, pos: Position, date_str: str) -> Optional[float]:
        """Look up spread value from Polygon options cache.

        For each leg, builds the OCC symbol and looks up the close price.
        Returns net spread value (short legs negative, long legs positive)
        if ALL legs are found, else None (fall back to BS).
        """
        if self._options_cache is None:
            return None

        from backtest.historical_data import HistoricalOptionsData

        net_value = 0.0
        for leg in pos.legs:
            if leg.leg_type in (LegType.LONG_STOCK, LegType.SHORT_STOCK):
                return None  # Stock legs: use equity pricing, not options cache

            is_call = "call" in leg.leg_type.value
            is_long = "long" in leg.leg_type.value
            option_type = "C" if is_call else "P"

            symbol = HistoricalOptionsData.build_occ_symbol(
                pos.ticker, leg.expiration, leg.strike, option_type,
            )
            price = self._options_cache.get_contract_price(symbol, date_str)
            if price is None:
                self._cache_misses += 1
                return None

            if is_long:
                net_value += price
            else:
                net_value -= price

        self._cache_hits += 1
        return net_value

    def _compute_exit_pnl(
        self,
        pos: Position,
        action: PositionAction,
        price: float,
        iv: float,
        current_date: datetime,
        vix: float = 20.0,
        r: float = DEFAULT_RISK_FREE_RATE,
    ) -> float:
        """Compute mid-trade P&L for non-expiration exits.

        Always uses mark-to-market with bid-ask friction — no hardcoded
        percentage shortcuts. This ensures profit/stop exits reflect
        actual closing costs rather than ideal percentages.
        """
        has_stock_legs = any(
            leg.leg_type in (LegType.LONG_STOCK, LegType.SHORT_STOCK)
            for leg in pos.legs
        )

        if has_stock_legs:
            # Equity/stock P&L
            pnl = 0.0
            for leg in pos.legs:
                if leg.leg_type == LegType.LONG_STOCK:
                    pnl += (price - leg.entry_price) * pos.contracts
                elif leg.leg_type == LegType.SHORT_STOCK:
                    pnl += (leg.entry_price - price) * pos.contracts
            return pnl

        # Try cached Polygon prices first, fall back to BS model
        cached = self._get_cached_spread_value(pos, current_date.strftime("%Y-%m-%d"))
        if cached is not None:
            current_value = cached
        else:
            # Mark-to-market with friction for ALL exit types
            current_value = estimate_spread_value_with_friction(
                pos, price, iv, current_date, r, closing=True, vix=vix,
            )

        is_credit = pos.net_credit > 0

        if is_credit:
            # Credit: collected net_credit upfront, now pay current_value to close
            # current_value is negative for short spreads (cost to buy back)
            pnl = (pos.net_credit + current_value) * pos.contracts * 100
        else:
            # Debit: paid |net_credit| upfront, now receive current_value
            pnl = (current_value - abs(pos.net_credit)) * pos.contracts * 100

        return pnl

    # ------------------------------------------------------------------
    # Equity Tracking
    # ------------------------------------------------------------------

    def _record_equity(
        self, date: datetime, snapshot: MarketSnapshot,
    ) -> None:
        """Record end-of-day equity (cash + mark-to-market open positions).

        True portfolio value = cash + unrealized value of every open position.
        Credit positions: unrealized = (net_credit + current_value) * contracts * 100
        Debit positions:  unrealized = (current_value - |net_credit|) * contracts * 100
        Stock positions:  unrealized = (price - entry) * contracts  (or inverse for short)
        """
        unrealized = 0.0
        for pos in self.open_positions:
            price = snapshot.prices.get(pos.ticker)
            if price is None:
                continue

            has_stock = any(
                leg.leg_type in (LegType.LONG_STOCK, LegType.SHORT_STOCK)
                for leg in pos.legs
            )

            if has_stock:
                for leg in pos.legs:
                    if leg.leg_type == LegType.LONG_STOCK:
                        unrealized += (price - leg.entry_price) * pos.contracts
                    elif leg.leg_type == LegType.SHORT_STOCK:
                        unrealized += (leg.entry_price - price) * pos.contracts
            else:
                # Try cached Polygon prices first, fall back to BS
                cached = self._get_cached_spread_value(pos, date.strftime("%Y-%m-%d"))
                if cached is not None:
                    current_value = cached
                else:
                    iv = snapshot.realized_vol.get(pos.ticker, 0.20)
                    current_value = estimate_spread_value_with_friction(
                        pos, price, iv, date, snapshot.risk_free_rate, closing=True,
                        vix=snapshot.vix,
                    )
                if pos.net_credit > 0:
                    # Credit: collected premium, now would cost -current_value to close
                    unrealized += (pos.net_credit + current_value) * pos.contracts * 100
                else:
                    # Debit: paid |net_credit|, position now worth current_value
                    unrealized += (current_value - abs(pos.net_credit)) * pos.contracts * 100

        self.equity_curve.append((date, self.capital + unrealized))

    # ------------------------------------------------------------------
    # Performance Metrics
    # ------------------------------------------------------------------

    def _calculate_results(self) -> Dict[str, Any]:
        """Compute combined + per-strategy performance metrics."""
        trades = self.closed_trades
        config = {
            "strategies": [name for name, _ in self.strategies],
            "tickers": self.tickers,
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "end_date": self.end_date.strftime("%Y-%m-%d"),
            "starting_capital": self.starting_capital,
            "max_positions": self.max_positions,
            "max_positions_per_strategy": self.max_positions_per_strategy,
            "max_portfolio_risk_pct": self.max_portfolio_risk_pct,
        }

        combined = self._compute_metrics(trades)
        combined["starting_capital"] = self.starting_capital
        combined["ending_capital"] = round(self.capital, 2)
        combined["return_pct"] = round(
            ((self.capital - self.starting_capital) / self.starting_capital) * 100, 2
        ) if self.starting_capital else 0.0

        # Equity curve
        combined["equity_curve"] = [
            {"date": d.strftime("%Y-%m-%d"), "equity": round(eq, 2)}
            for d, eq in self.equity_curve
        ]

        # Sharpe & max drawdown from equity curve
        if len(self.equity_curve) > 1:
            eq_values = [eq for _, eq in self.equity_curve]
            eq_series = pd.Series(eq_values, dtype=float)
            daily_returns = eq_series.pct_change().dropna()

            if len(daily_returns) > 0 and daily_returns.std() > 0:
                combined["sharpe_ratio"] = round(
                    float((daily_returns.mean() / daily_returns.std()) * np.sqrt(252)),
                    2,
                )
            else:
                combined["sharpe_ratio"] = 0.0

            cummax = eq_series.cummax()
            drawdowns = (eq_series - cummax) / cummax
            combined["max_drawdown"] = round(float(drawdowns.min()) * 100, 2)
        else:
            combined["sharpe_ratio"] = 0.0
            combined["max_drawdown"] = 0.0

        # Gap stop statistics
        gap_stopped = [t for t in trades if t.exit_reason == "close_gap_stop"]
        combined["gap_stop_count"] = len(gap_stopped)
        combined["gap_stop_pnl"] = round(sum(t.realized_pnl for t in gap_stopped), 2)

        # Monthly P&L
        combined["monthly_pnl"] = self._monthly_pnl(trades)

        # Per-strategy breakdown
        per_strategy: Dict[str, Dict] = {}
        strategy_names = set(t.strategy_name for t in trades)
        for sname in strategy_names:
            strades = [t for t in trades if t.strategy_name == sname]
            per_strategy[sname] = self._compute_metrics(strades)

        # Per-trade log
        trade_log = self._build_trade_log(trades)

        # Yearly breakdown
        yearly = self._yearly_breakdown(trades)

        return {
            "timestamp": datetime.now().isoformat(),
            "config": config,
            "combined": combined,
            "per_strategy": per_strategy,
            "trades": trade_log,
            "yearly": yearly,
        }

    def _compute_metrics(self, trades: List[Position]) -> Dict[str, Any]:
        """Compute standard performance metrics for a list of closed trades."""
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "max_win_streak": 0,
                "max_loss_streak": 0,
            }

        pnls = [t.realized_pnl for t in trades]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p < 0]

        total_trades = len(trades)
        win_rate = round((len(winners) / total_trades) * 100, 2) if total_trades else 0.0
        total_pnl = round(sum(pnls), 2)
        avg_win = round(sum(winners) / len(winners), 2) if winners else 0.0
        avg_loss = round(abs(sum(losers) / len(losers)), 2) if losers else 0.0

        winning_total = sum(winners) if winners else 0
        losing_total = abs(sum(losers)) if losers else 0
        if losing_total > 0:
            profit_factor = round(winning_total / losing_total, 2)
        elif winning_total > 0:
            profit_factor = 999.99
        else:
            profit_factor = 0.0

        # Streak tracking
        max_win_streak = max_loss_streak = cur_win = cur_loss = 0
        for p in pnls:
            if p > 0:
                cur_win += 1
                cur_loss = 0
                max_win_streak = max(max_win_streak, cur_win)
            else:
                cur_loss += 1
                cur_win = 0
                max_loss_streak = max(max_loss_streak, cur_loss)

        return {
            "total_trades": total_trades,
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
        }

    def _monthly_pnl(self, trades: List[Position]) -> Dict[str, Dict]:
        """Compute monthly P&L breakdown."""
        monthly: Dict[str, Dict] = {}
        for t in trades:
            if t.exit_date is None:
                continue
            key = t.exit_date.strftime("%Y-%m")
            if key not in monthly:
                monthly[key] = {"pnl": 0.0, "trades": 0, "wins": 0}
            monthly[key]["pnl"] = round(monthly[key]["pnl"] + t.realized_pnl, 2)
            monthly[key]["trades"] += 1
            if t.realized_pnl > 0:
                monthly[key]["wins"] += 1

        for key in monthly:
            m = monthly[key]
            m["win_rate"] = round(m["wins"] / m["trades"], 3) if m["trades"] else 0.0

        return monthly

    def _build_trade_log(self, trades: List[Position]) -> List[Dict]:
        """Build per-trade log for JSON output."""
        log = []
        for t in trades:
            entry = {
                "id": t.id,
                "strategy": t.strategy_name,
                "ticker": t.ticker,
                "direction": t.direction.value,
                "entry_date": t.entry_date.strftime("%Y-%m-%d") if t.entry_date else None,
                "exit_date": t.exit_date.strftime("%Y-%m-%d") if t.exit_date else None,
                "exit_reason": t.exit_reason,
                "net_credit": round(t.net_credit, 4),
                "contracts": t.contracts,
                "pnl": round(t.realized_pnl, 2),
                "return_pct": round(
                    (t.realized_pnl / (t.max_loss_per_unit * t.contracts * 100)) * 100, 2
                ) if t.max_loss_per_unit * t.contracts else 0.0,
                "legs": [
                    {
                        "type": leg.leg_type.value,
                        "strike": leg.strike,
                        "exp": leg.expiration.strftime("%Y-%m-%d") if leg.expiration else None,
                    }
                    for leg in t.legs
                ],
            }
            log.append(entry)
        return log

    def _yearly_breakdown(self, trades: List[Position]) -> Dict[str, Dict]:
        """Compute per-year return, drawdown, and trade count."""
        yearly: Dict[str, Dict] = {}
        for t in trades:
            if t.exit_date is None:
                continue
            year = str(t.exit_date.year)
            if year not in yearly:
                yearly[year] = {"total_pnl": 0.0, "trades": 0, "wins": 0}
            yearly[year]["total_pnl"] = round(yearly[year]["total_pnl"] + t.realized_pnl, 2)
            yearly[year]["trades"] += 1
            if t.realized_pnl > 0:
                yearly[year]["wins"] += 1

        # Compute return_pct and win_rate per year
        for year in yearly:
            y = yearly[year]
            y["return_pct"] = round(
                (y["total_pnl"] / self.starting_capital) * 100, 2
            )
            y["win_rate"] = round(
                (y["wins"] / y["trades"]) * 100, 2
            ) if y["trades"] else 0.0
            # Remove intermediate keys
            del y["wins"]

        # Per-year max drawdown from equity curve
        eq_by_year: Dict[str, List[float]] = {}
        for d, eq in self.equity_curve:
            yr = str(d.year)
            if yr not in eq_by_year:
                eq_by_year[yr] = []
            eq_by_year[yr].append(eq)

        for year in yearly:
            if year in eq_by_year and len(eq_by_year[year]) > 1:
                eq = pd.Series(eq_by_year[year], dtype=float)
                cummax = eq.cummax()
                dd = ((eq - cummax) / cummax).min()
                yearly[year]["max_drawdown"] = round(float(dd) * 100, 2)
            else:
                yearly[year]["max_drawdown"] = 0.0

        return yearly
