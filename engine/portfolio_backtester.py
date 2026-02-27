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
from shared.constants import DEFAULT_RISK_FREE_RATE
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
from strategies.pricing import bs_price, calculate_rsi, estimate_spread_value

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
        slippage: float = 0.05,
        max_positions: int = 10,
        max_positions_per_strategy: int = 5,
        max_portfolio_risk_pct: float = 0.40,
    ):
        self.strategies = strategies
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.starting_capital = starting_capital
        self.commission_per_leg = commission_per_leg
        self.slippage = slippage
        self.max_positions = max_positions
        self.max_positions_per_strategy = max_positions_per_strategy
        self.max_portfolio_risk_pct = max_portfolio_risk_pct

        # State
        self.capital = starting_capital
        self.open_positions: List[Position] = []
        self.closed_trades: List[Position] = []
        self.equity_curve: List[Tuple[datetime, float]] = []

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
            self._record_equity(date_dt)

        # Close any remaining open positions at backtest end
        if self.open_positions:
            last_date = trading_dates[-1]
            last_dt = last_date.to_pydatetime().replace(tzinfo=None)
            last_snapshot = self._build_market_snapshot(last_date, last_dt)
            for pos in list(self.open_positions):
                self._close_position(pos, PositionAction.CLOSE_EXPIRY, last_snapshot)

        results = self._calculate_results()
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
            vix=vix_val,
            vix_history=vix_history,
            iv_rank=iv_rank,
            realized_vol=realized_vol,
            rsi=rsi,
            upcoming_events=upcoming_events,
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
        return PortfolioState(
            equity=self.capital,
            starting_capital=self.starting_capital,
            cash=self.capital,
            open_positions=list(self.open_positions),
            total_risk=total_risk,
            max_portfolio_risk_pct=self.max_portfolio_risk_pct,
        )

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
        # Capital changes happen entirely at close via realized P&L.
        # No debit deduction here — P&L at close accounts for entry cost.

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
            pnl = self._compute_exit_pnl(pos, action, price, iv, snapshot.date)

        # Exit commission
        num_legs = len(pos.legs)
        exit_commission = self.commission_per_leg * num_legs * pos.contracts
        pnl -= exit_commission

        self.capital += pnl
        pos.realized_pnl = pnl
        pos.exit_date = snapshot.date
        pos.exit_reason = action.value

        if pos in self.open_positions:
            self.open_positions.remove(pos)
        self.closed_trades.append(pos)

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

    def _compute_exit_pnl(
        self,
        pos: Position,
        action: PositionAction,
        price: float,
        iv: float,
        current_date: datetime,
    ) -> float:
        """Compute mid-trade P&L for non-expiration exits."""
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

        is_credit = pos.net_credit > 0

        if is_credit:
            # Credit spread P&L using profit target / stop loss heuristic
            if action == PositionAction.CLOSE_PROFIT:
                pnl = pos.net_credit * pos.profit_target_pct * pos.contracts * 100
            elif action == PositionAction.CLOSE_STOP:
                pnl = -(pos.net_credit * pos.stop_loss_pct) * pos.contracts * 100
            else:
                # Mark-to-market via BS
                current_value = estimate_spread_value(
                    pos, price, iv, current_date, DEFAULT_RISK_FREE_RATE,
                )
                # For short spreads: we collected net_credit, now cost is -current_value
                pnl = (pos.net_credit + current_value) * pos.contracts * 100
        else:
            # Debit spread P&L
            if action == PositionAction.CLOSE_PROFIT:
                pnl = abs(pos.net_credit) * pos.profit_target_pct * pos.contracts * 100
            elif action == PositionAction.CLOSE_STOP:
                pnl = -(abs(pos.net_credit) * pos.stop_loss_pct) * pos.contracts * 100
            else:
                # Mark-to-market via BS
                current_value = estimate_spread_value(
                    pos, price, iv, current_date, DEFAULT_RISK_FREE_RATE,
                )
                # For long spreads: we paid |net_credit|, now it's worth current_value
                pnl = (current_value - abs(pos.net_credit)) * pos.contracts * 100

        return pnl

    # ------------------------------------------------------------------
    # Equity Tracking
    # ------------------------------------------------------------------

    def _record_equity(self, date: datetime) -> None:
        """Record end-of-day equity (cash + unrealized position value)."""
        # For simplicity, use cash as equity (unrealized P&L is complex to
        # estimate daily across all position types).  Open position risk is
        # already reflected in capital via debit deductions.
        self.equity_curve.append((date, self.capital))

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
