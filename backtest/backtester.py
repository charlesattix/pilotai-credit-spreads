"""
Backtesting Engine
Tests credit spread strategies against historical data using real option prices.
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from shared.scheduler import SCAN_TIMES

logger = logging.getLogger(__name__)

# Scan times that have actual option bars (9:15 is pre-open; bars start at 9:30)
_FIRST_BAR_HOUR = 9
_FIRST_BAR_MINUTE = 30


def _nearest_friday_expiration(
    date: datetime, target_dte: int = 35, min_dte: int = 25
) -> datetime:
    """Return the nearest Friday options expiration around *target_dte* days out.

    Options expire on Fridays (weeklies / monthlies).  A naive
    ``date + timedelta(35)`` usually lands on a weekday with no contracts,
    causing ``get_available_strikes`` to return nothing.  This function snaps
    to the Friday closest to the target, ensuring at least *min_dte* days of
    time value remain.

    Args:
        date: Entry / evaluation date.
        target_dte: Desired days-to-expiration (default 35).
        min_dte: Minimum acceptable DTE (default 25).

    Returns:
        A datetime set to midnight of the target Friday.
    """
    target = date + timedelta(days=target_dte)
    # (weekday - 4) % 7: number of days since the most-recent Friday
    days_since_friday = (target.weekday() - 4) % 7
    friday_before = target - timedelta(days=days_since_friday)
    friday_after = friday_before + timedelta(days=7)

    min_exp = date + timedelta(days=min_dte)

    # Prefer the closer Friday; fall through to friday_after if too soon
    if days_since_friday <= 3 and friday_before >= min_exp:
        return friday_before
    return friday_after


class Backtester:
    """
    Backtest credit spread strategies on historical data.

    When an ``HistoricalOptionsData`` instance is provided, real Polygon
    option prices are used for entry credits, daily marks, and exit P&L.
    Otherwise falls back to the legacy heuristic mode (for quick testing).
    """

    def __init__(self, config: Dict, historical_data=None, otm_pct: float = 0.05):
        """
        Initialize backtester.

        Args:
            config: Configuration dictionary
            historical_data: Optional HistoricalOptionsData instance for
                             real pricing.  None = legacy heuristic mode.
            otm_pct: How far OTM the short strike is as a fraction of price
                     (default 0.05 = 5% OTM).  Applies to both puts and calls.
        """
        self.config = config
        self.backtest_config = config['backtest']
        self.strategy_params = config['strategy']
        self.risk_params = config['risk']

        self.starting_capital = self.backtest_config['starting_capital']
        self.commission = self.backtest_config['commission_per_contract']
        self.slippage = self.backtest_config['slippage']
        self.otm_pct = otm_pct

        self.historical_data = historical_data
        self._use_real_data = historical_data is not None

        # Trade history
        self.trades = []
        self.equity_curve = []

        mode = "real data" if self._use_real_data else "heuristic"
        logger.info("Backtester initialized (%s mode)", mode)

    def run_backtest(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict:
        """
        Run backtest for a ticker over date range.

        Args:
            ticker: Stock ticker
            start_date: Start date for backtest
            end_date: End date for backtest

        Returns:
            Dictionary with backtest results
        """
        logger.info(f"Starting backtest for {ticker}: {start_date} to {end_date}")

        # Fetch 30 extra calendar days before start so the MA20 is valid on day 1
        # (MA20 needs 20 trading days ≈ 28 calendar days of history)
        _MA_WARMUP_DAYS = 30
        data_fetch_start = start_date - timedelta(days=_MA_WARMUP_DAYS)

        # Get historical price data (with MA warmup prefix)
        price_data = self._get_historical_data(ticker, data_fetch_start, end_date)

        if price_data.empty:
            logger.error(f"No historical data for {ticker}")
            return {}

        # Strip timezone for consistent date-only comparison
        start_date = start_date.replace(tzinfo=None) if hasattr(start_date, 'tzinfo') and start_date.tzinfo else start_date
        end_date = end_date.replace(tzinfo=None) if hasattr(end_date, 'tzinfo') and end_date.tzinfo else end_date

        # Initialize portfolio
        self.capital = self.starting_capital
        self.trades = []
        self.equity_curve = [(start_date, self.capital)]

        open_positions = []

        if price_data.index.tz is not None:
            price_data.index = price_data.index.tz_localize(None)
        trading_dates = set(price_data.index)

        # Simulate trading day by day — start at backtest start, not the warmup prefix
        current_date = start_date

        while current_date <= end_date:
            lookup_date = pd.Timestamp(current_date.date())

            if lookup_date not in trading_dates:
                current_date += timedelta(days=1)
                continue

            current_price = float(price_data.loc[lookup_date, 'Close'])

            logger.debug(
                "%s  price=%.2f  open_positions=%d",
                current_date.strftime("%Y-%m-%d"), current_price, len(open_positions),
            )

            # Check existing positions
            open_positions = self._manage_positions(
                open_positions, current_date, current_price, ticker
            )

            # Look for new opportunities.
            # Real-data mode: simulate all 14 intraday scan times per trading day.
            # Heuristic mode: one scan per week on Monday (backward compat).

            # Drawdown circuit breaker: pause NEW entries when account is down >20%
            # from starting capital (prevents going to negative balance with fixed sizing).
            _drawdown_pct = (self.capital - self.starting_capital) / self.starting_capital
            _skip_new_entries = _drawdown_pct < -0.20

            _ic_enabled = self.strategy_params.get('iron_condor', {}).get('enabled', False)

            if self._use_real_data:
                for scan_hour, scan_minute in SCAN_TIMES:
                    if _skip_new_entries:
                        break
                    if len(open_positions) >= self.risk_params['max_positions']:
                        break
                    new_position = self._find_backtest_opportunity(
                        ticker, current_date, current_price, price_data,
                        scan_hour=scan_hour, scan_minute=scan_minute,
                    )
                    if new_position:
                        open_positions.append(new_position)
                        continue
                    if len(open_positions) >= self.risk_params['max_positions']:
                        break
                    bear_call = self._find_bear_call_opportunity(
                        ticker, current_date, current_price, price_data,
                        scan_hour=scan_hour, scan_minute=scan_minute,
                    )
                    if bear_call:
                        open_positions.append(bear_call)
                        continue
                    # Iron condor fallback — only if enabled in config
                    if _ic_enabled and len(open_positions) < self.risk_params['max_positions']:
                        condor = self._find_iron_condor_opportunity(
                            ticker, current_date, current_price, scan_hour, scan_minute,
                        )
                        if condor:
                            open_positions.append(condor)
            else:
                # Heuristic mode: one opportunity scan per week on Monday
                if current_date.weekday() == 0:
                    if len(open_positions) < self.risk_params['max_positions']:
                        new_position = self._find_backtest_opportunity(
                            ticker, current_date, current_price, price_data
                        )
                        if new_position:
                            open_positions.append(new_position)

                        if not new_position and len(open_positions) < self.risk_params['max_positions']:
                            bear_call = self._find_bear_call_opportunity(
                                ticker, current_date, current_price, price_data
                            )
                            if bear_call:
                                open_positions.append(bear_call)
                            elif _ic_enabled and self._use_real_data:
                                if len(open_positions) < self.risk_params['max_positions']:
                                    condor = self._find_iron_condor_opportunity(
                                        ticker, current_date, current_price,
                                    )
                                    if condor:
                                        open_positions.append(condor)

            # Record equity
            position_value = sum(pos.get('current_value', 0) for pos in open_positions)
            total_equity = self.capital + position_value
            self.equity_curve.append((current_date, total_equity))

            current_date += timedelta(days=1)

        # Close any remaining positions
        for pos in open_positions:
            if self._use_real_data:
                # Mark-to-market using the final daily close spread value
                self._close_at_expiration_real(pos, end_date)
            else:
                self._close_position(pos, end_date, current_price, 'backtest_end')

        # Calculate performance metrics
        results = self._calculate_results()

        if self._use_real_data:
            logger.info(
                "Backtest complete. Total trades: %d, API calls: %d",
                len(self.trades), self.historical_data.api_calls_made,
            )
        else:
            logger.info(f"Backtest complete. Total trades: {len(self.trades)}")

        return results

    def _get_historical_data(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """Retrieve historical price data."""
        try:
            stock = yf.Ticker(ticker)
            data = stock.history(start=start_date, end=end_date)
            return data
        except Exception as e:
            logger.error(f"Error getting historical data: {e}", exc_info=True)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Opportunity finding
    # ------------------------------------------------------------------

    def _find_backtest_opportunity(
        self,
        ticker: str,
        date: datetime,
        price: float,
        price_data: pd.DataFrame,
        scan_hour: Optional[int] = None,
        scan_minute: Optional[int] = None,
    ) -> Optional[Dict]:
        """Find a bull put spread opportunity."""
        recent_data = price_data.loc[:date].tail(50)

        if len(recent_data) < 20:
            return None

        ma20 = recent_data['Close'].rolling(20).mean().iloc[-1]

        if price < ma20:
            return None

        # Expiration: nearest Friday around 35 DTE (options only expire on Fridays)
        expiration = _nearest_friday_expiration(date)
        date_str = date.strftime("%Y-%m-%d")
        spread_width = self.strategy_params['spread_width']

        if self._use_real_data:
            return self._find_real_spread(
                ticker, date, date_str, price, expiration,
                spread_width, option_type="P",
                scan_hour=scan_hour, scan_minute=scan_minute,
            )
        else:
            return self._find_heuristic_spread(
                ticker, date, price, expiration, spread_width, spread_type="bull_put_spread",
            )

    def _find_bear_call_opportunity(
        self,
        ticker: str,
        date: datetime,
        price: float,
        price_data: pd.DataFrame,
        scan_hour: Optional[int] = None,
        scan_minute: Optional[int] = None,
    ) -> Optional[Dict]:
        """Find a bear call spread opportunity (bearish/neutral trend)."""
        recent_data = price_data.loc[:date].tail(50)

        if len(recent_data) < 20:
            return None

        ma20 = recent_data['Close'].rolling(20).mean().iloc[-1]

        if price > ma20:
            # Price above MA — bullish, skip bear calls
            return None

        expiration = _nearest_friday_expiration(date)
        date_str = date.strftime("%Y-%m-%d")
        spread_width = self.strategy_params['spread_width']

        if self._use_real_data:
            return self._find_real_spread(
                ticker, date, date_str, price, expiration,
                spread_width, option_type="C",
                scan_hour=scan_hour, scan_minute=scan_minute,
            )
        else:
            return self._find_heuristic_spread(
                ticker, date, price, expiration, spread_width, spread_type="bear_call_spread",
            )

    def _find_iron_condor_opportunity(
        self,
        ticker: str,
        date: datetime,
        price: float,
        scan_hour: Optional[int] = None,
        scan_minute: Optional[int] = None,
    ) -> Optional[Dict]:
        """Find an iron condor (put spread + call spread) as a fallback.

        No MA20 direction check — condors are direction-neutral.  Used only
        when neither a bull put nor bear call passes its individual credit
        minimum.  Requires real data mode.
        """
        if not self._use_real_data:
            return None

        expiration = _nearest_friday_expiration(date)
        date_str = date.strftime("%Y-%m-%d")
        spread_width = self.strategy_params['spread_width']

        # Fetch each leg — bypass individual min_credit (checked on combined below)
        put_leg = self._find_real_spread(
            ticker, date, date_str, price, expiration,
            spread_width, option_type="P",
            scan_hour=scan_hour, scan_minute=scan_minute,
            min_credit_override=0.0, skip_commission=True,
        )
        if put_leg is None:
            return None

        call_leg = self._find_real_spread(
            ticker, date, date_str, price, expiration,
            spread_width, option_type="C",
            scan_hour=scan_hour, scan_minute=scan_minute,
            min_credit_override=0.0, skip_commission=True,
        )
        if call_leg is None:
            return None

        # Validate non-overlapping strikes
        if put_leg['short_strike'] >= call_leg['short_strike']:
            logger.debug(
                "IC legs overlap: put_short=%.0f >= call_short=%.0f on %s — skipping",
                put_leg['short_strike'], call_leg['short_strike'], date_str,
            )
            return None

        put_credit = put_leg['credit']   # already net of slippage
        call_credit = call_leg['credit']  # already net of slippage
        combined_credit = put_credit + call_credit

        # Combined credit minimum check
        min_combined_credit_pct = self.strategy_params.get('iron_condor', {}).get(
            'min_combined_credit_pct', 20
        )
        min_combined_credit = spread_width * (min_combined_credit_pct / 100)
        if combined_credit < min_combined_credit:
            logger.debug(
                "IC combined credit $%.2f below minimum $%.2f (%.0f%% of $%.0fw) on %s — skipping",
                combined_credit, min_combined_credit, min_combined_credit_pct,
                spread_width, date_str,
            )
            return None

        stop_loss_multiplier = self.risk_params['stop_loss_multiplier']
        commission_cost = self.commission * 4  # 4 legs (entry)
        max_loss = spread_width - combined_credit  # only one wing can fully lose

        risk_per_spread = max_loss * 100
        if risk_per_spread <= 0:
            return None

        max_risk = self.starting_capital * (self.risk_params['max_risk_per_trade'] / 100)
        max_contracts_cap = self.risk_params.get('max_contracts', 999)
        contracts = max(1, min(max_contracts_cap, int(max_risk / risk_per_spread)))

        scan_time_mins = (scan_hour or 0) * 60 + (scan_minute or 0)
        market_open_mins = _FIRST_BAR_HOUR * 60 + _FIRST_BAR_MINUTE
        use_intraday = (
            scan_hour is not None
            and scan_minute is not None
            and scan_time_mins >= market_open_mins
        )
        slippage_applied = (
            put_leg.get('slippage_applied', 0.0) + call_leg.get('slippage_applied', 0.0)
        )

        position = {
            'ticker': ticker,
            'type': 'iron_condor',
            'entry_date': date,
            'expiration': expiration,
            # Put spread leg (backward compat with _record_close)
            'short_strike': put_leg['short_strike'],
            'long_strike': put_leg['long_strike'],
            # Call spread leg
            'call_short_strike': call_leg['short_strike'],
            'call_long_strike': call_leg['long_strike'],
            # Credits
            'put_credit': put_credit,
            'call_credit': call_credit,
            'credit': combined_credit,
            'contracts': contracts,
            'max_loss': max_loss,
            'profit_target': combined_credit * 0.5,
            'stop_loss': combined_credit * stop_loss_multiplier,
            'commission': commission_cost,  # exit commission (4 legs)
            'status': 'open',
            'option_type': 'IC',
            'current_value': combined_credit * contracts * 100,
            'entry_scan_time': f"{scan_hour:02d}:{scan_minute:02d}" if use_intraday else None,
            'slippage_applied': slippage_applied,
        }

        self.capital -= commission_cost  # entry commission

        logger.debug(
            "Opened iron_condor: %s put=%s/%s call=%s/%s credit=$%.2f (%d contracts)%s",
            ticker,
            put_leg['short_strike'], put_leg['long_strike'],
            call_leg['short_strike'], call_leg['long_strike'],
            combined_credit, contracts,
            f" @ {position['entry_scan_time']} ET" if use_intraday else "",
        )

        return position

    def _find_real_spread(
        self,
        ticker: str,
        date: datetime,
        date_str: str,
        price: float,
        expiration: datetime,
        spread_width: float,
        option_type: str,
        scan_hour: Optional[int] = None,
        scan_minute: Optional[int] = None,
        min_credit_override: Optional[float] = None,
        skip_commission: bool = False,
    ) -> Optional[Dict]:
        """Find a spread using real historical option prices from Polygon.

        When scan_hour/scan_minute are provided, uses 5-min intraday bars for
        entry pricing and models slippage from the actual bar bid/ask spread
        width (bar high - bar low).  Falls back to daily close when no scan
        time is given (legacy daily mode).
        """
        exp_str = expiration.strftime("%Y-%m-%d")
        ot = option_type[0].upper()

        # Discover available strikes
        strikes = self.historical_data.get_available_strikes(
            ticker, exp_str, date_str, option_type=ot,
        )

        if not strikes:
            logger.debug("No strikes available for %s exp %s on %s", ticker, exp_str, date_str)
            return None

        # Pick short strike OTM by self.otm_pct (default 5%)
        if ot == "P":
            target_short = price * (1 - self.otm_pct)
            candidates = [s for s in strikes if s <= target_short]
            if not candidates:
                return None
            short_strike = max(candidates)
            long_strike = short_strike - spread_width
            spread_type = "bull_put_spread"
        else:
            target_short = price * (1 + self.otm_pct)
            candidates = [s for s in strikes if s >= target_short]
            if not candidates:
                return None
            short_strike = min(candidates)
            long_strike = short_strike + spread_width
            spread_type = "bear_call_spread"

        # Use intraday pricing only when a scan time is given AND options are open
        # (options market opens at 9:30 ET; the 9:15 scan runs pre-open)
        scan_time_mins = (scan_hour or 0) * 60 + (scan_minute or 0)
        market_open_mins = _FIRST_BAR_HOUR * 60 + _FIRST_BAR_MINUTE  # 9:30 = 570
        use_intraday = (
            scan_hour is not None
            and scan_minute is not None
            and scan_time_mins >= market_open_mins
        )

        def _get_prices(ss: float, ls: float) -> Optional[Dict]:
            if use_intraday:
                return self.historical_data.get_intraday_spread_prices(
                    ticker, expiration, ss, ls, ot,
                    date_str, scan_hour, scan_minute,
                )
            return self.historical_data.get_spread_prices(
                ticker, expiration, ss, ls, ot, date_str,
            )

        prices = _get_prices(short_strike, long_strike)

        if prices is None:
            # Try adjacent strikes (+/- $1)
            for offset in [1, -1, 2, -2]:
                alt_short = short_strike + offset
                alt_long = alt_short - spread_width if ot == "P" else alt_short + spread_width
                prices = _get_prices(alt_short, alt_long)
                if prices is not None:
                    short_strike = alt_short
                    long_strike = alt_long
                    break

        if prices is None:
            logger.debug(
                "No %s price data for spread %s %s/%s on %s",
                "intraday" if use_intraday else "daily",
                ticker, short_strike, long_strike, date_str,
            )
            return None

        credit = prices["spread_value"]

        if credit <= 0:
            return None

        # Minimum credit filter
        if min_credit_override is not None:
            min_credit = min_credit_override
        else:
            min_credit_pct = self.strategy_params.get('min_credit_pct', 15) / 100
            min_credit = spread_width * min_credit_pct
        if credit < min_credit:
            scan_tag = f" [{scan_hour:02d}:{scan_minute:02d} ET]" if use_intraday else ""
            logger.debug(
                "Credit $%.2f below minimum $%.2f on %s%s — skipping",
                credit, min_credit, date_str, scan_tag,
            )
            return None

        # Slippage: use bid/ask-modeled value from intraday bar, or config flat value
        slippage = prices.get("slippage", self.slippage)
        credit -= slippage
        if credit <= 0:
            return None

        commission_cost = self.commission * 2  # Two legs

        max_loss = spread_width - credit

        risk_per_spread = max_loss * 100
        if risk_per_spread <= 0:
            return None
        # Fixed sizing: use starting_capital (not current capital) so compounding
        # doesn't inflate later trades — each trade risks the same dollar amount.
        max_risk = self.starting_capital * (self.risk_params['max_risk_per_trade'] / 100)
        max_contracts_cap = self.risk_params.get('max_contracts', 999)
        contracts = max(1, min(max_contracts_cap, int(max_risk / risk_per_spread)))

        position = {
            'ticker': ticker,
            'type': spread_type,
            'entry_date': date,
            'expiration': expiration,
            'short_strike': short_strike,
            'long_strike': long_strike,
            'credit': credit,
            'contracts': contracts,
            'max_loss': max_loss,
            'profit_target': credit * 0.5,
            'stop_loss': credit * self.risk_params['stop_loss_multiplier'],
            'commission': commission_cost,
            'status': 'open',
            'current_value': credit * contracts * 100,
            'option_type': ot,
            'entry_scan_time': f"{scan_hour:02d}:{scan_minute:02d}" if use_intraday else None,
            'slippage_applied': slippage,
        }

        if not skip_commission:
            self.capital -= commission_cost

        logger.debug(
            "Opened %s: %s %s/%s credit=$%.2f slippage=$%.3f (%d contracts)%s",
            spread_type, ticker, short_strike, long_strike, credit, slippage, contracts,
            f" @ {position['entry_scan_time']} ET" if use_intraday else "",
        )

        return position

    def _find_heuristic_spread(
        self,
        ticker: str,
        date: datetime,
        price: float,
        expiration: datetime,
        spread_width: float,
        spread_type: str,
    ) -> Optional[Dict]:
        """Legacy heuristic spread finding (no real options data)."""
        from shared.constants import BACKTEST_SHORT_STRIKE_OTM_FRACTION, BACKTEST_CREDIT_FRACTION

        if spread_type == "bull_put_spread":
            short_strike = price * BACKTEST_SHORT_STRIKE_OTM_FRACTION
            long_strike = short_strike - spread_width
            ot = "P"
        else:
            short_strike = price * (2 - BACKTEST_SHORT_STRIKE_OTM_FRACTION)  # ~1.10
            long_strike = short_strike + spread_width
            ot = "C"

        credit = spread_width * BACKTEST_CREDIT_FRACTION
        credit -= self.slippage
        commission_cost = self.commission * 2

        max_loss = spread_width - credit

        risk_per_spread = max_loss * 100
        max_risk = self.capital * (self.risk_params['max_risk_per_trade'] / 100)
        contracts = max(1, int(max_risk / risk_per_spread))

        position = {
            'ticker': ticker,
            'type': spread_type,
            'entry_date': date,
            'expiration': expiration,
            'short_strike': short_strike,
            'long_strike': long_strike,
            'credit': credit,
            'contracts': contracts,
            'max_loss': max_loss,
            'profit_target': credit * 0.5,
            'stop_loss': credit * self.risk_params['stop_loss_multiplier'],
            'commission': commission_cost,
            'status': 'open',
            'current_value': credit * contracts * 100,
            'option_type': ot,
        }

        self.capital -= commission_cost

        logger.debug(f"Opened position: {ticker} {spread_type} @ ${short_strike:.2f}")

        return position

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def _check_intraday_exits(
        self,
        pos: Dict,
        current_date: datetime,
        date_str: str,
    ) -> Optional[Tuple]:
        """Check 30-min intraday scan times for stop/profit triggers.

        Mirrors the live scanner's 30-min cadence (SCAN_TIMES) so backtest
        exit granularity matches live trading behavior.

        On the entry day, bars at or before entry_scan_time are skipped to
        avoid acting on data that predates the position's opening.

        Returns:
            ('profit_target'|'stop_loss', spread_value) if triggered
            ('no_trigger', last_spread_value)            if data found but no trigger
            None                                         if no intraday data (fall back to daily close)
        """
        entry_scan_time = pos.get('entry_scan_time')  # e.g. "10:30"
        is_entry_day = current_date.date() == pos['entry_date'].date()

        entry_mins = None
        if entry_scan_time and is_entry_day:
            h, m = entry_scan_time.split(':')
            entry_mins = int(h) * 60 + int(m)

        had_any_data = False
        last_spread_value = None

        for scan_hour, scan_minute in SCAN_TIMES:
            # Skip 9:15 — options don't open until 9:30
            if scan_hour == _FIRST_BAR_HOUR and scan_minute < _FIRST_BAR_MINUTE:
                continue

            # On entry day, skip scan times at or before the entry scan time
            if entry_mins is not None:
                if scan_hour * 60 + scan_minute <= entry_mins:
                    continue

            if pos['type'] == 'iron_condor':
                put_prices = self.historical_data.get_intraday_spread_prices(
                    pos['ticker'], pos['expiration'],
                    pos['short_strike'], pos['long_strike'], 'P',
                    date_str, scan_hour, scan_minute,
                )
                call_prices = self.historical_data.get_intraday_spread_prices(
                    pos['ticker'], pos['expiration'],
                    pos['call_short_strike'], pos['call_long_strike'], 'C',
                    date_str, scan_hour, scan_minute,
                )
                if put_prices is None or call_prices is None:
                    continue
                spread_value = put_prices['spread_value'] + call_prices['spread_value']
            else:
                ot = pos.get('option_type', 'P')
                prices = self.historical_data.get_intraday_spread_prices(
                    pos['ticker'], pos['expiration'],
                    pos['short_strike'], pos['long_strike'], ot,
                    date_str, scan_hour, scan_minute,
                )
                if prices is None:
                    continue
                spread_value = prices['spread_value']

            had_any_data = True
            last_spread_value = spread_value

            if pos['credit'] - spread_value >= pos['profit_target']:
                return ('profit_target', spread_value)
            if spread_value - pos['credit'] >= pos['stop_loss']:
                return ('stop_loss', spread_value)

        if not had_any_data:
            return None  # No intraday data — caller falls back to daily close
        return ('no_trigger', last_spread_value)

    def _manage_positions(
        self,
        positions: List[Dict],
        current_date: datetime,
        current_price: float,
        ticker: str = "",
    ) -> List[Dict]:
        """Manage open positions — check for exits."""
        remaining_positions = []

        for pos in positions:
            # Check if expired
            if current_date >= pos['expiration']:
                if self._use_real_data:
                    self._close_at_expiration_real(pos, current_date)
                else:
                    if current_price > pos['short_strike']:
                        self._close_position(pos, current_date, current_price, 'expiration_profit')
                    else:
                        self._close_position(pos, current_date, current_price, 'expiration_loss')
                continue

            # Check spread value
            date_str = current_date.strftime("%Y-%m-%d")

            if self._use_real_data:
                # Try intraday exits first (30-min scan granularity matching live scanner)
                intraday_result = self._check_intraday_exits(pos, current_date, date_str)
                if intraday_result is not None:
                    reason, spread_value = intraday_result
                    if reason in ('profit_target', 'stop_loss'):
                        pnl = (pos['credit'] - spread_value) * pos['contracts'] * 100 - pos['commission']
                        self._record_close(pos, current_date, pnl, reason)
                        continue
                    # 'no_trigger' — had intraday data but no exit; skip daily close check
                    pos['current_value'] = -spread_value * pos['contracts'] * 100
                    remaining_positions.append(pos)
                    continue

                # No intraday data available — fall back to daily close check
                if pos['type'] == 'iron_condor':
                    put_prices = self.historical_data.get_spread_prices(
                        pos['ticker'], pos['expiration'],
                        pos['short_strike'], pos['long_strike'], 'P', date_str,
                    )
                    call_prices = self.historical_data.get_spread_prices(
                        pos['ticker'], pos['expiration'],
                        pos['call_short_strike'], pos['call_long_strike'], 'C', date_str,
                    )
                    if put_prices is None or call_prices is None:
                        remaining_positions.append(pos)
                        continue
                    current_spread_value = put_prices['spread_value'] + call_prices['spread_value']
                else:
                    ot = pos.get('option_type', 'P')
                    prices = self.historical_data.get_spread_prices(
                        pos['ticker'], pos['expiration'],
                        pos['short_strike'], pos['long_strike'],
                        ot, date_str,
                    )

                    if prices is None:
                        # No data for today — keep position, don't mark
                        remaining_positions.append(pos)
                        continue

                    current_spread_value = prices["spread_value"]
            else:
                dte = (pos['expiration'] - current_date).days
                current_spread_value = self._estimate_spread_value(pos, current_price, dte)

            # P&L check: profit = credit - current spread value (daily close fallback)
            profit = pos['credit'] - current_spread_value

            if profit >= pos['profit_target']:
                if self._use_real_data:
                    # Real exit debit = current spread value
                    pnl = (pos['credit'] - current_spread_value) * pos['contracts'] * 100 - pos['commission']
                    self._record_close(pos, current_date, pnl, 'profit_target')
                else:
                    self._close_position(pos, current_date, current_price, 'profit_target')
                continue

            loss = current_spread_value - pos['credit']
            if loss >= pos['stop_loss']:
                if self._use_real_data:
                    pnl = (pos['credit'] - current_spread_value) * pos['contracts'] * 100 - pos['commission']
                    self._record_close(pos, current_date, pnl, 'stop_loss')
                else:
                    self._close_position(pos, current_date, current_price, 'stop_loss')
                continue

            # Update current value
            pos['current_value'] = -current_spread_value * pos['contracts'] * 100

            remaining_positions.append(pos)

        return remaining_positions

    def _close_at_expiration_real(self, pos: Dict, expiration_date: datetime):
        """Close a position at expiration using real prices."""
        date_str = expiration_date.strftime("%Y-%m-%d")

        if pos['type'] == 'iron_condor':
            put_prices = self.historical_data.get_spread_prices(
                pos['ticker'], pos['expiration'],
                pos['short_strike'], pos['long_strike'], 'P', date_str,
            )
            call_prices = self.historical_data.get_spread_prices(
                pos['ticker'], pos['expiration'],
                pos['call_short_strike'], pos['call_long_strike'], 'C', date_str,
            )
            if put_prices is not None and call_prices is not None:
                closing_spread_value = put_prices['spread_value'] + call_prices['spread_value']
                if closing_spread_value > 0.05:
                    pnl = (pos['credit'] - closing_spread_value) * pos['contracts'] * 100 - pos['commission']
                    reason = 'expiration_loss' if pnl < 0 else 'expiration_profit'
                else:
                    pnl = pos['credit'] * pos['contracts'] * 100 - pos['commission']
                    reason = 'expiration_profit'
            else:
                pnl = pos['credit'] * pos['contracts'] * 100 - pos['commission']
                reason = 'expiration_profit'
            self._record_close(pos, expiration_date, pnl, reason)
            return

        ot = pos.get('option_type', 'P')
        prices = self.historical_data.get_spread_prices(
            pos['ticker'], pos['expiration'],
            pos['short_strike'], pos['long_strike'],
            ot, date_str,
        )

        if prices is not None:
            closing_spread_value = prices["spread_value"]
            # If short leg still has value > 0.05, it's a loss scenario
            if closing_spread_value > 0.05:
                pnl = (pos['credit'] - closing_spread_value) * pos['contracts'] * 100 - pos['commission']
                reason = 'expiration_loss' if pnl < 0 else 'expiration_profit'
            else:
                # Expired worthless — max profit
                pnl = pos['credit'] * pos['contracts'] * 100 - pos['commission']
                reason = 'expiration_profit'
        else:
            # No data at expiration — assume expired worthless
            pnl = pos['credit'] * pos['contracts'] * 100 - pos['commission']
            reason = 'expiration_profit'

        self._record_close(pos, expiration_date, pnl, reason)

    def _record_close(self, pos: Dict, exit_date: datetime, pnl: float, reason: str):
        """Record a closed position (used by real-data mode)."""
        self.capital += pnl

        max_risk = pos['max_loss'] * pos['contracts'] * 100
        trade = {
            'ticker': pos['ticker'],
            'type': pos['type'],
            'entry_date': pos['entry_date'],
            'exit_date': exit_date,
            'exit_reason': reason,
            'short_strike': pos['short_strike'],
            'long_strike': pos['long_strike'],
            'credit': pos['credit'],
            'contracts': pos['contracts'],
            'pnl': pnl,
            'return_pct': (pnl / max_risk) * 100 if max_risk != 0 else 0,
            'entry_scan_time': pos.get('entry_scan_time'),
            'slippage_applied': pos.get('slippage_applied', 0.0),
        }

        self.trades.append(trade)
        logger.debug("Closed position: %s, P&L: $%.2f", reason, pnl)

    # ------------------------------------------------------------------
    # Legacy heuristic methods (used when historical_data is None)
    # ------------------------------------------------------------------

    def _estimate_spread_value(
        self,
        position: Dict,
        current_price: float,
        dte: int,
    ) -> float:
        """Estimate current value of spread (simplified heuristic).

        Only used in legacy mode when no real options data is available.
        """
        short_strike = position['short_strike']
        spread_width = position['short_strike'] - position['long_strike']

        # For bear call spreads, spread_width is negative — use absolute
        spread_width = abs(spread_width)

        OTM_BUFFER = 0.05
        ITM_BUFFER = 0.05
        TYPICAL_DTE = 35
        ITM_EXTRINSIC_FRAC = 0.3
        NTM_EXTRINSIC_FRAC = 0.7
        ITM_DISTANCE_MULT = 2

        is_put = position.get('type', 'bull_put_spread') == 'bull_put_spread'

        if is_put:
            otm = current_price > short_strike * (1 + OTM_BUFFER)
            itm = current_price < short_strike * (1 - ITM_BUFFER)
        else:
            otm = current_price < short_strike * (1 - OTM_BUFFER)
            itm = current_price > short_strike * (1 + ITM_BUFFER)

        if otm:
            decay_factor = max(0, dte / TYPICAL_DTE)
            value = position['credit'] * decay_factor * ITM_EXTRINSIC_FRAC
        elif itm:
            if is_put:
                distance = (short_strike - current_price) / short_strike
            else:
                distance = (current_price - short_strike) / short_strike
            value = spread_width * min(1.0, distance * ITM_DISTANCE_MULT)
        else:
            time_factor = dte / TYPICAL_DTE
            value = position['credit'] * NTM_EXTRINSIC_FRAC * time_factor

        return max(0, value)

    def _close_position(
        self,
        position: Dict,
        exit_date: datetime,
        exit_price: float,
        exit_reason: str,
    ):
        """Close a position and record trade (legacy heuristic mode)."""
        if exit_reason == 'expiration_profit':
            pnl = position['credit'] * position['contracts'] * 100
        elif exit_reason == 'expiration_loss':
            pnl = -position['max_loss'] * position['contracts'] * 100
        elif exit_reason == 'profit_target':
            pnl = position['profit_target'] * position['contracts'] * 100
        elif exit_reason == 'stop_loss':
            pnl = -position['stop_loss'] * position['contracts'] * 100
        else:
            pnl = 0

        pnl -= position['commission']

        self.capital += pnl

        trade = {
            'ticker': position['ticker'],
            'type': position['type'],
            'entry_date': position['entry_date'],
            'exit_date': exit_date,
            'exit_reason': exit_reason,
            'short_strike': position['short_strike'],
            'long_strike': position['long_strike'],
            'credit': position['credit'],
            'contracts': position['contracts'],
            'pnl': pnl,
            'return_pct': (pnl / (position['max_loss'] * position['contracts'] * 100)) * 100 if (position['max_loss'] * position['contracts']) != 0 else 0,
        }

        self.trades.append(trade)

        logger.debug(f"Closed position: {exit_reason}, P&L: ${pnl:.2f}")

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def _calculate_results(self) -> Dict:
        """Calculate backtest performance metrics."""
        if not self.trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_factor': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'starting_capital': self.starting_capital,
                'ending_capital': self.capital,
                'return_pct': 0,
                'trades': [],
                'equity_curve': [],
                'bull_put_trades': 0,
                'bear_call_trades': 0,
                'bull_put_win_rate': 0,
                'bear_call_win_rate': 0,
                'iron_condor_trades': 0,
                'iron_condor_win_rate': 0,
            }

        trades_df = pd.DataFrame(self.trades)

        # Basic stats
        total_trades = len(trades_df)
        winners = trades_df[trades_df['pnl'] > 0]
        losers = trades_df[trades_df['pnl'] < 0]

        win_rate = (len(winners) / total_trades) * 100 if total_trades > 0 else 0

        total_pnl = trades_df['pnl'].sum()
        avg_win = winners['pnl'].mean() if len(winners) > 0 else 0
        avg_loss = abs(losers['pnl'].mean()) if len(losers) > 0 else 0

        # Per-strategy breakdown
        bull_puts = trades_df[trades_df['type'] == 'bull_put_spread']
        bear_calls = trades_df[trades_df['type'] == 'bear_call_spread']
        iron_condors = trades_df[trades_df['type'] == 'iron_condor']

        bull_put_winners = bull_puts[bull_puts['pnl'] > 0] if len(bull_puts) > 0 else pd.DataFrame()
        bear_call_winners = bear_calls[bear_calls['pnl'] > 0] if len(bear_calls) > 0 else pd.DataFrame()
        iron_condor_winners = iron_condors[iron_condors['pnl'] > 0] if len(iron_condors) > 0 else pd.DataFrame()

        bull_put_wr = (len(bull_put_winners) / len(bull_puts)) * 100 if len(bull_puts) > 0 else 0
        bear_call_wr = (len(bear_call_winners) / len(bear_calls)) * 100 if len(bear_calls) > 0 else 0
        iron_condor_wr = (len(iron_condor_winners) / len(iron_condors)) * 100 if len(iron_condors) > 0 else 0

        # Equity curve analysis
        equity_df = pd.DataFrame(self.equity_curve, columns=['date', 'equity'])
        equity_df['returns'] = equity_df['equity'].pct_change()

        # Max drawdown
        equity_df['cummax'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['cummax']) / equity_df['cummax']
        max_drawdown = equity_df['drawdown'].min() * 100

        # Sharpe ratio (annualized)
        returns = equity_df['returns'].dropna()
        if len(returns) > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        else:
            sharpe = 0

        # Profit factor
        winning_total = winners['pnl'].sum() if len(winners) > 0 else 0
        losing_total = losers['pnl'].sum() if len(losers) > 0 else 0
        if losing_total != 0:
            profit_factor = round(abs(winning_total / losing_total), 2)
        elif winning_total > 0:
            profit_factor = float('inf')
        else:
            profit_factor = 0

        # Return percentage
        if self.starting_capital != 0:
            return_pct = round(((self.capital - self.starting_capital) / self.starting_capital) * 100, 2)
        else:
            return_pct = 0

        results = {
            'total_trades': total_trades,
            'winning_trades': len(winners),
            'losing_trades': len(losers),
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': profit_factor,
            'max_drawdown': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe, 2),
            'starting_capital': self.starting_capital,
            'ending_capital': round(self.capital, 2),
            'return_pct': return_pct,
            'trades': trades_df.to_dict('records'),
            'equity_curve': equity_df.to_dict('records'),
            'bull_put_trades': len(bull_puts),
            'bear_call_trades': len(bear_calls),
            'bull_put_win_rate': round(bull_put_wr, 2),
            'bear_call_win_rate': round(bear_call_wr, 2),
            'iron_condor_trades': len(iron_condors),
            'iron_condor_win_rate': round(iron_condor_wr, 2),
        }

        return results
