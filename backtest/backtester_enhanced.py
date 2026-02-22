"""
Enhanced Backtesting Engine with Real Alert Logic
Integrates full strategy scoring: ML, IV filtering, regime detection, and technical analysis.
"""

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from strategy import CreditSpreadStrategy, TechnicalAnalyzer, OptionsAnalyzer
from shared.data_cache import DataCache

logger = logging.getLogger(__name__)


class BacktesterEnhanced:
    """
    Enhanced backtest engine that uses real alert-generation logic.
    
    This version integrates:
    - CreditSpreadStrategy.evaluate_spread_opportunity()
    - Full ML scoring (if available)
    - IV filtering and regime detection
    - Technical analysis
    - Everything that produces actual alerts
    """

    def __init__(
        self,
        config: Dict,
        historical_data=None,
        ml_pipeline=None,
        strategy: Optional[CreditSpreadStrategy] = None,
        technical_analyzer: Optional[TechnicalAnalyzer] = None,
        options_analyzer: Optional[OptionsAnalyzer] = None,
    ):
        """
        Initialize enhanced backtester.

        Args:
            config: Configuration dictionary
            historical_data: Optional HistoricalOptionsData instance for real pricing
            ml_pipeline: Optional ML pipeline for scoring
            strategy: Optional pre-built strategy instance
            technical_analyzer: Optional pre-built technical analyzer
            options_analyzer: Optional pre-built options analyzer
        """
        self.config = config
        self.backtest_config = config['backtest']
        self.strategy_params = config['strategy']
        self.risk_params = config['risk']

        self.starting_capital = self.backtest_config['starting_capital']
        self.commission = self.backtest_config['commission_per_contract']
        self.slippage = self.backtest_config['slippage']
        self.score_threshold = self.backtest_config.get('score_threshold', 40)

        self.historical_data = historical_data
        self._use_real_data = historical_data is not None

        # Initialize strategy components
        self.data_cache = DataCache()
        self.strategy = strategy or CreditSpreadStrategy(config)
        self.technical_analyzer = technical_analyzer or TechnicalAnalyzer(config)
        self.options_analyzer = options_analyzer or OptionsAnalyzer(config, data_cache=self.data_cache)
        self.ml_pipeline = ml_pipeline

        # ML/rules blending weights
        strategy_cfg = self.config.get('strategy', {})
        self.ml_score_weight = strategy_cfg.get('ml_score_weight', 0.6)
        self.rules_score_weight = 1.0 - self.ml_score_weight
        self.event_risk_threshold = strategy_cfg.get('event_risk_threshold', 0.7)

        # Trade history
        self.trades = []
        self.equity_curve = []
        self.opportunity_log = []  # Log all opportunities found (for analysis)

        mode = "real data" if self._use_real_data else "heuristic"
        ml_mode = "with ML" if ml_pipeline else "rules-only"
        logger.info(f"BacktesterEnhanced initialized ({mode} mode, {ml_mode})")

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
        logger.info(f"Starting ENHANCED backtest for {ticker}: {start_date} to {end_date}")
        logger.info(f"Score threshold: {self.score_threshold}")

        # Get historical price data
        price_data = self._get_historical_data(ticker, start_date, end_date)

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
        self.opportunity_log = []

        open_positions = []

        if price_data.index.tz is not None:
            price_data.index = price_data.index.tz_localize(None)
        trading_dates = set(price_data.index)

        # Simulate trading day by day
        current_date = start_date
        scan_count = 0
        opportunity_count = 0

        while current_date <= end_date:
            lookup_date = pd.Timestamp(current_date.date())

            if lookup_date not in trading_dates:
                current_date += timedelta(days=1)
                continue

            current_price = float(price_data.loc[lookup_date, 'Close'])

            # Check existing positions
            open_positions = self._manage_positions(
                open_positions, current_date, current_price, ticker
            )

            # Look for new opportunities (once per week on Monday)
            if current_date.weekday() == 0:  # Monday
                if len(open_positions) < self.risk_params['max_positions']:
                    scan_count += 1
                    
                    # Use REAL alert logic to find opportunities
                    opportunities = self._find_opportunities_with_real_logic(
                        ticker, current_date, current_price, price_data, lookup_date
                    )
                    
                    opportunity_count += len(opportunities)
                    
                    # Log all opportunities for analysis
                    for opp in opportunities:
                        self.opportunity_log.append({
                            'date': current_date,
                            'ticker': opp['ticker'],
                            'type': opp['type'],
                            'score': opp.get('score', 0),
                            'rules_score': opp.get('rules_score'),
                            'ml_score': opp.get('ml_score'),
                            'regime': opp.get('regime'),
                            'short_strike': opp['short_strike'],
                            'credit': opp['credit'],
                            'pop': opp['pop'],
                            'entered': False,
                        })
                    
                    # Take the BEST opportunity that meets threshold
                    valid_opportunities = [
                        opp for opp in opportunities
                        if opp.get('score', 0) >= self.score_threshold
                    ]
                    
                    if valid_opportunities and len(open_positions) < self.risk_params['max_positions']:
                        best_opp = valid_opportunities[0]  # Already sorted by score
                        
                        # Convert to position
                        new_position = self._opportunity_to_position(best_opp, current_date)
                        if new_position:
                            open_positions.append(new_position)
                            # Mark as entered in log
                            if self.opportunity_log:
                                self.opportunity_log[-len(opportunities)]['entered'] = True
                            logger.info(
                                f"  → Entered {best_opp['type']} @ {current_date.date()}: "
                                f"Score={best_opp.get('score', 0):.1f}, "
                                f"Credit=${best_opp['credit']:.2f}"
                            )

            # Record equity
            position_value = sum(pos.get('current_value', 0) for pos in open_positions)
            total_equity = self.capital + position_value
            self.equity_curve.append((current_date, total_equity))

            current_date += timedelta(days=1)

        # Close any remaining positions
        for pos in open_positions:
            self._close_position(pos, end_date, current_price, 'backtest_end')

        # Calculate performance metrics
        results = self._calculate_results()
        results['scan_count'] = scan_count
        results['opportunity_count'] = opportunity_count
        results['opportunities_per_scan'] = opportunity_count / scan_count if scan_count > 0 else 0
        results['entry_rate'] = len(self.trades) / opportunity_count if opportunity_count > 0 else 0

        logger.info("=" * 80)
        logger.info("ENHANCED BACKTEST COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Scans performed: {scan_count}")
        logger.info(f"Opportunities found: {opportunity_count}")
        logger.info(f"Trades entered: {len(self.trades)}")
        logger.info(f"Entry rate: {results['entry_rate']:.1%}")
        logger.info(f"Starting capital: ${self.starting_capital:,.2f}")
        logger.info(f"Ending capital: ${results['ending_capital']:,.2f}")
        logger.info(f"Total return: {results['return_pct']:.2f}%")
        logger.info(f"Win rate: {results['win_rate']:.2f}%")
        logger.info("=" * 80)

        return results

    def _find_opportunities_with_real_logic(
        self,
        ticker: str,
        date: datetime,
        current_price: float,
        price_data: pd.DataFrame,
        lookup_date: pd.Timestamp,
    ) -> List[Dict]:
        """
        Find opportunities using the REAL alert generation logic.
        
        This mirrors main.py::_analyze_ticker() to use the full strategy stack.
        """
        try:
            # Get historical price data window for technical analysis
            hist_window = price_data.loc[:lookup_date].tail(252)  # 1 year window
            
            if len(hist_window) < 50:
                return []

            # Technical analysis (REAL)
            technical_signals = self.technical_analyzer.analyze(ticker, hist_window)

            # Options chain simulation (since we don't have historical chains in backtest)
            # We'll create a synthetic chain based on current price
            options_chain = self._create_synthetic_options_chain(
                ticker, current_price, date
            )

            if options_chain.empty:
                return []

            # IV analysis (REAL)
            current_iv = self.options_analyzer.get_current_iv(options_chain)
            iv_data = self.options_analyzer.calculate_iv_rank(ticker, current_iv)
            
            logger.debug(f"{ticker} @ {date.date()}: IV={current_iv:.2f}, IV_Rank={iv_data.get('iv_rank', 0):.1f}, Trend={technical_signals.get('trend', 'N/A')}")

            # Evaluate spread opportunities (REAL STRATEGY LOGIC)
            opportunities = self.strategy.evaluate_spread_opportunity(
                ticker=ticker,
                option_chain=options_chain,
                technical_signals=technical_signals,
                iv_data=iv_data,
                current_price=current_price
            )

            # Enhance with ML scoring if available (REAL ML LOGIC)
            if self.ml_pipeline and opportunities:
                try:
                    for opp in opportunities:
                        spread_type = 'bull_put' if 'put' in opp.get('type', '') else 'bear_call'
                        ml_result = self.ml_pipeline.analyze_trade(
                            ticker=ticker,
                            current_price=current_price,
                            options_chain=options_chain,
                            spread_type=spread_type,
                            technical_signals=technical_signals,
                        )
                        # Blend ML score with rules-based score
                        rules_score = opp.get('score', 50)
                        ml_score = ml_result.get('enhanced_score', rules_score)
                        opp['rules_score'] = rules_score
                        opp['ml_score'] = ml_score
                        opp['score'] = self.ml_score_weight * ml_score + self.rules_score_weight * rules_score
                        opp['regime'] = ml_result.get('regime', {}).get('regime', 'unknown')
                        opp['regime_confidence'] = ml_result.get('regime', {}).get('confidence', 0)
                        opp['event_risk'] = ml_result.get('event_risk', {}).get('event_risk_score', 0)

                        # Skip if high event risk (REAL FILTERING)
                        if opp['event_risk'] > self.event_risk_threshold:
                            logger.debug(f"Skipping {ticker} {opp['type']} due to high event risk")
                            opp['score'] = 0

                except Exception as e:
                    logger.warning(f"ML scoring failed, using rules-based: {e}")

            # Sort by score (highest first)
            opportunities.sort(key=lambda x: x.get('score', 0), reverse=True)

            return opportunities

        except Exception as e:
            logger.error(f"Error finding opportunities for {ticker}: {e}", exc_info=True)
            return []

    def _create_synthetic_options_chain(
        self,
        ticker: str,
        current_price: float,
        date: datetime,
    ) -> pd.DataFrame:
        """
        Create a synthetic options chain for backtesting.
        
        Since we don't have historical options chains, we simulate one
        with reasonable greeks and prices.
        """
        from scipy.stats import norm
        
        chain_data = []
        
        # Create expirations: 30, 37, 44, 51 DTE
        for dte in [30, 37, 44, 51]:
            exp_date = date + timedelta(days=dte)
            
            # Volatility and time parameters
            iv = 0.25  # 25% implied volatility
            t = dte / 365.0
            sqrt_t = math.sqrt(t)
            
            # Create strikes around current price (in $1 increments)
            strike_range = int(current_price * 0.20)  # +/- 20%
            strikes = range(
                int(current_price - strike_range),
                int(current_price + strike_range),
                1
            )
            
            for strike in strikes:
                # Black-Scholes-ish delta calculation
                moneyness = math.log(current_price / strike)
                d1 = (moneyness + 0.5 * iv**2 * t) / (iv * sqrt_t)
                
                # Put delta (negative)
                put_delta = norm.cdf(d1) - 1  # Range: -1 to 0
                put_delta = max(-0.99, min(-0.01, put_delta))
                
                # Put price approximation (more realistic)
                intrinsic_put = max(0, strike - current_price)
                # Use Black-Scholes inspired pricing with more generous time value
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
                
                # Call delta (positive)
                call_delta = norm.cdf(d1)  # Range: 0 to 1
                call_delta = max(0.01, min(0.99, call_delta))
                
                # Call price approximation
                intrinsic_call = max(0, current_price - strike)
                # Use Black-Scholes inspired pricing with more generous time value
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

    def _opportunity_to_position(self, opportunity: Dict, entry_date: datetime) -> Optional[Dict]:
        """
        Convert an opportunity dict to a position dict.
        """
        commission_cost = self.commission * 2  # Two legs

        # Calculate contracts based on risk
        max_loss = opportunity['max_loss']
        risk_per_spread = max_loss * 100
        if risk_per_spread <= 0:
            return None
        
        max_risk = self.capital * (self.risk_params['max_risk_per_trade'] / 100)
        contracts = max(1, int(max_risk / risk_per_spread))

        position = {
            'ticker': opportunity['ticker'],
            'type': opportunity['type'],
            'entry_date': entry_date,
            'expiration': opportunity['expiration'],
            'short_strike': opportunity['short_strike'],
            'long_strike': opportunity['long_strike'],
            'credit': opportunity['credit'],
            'contracts': contracts,
            'max_loss': max_loss,
            'profit_target': opportunity['profit_target'],
            'stop_loss': opportunity['stop_loss'],
            'commission': commission_cost,
            'status': 'open',
            'current_value': opportunity['credit'] * contracts * 100,
            'option_type': 'P' if 'put' in opportunity['type'] else 'C',
            'score': opportunity.get('score', 0),
            'rules_score': opportunity.get('rules_score'),
            'ml_score': opportunity.get('ml_score'),
            'regime': opportunity.get('regime'),
        }

        self.capital -= commission_cost

        return position

    def _get_historical_data(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """Retrieve historical price data."""
        try:
            # Add buffer for technical indicators
            buffer_start = start_date - timedelta(days=252)
            stock = yf.Ticker(ticker)
            data = stock.history(start=buffer_start, end=end_date)
            return data
        except Exception as e:
            logger.error(f"Error getting historical data: {e}", exc_info=True)
            return pd.DataFrame()

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
                self._close_at_expiration(pos, current_date, current_price)
                continue

            # Estimate current spread value
            dte = (pos['expiration'] - current_date).days
            current_spread_value = self._estimate_spread_value(pos, current_price, dte)

            # P&L check: profit = credit - current spread value
            profit = pos['credit'] - current_spread_value

            if profit >= pos['profit_target']:
                pnl = profit * pos['contracts'] * 100 - pos['commission']
                self._record_close(pos, current_date, pnl, 'profit_target')
                continue

            loss = current_spread_value - pos['credit']
            if loss >= pos['stop_loss']:
                pnl = -loss * pos['contracts'] * 100 - pos['commission']
                self._record_close(pos, current_date, pnl, 'stop_loss')
                continue

            # Update current value
            pos['current_value'] = -current_spread_value * pos['contracts'] * 100

            remaining_positions.append(pos)

        return remaining_positions

    def _close_at_expiration(self, pos: Dict, expiration_date: datetime, current_price: float):
        """Close a position at expiration."""
        is_put = pos['option_type'] == 'P'
        
        # Check if short leg is ITM
        if is_put:
            itm = current_price < pos['short_strike']
        else:
            itm = current_price > pos['short_strike']
        
        if itm:
            # Assignment risk — estimate loss
            pnl = -pos['max_loss'] * pos['contracts'] * 100 - pos['commission']
            reason = 'expiration_loss'
        else:
            # Expired worthless — max profit
            pnl = pos['credit'] * pos['contracts'] * 100 - pos['commission']
            reason = 'expiration_profit'
        
        self._record_close(pos, expiration_date, pnl, reason)

    def _estimate_spread_value(
        self,
        position: Dict,
        current_price: float,
        dte: int,
    ) -> float:
        """
        Estimate current value of spread (heuristic).
        """
        short_strike = position['short_strike']
        spread_width = abs(position['short_strike'] - position['long_strike'])

        OTM_BUFFER = 0.05
        ITM_BUFFER = 0.05
        TYPICAL_DTE = 35
        ITM_EXTRINSIC_FRAC = 0.3
        NTM_EXTRINSIC_FRAC = 0.7
        ITM_DISTANCE_MULT = 2

        is_put = position.get('option_type') == 'P'

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
        """Close a position and record trade (legacy fallback)."""
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
        self._record_close(position, exit_date, pnl, exit_reason)

    def _record_close(self, pos: Dict, exit_date: datetime, pnl: float, reason: str):
        """Record a closed position."""
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
            'score': pos.get('score'),
            'rules_score': pos.get('rules_score'),
            'ml_score': pos.get('ml_score'),
            'regime': pos.get('regime'),
        }

        self.trades.append(trade)
        logger.debug(f"Closed position: {reason}, P&L: ${pnl:.2f}")

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
                'opportunity_log': self.opportunity_log,
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
            'opportunity_log': self.opportunity_log,
        }

        return results
