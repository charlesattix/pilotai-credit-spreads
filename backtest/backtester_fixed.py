"""
FIXED Backtesting Engine - Uses REAL Strategy Logic + REAL Option Prices
========================================================================

This version properly integrates:
- strategy.evaluate_spread_opportunity() with full scoring
- ML pipeline scoring (if available)
- Technical analysis + IV filtering
- REAL historical option prices from Polygon.io (when available)
- Proper P&L based on actual option close prices

Author: Charles
Date: 2026-02-21
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class BacktesterFixed:
    """
    Backtester that uses THE SAME LOGIC as live scanning.
    
    Key difference from old backtester:
    - OLD: Just checked "price > MA20" (too simple)
    - NEW: Calls strategy.evaluate_spread_opportunity() with full ML scoring
    """

    def __init__(self, config: Dict, strategy, technical_analyzer, options_analyzer,
                 ml_pipeline=None, historical_data=None, polygon_provider=None):
        """
        Initialize fixed backtester.

        Args:
            config: Configuration dictionary
            strategy: CreditSpreadStrategy instance
            technical_analyzer: TechnicalAnalyzer instance
            options_analyzer: OptionsAnalyzer instance
            ml_pipeline: Optional MLPipeline instance
            historical_data: Optional HistoricalOptionsData instance
            polygon_provider: Optional PolygonProvider for real historical option prices
        """
        self.config = config
        self.backtest_config = config['backtest']
        self.strategy_params = config['strategy']
        self.risk_params = config['risk']

        self.starting_capital = self.backtest_config['starting_capital']
        self.commission = self.backtest_config['commission_per_contract']
        self.slippage = self.backtest_config['slippage']
        self.score_threshold = self.backtest_config.get('score_threshold', 28)

        # Strategy components (THE REAL ONES)
        self.strategy = strategy
        self.technical_analyzer = technical_analyzer
        self.options_analyzer = options_analyzer
        self.ml_pipeline = ml_pipeline
        self.historical_data = historical_data
        self.polygon_provider = polygon_provider

        # Cache for fetched spread price histories: (short_ticker, long_ticker) -> DataFrame
        self._spread_price_cache = {}

        # ML/rules blending weights
        strategy_cfg = self.config.get('strategy', {})
        self.ml_score_weight = strategy_cfg.get('ml_score_weight', 0.6)
        self.rules_score_weight = 1.0 - self.ml_score_weight
        self.event_risk_threshold = strategy_cfg.get('event_risk_threshold', 0.7)

        # Portfolio risk limits
        self.portfolio_risk = self.risk_params.get('portfolio_risk', {})

        # Rolling config
        self.enable_rolling = self.risk_params.get('enable_rolling', False)
        self.max_rolls = self.risk_params.get('max_rolls_per_position', 1)
        self.min_roll_credit = self.risk_params.get('min_roll_credit', 0.30)

        # Trade history
        self.trades = []
        self.equity_curve = []

        pricing = "REAL Polygon" if polygon_provider else "synthetic"
        mode = "real strategy" if strategy else "simplified"
        logger.info(f"BacktesterFixed initialized ({mode} mode, {pricing} pricing)")

    def run_backtest(self, ticker, start_date: datetime, end_date: datetime) -> Dict:
        """
        Run backtest using REAL strategy logic across one or more tickers.

        Args:
            ticker: Stock ticker (str) or list of tickers
            start_date: Start date
            end_date: End date

        Returns:
            Dictionary with backtest results
        """
        # Support both single ticker (backward compat) and multi-ticker
        if isinstance(ticker, str):
            tickers = [ticker]
        else:
            tickers = list(ticker)

        scan_days = set(self.risk_params.get('scan_days', [0, 2, 4]))
        max_positions = self.risk_params['max_positions']
        max_per_ticker = self.risk_params.get('max_positions_per_ticker', 2)

        logger.info(f"Starting FIXED backtest for {tickers}: {start_date} to {end_date}")
        logger.info(f"Score threshold: {self.score_threshold}, scan_days: {scan_days}, max_positions: {max_positions}")

        # Get historical price data for all tickers
        all_price_data: Dict[str, pd.DataFrame] = {}
        for t in tickers:
            pd_data = self._get_historical_data(t, start_date, end_date)
            if not pd_data.empty:
                all_price_data[t] = pd_data
            else:
                logger.warning(f"No historical data for {t}, skipping")

        if not all_price_data:
            logger.error("No historical data for any ticker")
            return {}

        # Initialize portfolio
        self.capital = self.starting_capital
        self.trades = []
        self.equity_curve = [(start_date, self.capital)]

        open_positions = []

        current_date = start_date
        scans_performed = 0
        opportunities_found = 0

        while current_date <= end_date:
            # Check if scan day (Mon/Wed/Fri by default)
            if current_date.weekday() in scan_days:
                scans_performed += 1

                # Scan each ticker for opportunities
                for scan_ticker in all_price_data:
                    if len(open_positions) >= max_positions:
                        break

                    # Enforce per-ticker limit
                    ticker_positions = [p for p in open_positions if p['ticker'] == scan_ticker]
                    if len(ticker_positions) >= max_per_ticker:
                        continue

                    price_data = all_price_data[scan_ticker]

                    # Get current price
                    try:
                        current_price_row = price_data.loc[price_data.index <= current_date].iloc[-1]
                        current_price = float(current_price_row['Close'])
                    except (IndexError, KeyError):
                        continue

                    # Look for new opportunity using REAL strategy
                    opportunity = self._find_opportunity_real_logic(
                        scan_ticker, current_date, current_price, price_data
                    )

                    if opportunity:
                        opportunities_found += 1
                        position = self._opportunity_to_position(opportunity, current_date)
                        if position and self._check_portfolio_limits(position, open_positions):
                            open_positions.append(position)
                            logger.info(
                                f"Opened {position['ticker']} {position['type']} "
                                f"@ {current_date.date()}, score={opportunity['score']:.1f}, "
                                f"credit=${position['credit']:.2f}, contracts={position['contracts']}"
                            )

            # Manage existing positions (need price data per ticker)
            remaining = []
            for pos in open_positions:
                pos_ticker = pos['ticker']
                price_data = all_price_data.get(pos_ticker)
                if price_data is None:
                    remaining.append(pos)
                    continue
                managed = self._manage_positions([pos], current_date, price_data, pos_ticker)
                remaining.extend(managed)
            open_positions = remaining

            # Record equity
            position_value = sum(pos.get('current_value', 0) for pos in open_positions)
            total_equity = self.capital + position_value
            self.equity_curve.append((current_date, total_equity))

            current_date += timedelta(days=1)

        # Close remaining positions with actual prices
        for pos in open_positions:
            pos_ticker = pos['ticker']
            price_data = all_price_data.get(pos_ticker)
            final_price = None
            if price_data is not None:
                try:
                    final_price_row = price_data.loc[price_data.index <= end_date].iloc[-1]
                    final_price = float(final_price_row['Close'])
                except (IndexError, KeyError):
                    pass

            if final_price is not None:
                spread_val = self._get_current_spread_value(pos, end_date, final_price)
                pnl_pc = pos['credit'] - spread_val
            else:
                pnl_pc = None
            self._close_position(pos, end_date, "backtest_end",
                                 underlying_price=final_price,
                                 real_pnl_per_contract=pnl_pc)

        # Calculate results
        results = self._calculate_results()
        results['scans_performed'] = scans_performed
        results['opportunities_found'] = opportunities_found
        results['tickers'] = tickers

        logger.info(f"Backtest complete: {scans_performed} scans, {opportunities_found} opportunities, {results['total_trades']} trades")

        return results

    def _check_portfolio_limits(self, new_pos: Dict, open_positions: List[Dict]) -> bool:
        """
        Check if adding a new position violates portfolio-level risk limits.

        Checks: total portfolio risk, single-ticker concentration,
        same-expiration limit, and correlation group limits.

        Returns True if position is allowed, False if it would breach limits.
        """
        if not self.portfolio_risk:
            return True

        new_risk = new_pos['max_loss'] * new_pos['contracts'] * 100

        # Check total portfolio risk
        max_pf_risk_pct = self.portfolio_risk.get('max_portfolio_risk_pct', 25)
        total_risk = sum(p['max_loss'] * p['contracts'] * 100 for p in open_positions)
        if (total_risk + new_risk) / self.capital > max_pf_risk_pct / 100:
            logger.debug(f"Portfolio risk limit: {(total_risk + new_risk)/self.capital:.1%} > {max_pf_risk_pct}%")
            return False

        # Check single-ticker concentration
        max_ticker_pct = self.portfolio_risk.get('max_single_ticker_pct', 12)
        ticker_risk = sum(
            p['max_loss'] * p['contracts'] * 100
            for p in open_positions if p['ticker'] == new_pos['ticker']
        )
        if (ticker_risk + new_risk) / self.capital > max_ticker_pct / 100:
            logger.debug(f"Ticker concentration limit for {new_pos['ticker']}")
            return False

        # Check same-expiration limit
        max_same_exp = self.portfolio_risk.get('max_same_expiration', 3)
        same_exp_count = sum(
            1 for p in open_positions
            if abs((p['expiration'] - new_pos['expiration']).days) <= 2  # same week
        )
        if same_exp_count >= max_same_exp:
            logger.debug(f"Same-expiration limit ({same_exp_count} >= {max_same_exp})")
            return False

        # Check correlation group limits
        corr_groups = self.risk_params.get('correlation_groups', {})
        new_ticker = new_pos['ticker']
        for group_name, group_cfg in corr_groups.items():
            group_tickers = group_cfg.get('tickers', [])
            if new_ticker not in group_tickers:
                continue

            max_group_pct = group_cfg.get('max_group_risk_pct', 18)
            group_risk = sum(
                p['max_loss'] * p['contracts'] * 100
                for p in open_positions if p['ticker'] in group_tickers
            )
            if (group_risk + new_risk) / self.capital > max_group_pct / 100:
                logger.debug(
                    f"Correlation group '{group_name}' limit: "
                    f"{(group_risk + new_risk)/self.capital:.1%} > {max_group_pct}%"
                )
                return False

        return True

    def _find_opportunity_real_logic(self, ticker: str, date: datetime,
                                    current_price: float, price_data: pd.DataFrame) -> Optional[Dict]:
        """
        Find opportunity using THE SAME LOGIC as live scanning.
        
        This is the KEY FIX - we now call strategy.evaluate_spread_opportunity()
        instead of just checking price > MA20.
        """
        try:
            # Get technical signals (same as live)
            technical_signals = self.technical_analyzer.analyze(ticker, price_data.loc[:date])

            # Get options chain (synthetic for now, or real if historical_data available)
            if self.historical_data:
                # TODO: Implement real historical options data lookup
                options_chain = self._get_synthetic_options_chain(ticker, date, current_price)
            else:
                options_chain = self._get_synthetic_options_chain(ticker, date, current_price)

            if options_chain.empty:
                return None

            # Calculate IV data
            current_iv = self.options_analyzer.get_current_iv(options_chain)
            iv_data = self.options_analyzer.calculate_iv_rank(ticker, current_iv)

            # Evaluate spread opportunities (THE REAL STRATEGY CALL)
            # Pass as_of_date so DTE is calculated from the backtest date, not today
            opportunities = self.strategy.evaluate_spread_opportunity(
                ticker=ticker,
                option_chain=options_chain,
                technical_signals=technical_signals,
                iv_data=iv_data,
                current_price=current_price,
                as_of_date=date  # ← KEY FIX: Use backtest date for DTE calculation
            )

            if not opportunities:
                return None

            # Enhance with ML scoring if available (same as live)
            if self.ml_pipeline:
                for opp in opportunities:
                    try:
                        spread_type = 'bull_put' if 'put' in opp.get('type', '') else 'bear_call'
                        ml_result = self.ml_pipeline.analyze_trade(
                            ticker=ticker,
                            current_price=current_price,
                            options_chain=options_chain,
                            spread_type=spread_type,
                            technical_signals=technical_signals,
                        )
                        
                        # Blend ML + rules scores
                        rules_score = opp.get('score', 50)
                        ml_score = ml_result.get('enhanced_score', rules_score)
                        opp['score'] = self.ml_score_weight * ml_score + self.rules_score_weight * rules_score
                        opp['event_risk'] = ml_result.get('event_risk', {}).get('event_risk_score', 0)

                        # Skip high event risk
                        if opp['event_risk'] > self.event_risk_threshold:
                            opp['score'] = 0
                    except Exception as e:
                        logger.warning(f"ML scoring failed, using rules-based: {e}")

            # Filter by score threshold
            valid_opps = [o for o in opportunities if o.get('score', 0) >= self.score_threshold]
            
            if not valid_opps:
                return None

            # Return top opportunity
            return max(valid_opps, key=lambda x: x.get('score', 0))

        except Exception as e:
            logger.error(f"Error finding opportunity for {ticker} on {date}: {e}")
            return None

    @staticmethod
    def _snap_to_friday(dt: datetime) -> datetime:
        """Snap a date to the nearest Friday (standard options expiration)."""
        weekday = dt.weekday()  # Mon=0 ... Sun=6
        # Friday = 4
        days_until_friday = (4 - weekday) % 7
        if days_until_friday == 0:
            return dt  # Already Friday
        if days_until_friday <= 3:
            return dt + timedelta(days=days_until_friday)  # Snap forward
        return dt - timedelta(days=(7 - days_until_friday))  # Snap backward

    def _get_synthetic_options_chain(self, ticker: str, date: datetime, current_price: float) -> pd.DataFrame:
        """
        Generate synthetic options chain for backtesting.
        Uses enhanced pricing model (4.5x time value multiplier).
        Expiration dates are snapped to Fridays for Polygon compatibility.
        """
        from scipy.stats import norm

        chain_data = []
        dte_values = [21, 30, 35, 45]

        for dte in dte_values:
            exp_date = self._snap_to_friday(date + timedelta(days=dte))
            iv = 0.25
            t = dte / 365.0
            sqrt_t = math.sqrt(t)
            
            # Generate strikes
            strike_range = int(current_price * 0.20)
            strikes = range(
                int(current_price - strike_range),
                int(current_price + strike_range),
                1
            )
            
            for strike in strikes:
                # Black-Scholes delta
                moneyness = math.log(current_price / strike)
                d1 = (moneyness + 0.5 * iv**2 * t) / (iv * sqrt_t)
                
                # Put
                put_delta = norm.cdf(d1) - 1
                put_delta = max(-0.99, min(-0.01, put_delta))
                intrinsic_put = max(0, strike - current_price)
                time_value = current_price * iv * sqrt_t * 4.5 * abs(put_delta)
                put_price = intrinsic_put + time_value
                
                chain_data.append({
                    'type': 'put',
                    'strike': float(strike),
                    'expiration': exp_date,
                    'bid': max(0.01, put_price * 0.97),
                    'ask': put_price * 1.03,
                    'delta': put_delta,
                    'iv': iv,
                })
                
                # Call
                call_delta = norm.cdf(d1)
                call_delta = max(0.01, min(0.99, call_delta))
                intrinsic_call = max(0, current_price - strike)
                time_value = current_price * iv * sqrt_t * 4.5 * call_delta
                call_price = intrinsic_call + time_value
                
                chain_data.append({
                    'type': 'call',
                    'strike': float(strike),
                    'expiration': exp_date,
                    'bid': max(0.01, call_price * 0.97),
                    'ask': call_price * 1.03,
                    'delta': call_delta,
                    'iv': iv,
                })
        
        return pd.DataFrame(chain_data)

    def _get_historical_data(self, ticker: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Get historical price data."""
        try:
            # Extend range slightly for technical indicators
            data_start = start_date - timedelta(days=365)
            data = yf.download(ticker, start=data_start, end=end_date, progress=False)
            
            if data.empty:
                return pd.DataFrame()
            
            # Handle MultiIndex columns
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            
            return data
        except Exception as e:
            logger.error(f"Failed to get historical data for {ticker}: {e}")
            return pd.DataFrame()

    def _opportunity_to_position(self, opp: Dict, entry_date: datetime) -> Optional[Dict]:
        """
        Convert opportunity to position using real Polygon prices.

        If polygon_provider is set, trades WITHOUT real Polygon pricing data
        are SKIPPED entirely (no synthetic fallback).
        """
        commission_cost = self.commission * 2
        max_loss = opp.get('max_loss', 0)

        if max_loss <= 0:
            return None

        credit = opp['credit']
        spread_prices = None

        # If Polygon provider available, fetch real option prices for both legs
        if self.polygon_provider:
            ticker = opp['ticker']
            expiration = opp['expiration']
            short_strike = opp['short_strike']
            long_strike = opp['long_strike']
            option_type = 'put' if 'put' in opp['type'].lower() else 'call'

            spread_prices = self.polygon_provider.get_spread_historical_prices(
                underlying=ticker,
                expiration=expiration,
                short_strike=short_strike,
                long_strike=long_strike,
                option_type=option_type,
                start_date=entry_date - timedelta(days=1),
                end_date=expiration + timedelta(days=1),
            )

            if spread_prices is not None and not spread_prices.empty:
                # Find entry date price (closest date on or after entry)
                entry_mask = spread_prices.index >= pd.Timestamp(entry_date).normalize()
                if entry_mask.any():
                    entry_row = spread_prices[entry_mask].iloc[0]
                    real_credit = entry_row['spread_value']
                    if real_credit > 0:
                        credit = real_credit
                        max_loss = abs(short_strike - long_strike) - credit
                        logger.info(f"  Real entry credit: ${credit:.2f} (synthetic was ${opp['credit']:.2f})")
                    else:
                        logger.debug(f"  Real credit non-positive ({real_credit:.2f}), skipping trade")
                        return None
                else:
                    logger.debug(f"  No real price data on entry date {entry_date.date()}, skipping trade")
                    return None
            else:
                logger.debug(f"  No Polygon data for {opp['type']} {short_strike}/{long_strike}, skipping trade")
                return None

        spread_width = abs(opp['short_strike'] - opp['long_strike'])
        risk_per_spread = max_loss * 100
        max_risk = self.capital * (self.risk_params['max_risk_per_trade'] / 100)
        min_contracts = self.risk_params.get('min_contracts', 1)
        max_contracts = self.risk_params.get('max_contracts', 20)
        contracts = max(min_contracts, min(max_contracts, int(max_risk / risk_per_spread)))

        # Log scaling effect
        base_contracts = max(min_contracts, min(max_contracts, int(
            self.starting_capital * (self.risk_params['max_risk_per_trade'] / 100) / risk_per_spread
        )))
        if contracts != base_contracts:
            logger.info(
                f"  Scaling: {contracts} contracts (base would be {base_contracts}, "
                f"capital=${self.capital:,.0f})"
            )

        position = {
            'ticker': opp['ticker'],
            'type': opp['type'],
            'entry_date': entry_date,
            'expiration': opp['expiration'],
            'short_strike': opp['short_strike'],
            'long_strike': opp['long_strike'],
            'credit': credit,
            'contracts': contracts,
            'max_loss': max_loss,
            'spread_width': spread_width,
            'score': opp.get('score', 0),
            'status': 'open',
            'current_value': credit * contracts * 100,
            'commission': commission_cost,
            'pricing_source': 'polygon',
        }

        # Cache the spread prices for daily management
        cache_key = (opp['short_strike'], opp['long_strike'], opp['expiration'].isoformat())
        self._spread_price_cache[cache_key] = spread_prices

        self.capital -= commission_cost
        return position

    def _get_current_spread_value(self, pos: Dict, current_date: datetime,
                                  current_price: float) -> float:
        """
        Get current spread cost-to-close.

        Uses real Polygon option prices if cached, otherwise falls back to
        intrinsic value estimation from underlying price.
        """
        cache_key = (pos['short_strike'], pos['long_strike'], pos['expiration'].isoformat())
        spread_prices = self._spread_price_cache.get(cache_key)

        if spread_prices is not None:
            # Use real option prices
            date_ts = pd.Timestamp(current_date).normalize()
            mask = spread_prices.index <= date_ts
            if mask.any():
                row = spread_prices[mask].iloc[-1]
                return row['spread_value']

        # Fallback: estimate from underlying price (intrinsic value only)
        short_strike = pos['short_strike']
        long_strike = pos['long_strike']
        spread_type = pos['type']

        if 'put' in spread_type.lower():
            if current_price >= short_strike:
                return 0.0
            elif current_price <= long_strike:
                return abs(short_strike - long_strike)
            else:
                return short_strike - current_price
        else:
            if current_price <= short_strike:
                return 0.0
            elif current_price >= long_strike:
                return abs(long_strike - short_strike)
            else:
                return current_price - short_strike

    def _get_profit_target_pct(self, pos: Dict, current_date: datetime) -> float:
        """
        Profit target as fraction of credit, adjusted by time remaining.

        >21 DTE: Take 50% profit (normal — theta hasn't kicked in yet)
        14-21 DTE: Take 40% profit (theta accelerating, capture gains)
        7-14 DTE: Take 25% profit (gamma risk rising, take what you can)
        <7 DTE: Take any profit (close before expiration week)
        """
        dte_remaining = (pos['expiration'] - current_date).days

        if dte_remaining > 21:
            return 0.50
        elif dte_remaining > 14:
            return 0.40
        elif dte_remaining > 7:
            return 0.25
        else:
            return 0.01  # Take any profit in final week

    def _get_dynamic_stop_value(self, pos: Dict, current_date: datetime) -> float:
        """
        Width-based stop that tightens as DTE decreases (gamma risk increases).

        Returns the spread value threshold that triggers a stop loss.
        """
        spread_width = pos.get('spread_width', abs(pos['short_strike'] - pos['long_strike']))
        base_pct = self.risk_params.get('stop_loss_pct_of_width', 50) / 100

        dte_remaining = (pos['expiration'] - current_date).days

        if dte_remaining > 21:
            return spread_width * base_pct         # e.g., 50% of $10 = $5.00
        elif dte_remaining > 14:
            return spread_width * (base_pct - 0.10)  # 40% = $4.00
        elif dte_remaining > 7:
            return spread_width * (base_pct - 0.15)  # 35% = $3.50
        else:
            return spread_width * (base_pct - 0.20)  # 30% = $3.00

    def _attempt_roll(self, pos: Dict, current_date: datetime,
                      current_price: float) -> Optional[Dict]:
        """
        Attempt to roll a losing position to a later expiration.

        Closes the current position and opens a new one at the same strikes
        but ~30 DTE out, collecting additional credit to lower cost basis.

        Returns new position dict if roll succeeds, None if it should stop out.
        """
        if not self.enable_rolling:
            return None

        rolls_done = pos.get('rolls', 0)
        if rolls_done >= self.max_rolls:
            return None

        # Find new expiration ~30 DTE from now
        new_expiration = self._snap_to_friday(current_date + timedelta(days=30))

        # Try to get real Polygon pricing for the new expiration
        additional_credit = None
        new_spread_prices = None

        if self.polygon_provider:
            option_type = 'put' if 'put' in pos['type'].lower() else 'call'
            new_spread_prices = self.polygon_provider.get_spread_historical_prices(
                underlying=pos['ticker'],
                expiration=new_expiration,
                short_strike=pos['short_strike'],
                long_strike=pos['long_strike'],
                option_type=option_type,
                start_date=current_date - timedelta(days=1),
                end_date=new_expiration + timedelta(days=1),
            )

            if new_spread_prices is not None and not new_spread_prices.empty:
                entry_mask = new_spread_prices.index >= pd.Timestamp(current_date).normalize()
                if entry_mask.any():
                    new_entry_row = new_spread_prices[entry_mask].iloc[0]
                    new_credit = new_entry_row['spread_value']

                    # Current spread value is what we'd pay to close
                    current_spread_value = self._get_current_spread_value(
                        pos, current_date, current_price
                    )

                    # Additional credit = new credit - cost to close current
                    additional_credit = new_credit - current_spread_value

        if additional_credit is None or additional_credit < self.min_roll_credit:
            return None

        # Execute the roll: create new position with combined credit
        old_credit = pos['credit']
        rolled_pos = {
            'ticker': pos['ticker'],
            'type': pos['type'],
            'entry_date': pos['entry_date'],
            'expiration': new_expiration,
            'short_strike': pos['short_strike'],
            'long_strike': pos['long_strike'],
            'credit': round(old_credit + additional_credit, 2),
            'contracts': pos['contracts'],
            'max_loss': pos.get('spread_width', abs(pos['short_strike'] - pos['long_strike'])) - (old_credit + additional_credit),
            'score': pos.get('score', 0),
            'status': 'open',
            'current_value': 0,
            'commission': pos.get('commission', 0) + self.commission * 2,
            'pricing_source': 'polygon',
            'rolls': rolls_done + 1,
            'roll_date': current_date,
            'original_credit': pos.get('original_credit', old_credit),
            'spread_width': pos.get('spread_width', abs(pos['short_strike'] - pos['long_strike'])),
        }

        # Cache new spread prices
        cache_key = (pos['short_strike'], pos['long_strike'], new_expiration.isoformat())
        self._spread_price_cache[cache_key] = new_spread_prices

        # Clean up old cache
        old_cache_key = (pos['short_strike'], pos['long_strike'], pos['expiration'].isoformat())
        self._spread_price_cache.pop(old_cache_key, None)

        # Pay commission for the roll
        self.capital -= self.commission * 2

        logger.info(
            f"  Rolled {pos['ticker']} {pos['type']} to {new_expiration.date()} "
            f"(+${additional_credit:.2f} credit, total=${rolled_pos['credit']:.2f})"
        )

        return rolled_pos

    def _manage_positions(self, positions: List[Dict], current_date: datetime,
                         price_data: pd.DataFrame, ticker: str) -> List[Dict]:
        """
        Manage open positions with intra-position exit logic.

        Checks daily using real option prices (Polygon) or intrinsic estimation:
        - Expiration: close with actual P&L
        - Time-based profit target
        - Rolling: attempt roll before stop loss
        - Width-based stop loss: if spread value exceeds dynamic threshold
        """
        remaining = []

        # Get current underlying price
        try:
            price_row = price_data.loc[price_data.index <= current_date].iloc[-1]
            current_price = float(price_row['Close'])
        except (IndexError, KeyError):
            return positions

        for pos in positions:
            credit = pos['credit']
            spread_type = pos['type']

            # Check expiration first
            if current_date >= pos['expiration']:
                current_spread_value = self._get_current_spread_value(pos, current_date, current_price)
                pnl_per_contract = credit - current_spread_value
                self._close_position(pos, current_date, "expired",
                                     underlying_price=current_price,
                                     real_pnl_per_contract=pnl_per_contract)
                continue

            # Get current spread value (real or estimated)
            current_spread_value = self._get_current_spread_value(pos, current_date, current_price)
            current_pnl_per_contract = credit - current_spread_value

            # Time-based profit target (takes less profit as DTE decreases)
            target_pct = self._get_profit_target_pct(pos, current_date)
            if current_pnl_per_contract >= credit * target_pct:
                dte_rem = (pos['expiration'] - current_date).days
                self._close_position(pos, current_date, "profit_target",
                                     underlying_price=current_price,
                                     real_pnl_per_contract=current_pnl_per_contract)
                logger.info(
                    f"  Profit target hit: {pos['ticker']} {spread_type} @ ${current_price:.2f} "
                    f"(target={target_pct:.0%}, spread_val=${current_spread_value:.2f}, {dte_rem}d left)"
                )
                continue

            # Width-based stop loss with time decay tightening
            stop_threshold = self._get_dynamic_stop_value(pos, current_date)
            if current_spread_value >= stop_threshold:
                # Attempt to roll before stopping out
                rolled = self._attempt_roll(pos, current_date, current_price)
                if rolled:
                    remaining.append(rolled)
                    continue

                self._close_position(pos, current_date, "stop_loss",
                                     underlying_price=current_price,
                                     real_pnl_per_contract=current_pnl_per_contract)
                dte_rem = (pos['expiration'] - current_date).days
                logger.info(
                    f"  Stop loss hit: {pos['ticker']} {spread_type} @ ${current_price:.2f} "
                    f"(spread_val=${current_spread_value:.2f} >= stop=${stop_threshold:.2f}, {dte_rem}d left)"
                )
                continue

            pos['current_value'] = current_pnl_per_contract * pos['contracts'] * 100
            remaining.append(pos)

        return remaining

    def _close_position(self, position: Dict, close_date: datetime, reason: str,
                        underlying_price: float = None, real_pnl_per_contract: float = None):
        """
        Close a position with P&L calculation.

        If real_pnl_per_contract is provided (from real Polygon option prices or
        daily management), use it directly. Otherwise fall back to intrinsic
        value estimation from the underlying price.
        """
        credit = position['credit']
        contracts = position['contracts']
        short_strike = position['short_strike']
        long_strike = position['long_strike']
        spread_width = abs(short_strike - long_strike)

        if real_pnl_per_contract is not None:
            # Use the real P&L passed from management (based on real option prices or intrinsic)
            pnl_per_contract = real_pnl_per_contract
        elif reason in ("expired", "backtest_end") and underlying_price is not None:
            # Fallback: calculate from underlying price vs strikes
            spread_type = position['type']

            if 'put' in spread_type.lower():
                if underlying_price >= short_strike:
                    pnl_per_contract = credit
                elif underlying_price <= long_strike:
                    pnl_per_contract = credit - spread_width
                else:
                    intrinsic = short_strike - underlying_price
                    pnl_per_contract = credit - intrinsic
            else:
                if underlying_price <= short_strike:
                    pnl_per_contract = credit
                elif underlying_price >= long_strike:
                    pnl_per_contract = credit - spread_width
                else:
                    intrinsic = underlying_price - short_strike
                    pnl_per_contract = credit - intrinsic
        else:
            pnl_per_contract = credit

        pnl = pnl_per_contract * contracts * 100
        commission = position.get('commission', 0)
        pnl -= commission

        self.capital += pnl
        position['exit_date'] = close_date
        position['exit_reason'] = reason
        position['exit_price'] = underlying_price
        position['pnl'] = pnl
        position['status'] = 'closed'

        self.trades.append(position)

        # Clean up cached spread prices
        cache_key = (position['short_strike'], position['long_strike'], position['expiration'].isoformat())
        self._spread_price_cache.pop(cache_key, None)

    def _calculate_results(self) -> Dict:
        """Calculate backtest results."""
        if not self.trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'starting_capital': self.starting_capital,
                'ending_capital': self.capital,
                'return_pct': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'trades': [],
                'equity_curve': [],
            }
        
        trades_df = pd.DataFrame(self.trades)
        
        winners = trades_df[trades_df['pnl'] > 0]
        losers = trades_df[trades_df['pnl'] <= 0]
        
        total_pnl = trades_df['pnl'].sum()
        win_rate = (len(winners) / len(trades_df) * 100) if len(trades_df) > 0 else 0
        
        avg_win = winners['pnl'].mean() if len(winners) > 0 else 0
        avg_loss = losers['pnl'].mean() if len(losers) > 0 else 0
        
        # Calculate drawdown
        equity_df = pd.DataFrame(self.equity_curve, columns=['date', 'equity'])
        equity_df['cummax'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['cummax']) / equity_df['cummax']
        max_drawdown = equity_df['drawdown'].min() * 100
        
        # Sharpe ratio
        equity_df['returns'] = equity_df['equity'].pct_change()
        returns = equity_df['returns'].dropna()
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if len(returns) > 0 and returns.std() > 0 else 0
        
        return_pct = ((self.capital - self.starting_capital) / self.starting_capital) * 100
        
        # Trade type breakdown
        type_counts = trades_df['type'].value_counts().to_dict() if 'type' in trades_df else {}

        # Contract scaling: avg contracts in first vs last quarter of trades
        n = len(trades_df)
        if n >= 4 and 'contracts' in trades_df:
            q_size = max(1, n // 4)
            avg_contracts_q1 = trades_df['contracts'].iloc[:q_size].mean()
            avg_contracts_q4 = trades_df['contracts'].iloc[-q_size:].mean()
        else:
            avg_contracts_q1 = trades_df['contracts'].mean() if 'contracts' in trades_df else 0
            avg_contracts_q4 = avg_contracts_q1

        # Rolling stats
        rolled_count = int(trades_df['rolls'].sum()) if 'rolls' in trades_df else 0

        return {
            'total_trades': len(trades_df),
            'winning_trades': len(winners),
            'losing_trades': len(losers),
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'starting_capital': self.starting_capital,
            'ending_capital': round(self.capital, 2),
            'return_pct': round(return_pct, 2),
            'max_drawdown': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe, 2),
            'trade_types': type_counts,
            'avg_contracts_q1': round(avg_contracts_q1, 1),
            'avg_contracts_q4': round(avg_contracts_q4, 1),
            'rolled_positions': rolled_count,
            'trades': trades_df.to_dict('records'),
            'equity_curve': equity_df.to_dict('records'),
        }
