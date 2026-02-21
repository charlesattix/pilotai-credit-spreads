"""
FIXED Backtesting Engine - Uses REAL Strategy Logic
==================================================

This version properly integrates:
- strategy.evaluate_spread_opportunity() with full scoring
- ML pipeline scoring (if available)
- Technical analysis
- IV filtering
- Everything that generates actual alerts

Author: Charles (fixing P0 critical issue)
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
                 ml_pipeline=None, historical_data=None):
        """
        Initialize fixed backtester.

        Args:
            config: Configuration dictionary
            strategy: CreditSpreadStrategy instance
            technical_analyzer: TechnicalAnalyzer instance
            options_analyzer: OptionsAnalyzer instance
            ml_pipeline: Optional MLPipeline instance
            historical_data: Optional HistoricalOptionsData instance
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
        
        # ML/rules blending weights
        strategy_cfg = self.config.get('strategy', {})
        self.ml_score_weight = strategy_cfg.get('ml_score_weight', 0.6)
        self.rules_score_weight = 1.0 - self.ml_score_weight
        self.event_risk_threshold = strategy_cfg.get('event_risk_threshold', 0.7)

        # Trade history
        self.trades = []
        self.equity_curve = []

        mode = "real strategy" if strategy else "simplified"
        logger.info(f"BacktesterFixed initialized ({mode} mode)")

    def run_backtest(self, ticker: str, start_date: datetime, end_date: datetime) -> Dict:
        """
        Run backtest using REAL strategy logic.

        Args:
            ticker: Stock ticker
            start_date: Start date
            end_date: End date

        Returns:
            Dictionary with backtest results
        """
        logger.info(f"Starting FIXED backtest for {ticker}: {start_date} to {end_date}")
        logger.info(f"Score threshold: {self.score_threshold}")

        # Get historical price data
        price_data = self._get_historical_data(ticker, start_date, end_date)

        if price_data.empty:
            logger.error(f"No historical data for {ticker}")
            return {}

        # Initialize portfolio
        self.capital = self.starting_capital
        self.trades = []
        self.equity_curve = [(start_date, self.capital)]

        open_positions = []

        # Scan weekly (every Monday)
        current_date = start_date
        scans_performed = 0
        opportunities_found = 0

        while current_date <= end_date:
            # Check if Monday
            if current_date.weekday() == 0:
                scans_performed += 1
                
                # Get current price
                try:
                    current_price_row = price_data.loc[price_data.index <= current_date].iloc[-1]
                    current_price = float(current_price_row['Close'])
                except:
                    current_date += timedelta(days=1)
                    continue

                # Look for new opportunities using REAL strategy
                if len(open_positions) < self.risk_params['max_positions']:
                    opportunity = self._find_opportunity_real_logic(
                        ticker, current_date, current_price, price_data
                    )
                    
                    if opportunity:
                        opportunities_found += 1
                        position = self._opportunity_to_position(opportunity, current_date)
                        if position:
                            open_positions.append(position)
                            logger.info(f"Opened {position['type']} @ {current_date.date()}, score={opportunity['score']:.1f}")

            # Manage existing positions
            open_positions = self._manage_positions(open_positions, current_date, price_data, ticker)

            # Record equity
            position_value = sum(pos.get('current_value', 0) for pos in open_positions)
            total_equity = self.capital + position_value
            self.equity_curve.append((current_date, total_equity))

            current_date += timedelta(days=1)

        # Close remaining positions with actual underlying price
        try:
            final_price_row = price_data.loc[price_data.index <= end_date].iloc[-1]
            final_price = float(final_price_row['Close'])
        except (IndexError, KeyError):
            final_price = None

        for pos in open_positions:
            self._close_position(pos, end_date, "backtest_end",
                                 underlying_price=final_price)

        # Calculate results
        results = self._calculate_results()
        results['scans_performed'] = scans_performed
        results['opportunities_found'] = opportunities_found

        logger.info(f"Backtest complete: {scans_performed} scans, {opportunities_found} opportunities, {results['total_trades']} trades")

        return results

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

    def _get_synthetic_options_chain(self, ticker: str, date: datetime, current_price: float) -> pd.DataFrame:
        """
        Generate synthetic options chain for backtesting.
        Uses enhanced pricing model (4.5x time value multiplier).
        """
        from scipy.stats import norm
        
        chain_data = []
        dte_values = [21, 30, 35, 45]
        
        for dte in dte_values:
            exp_date = date + timedelta(days=dte)
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
        """Convert opportunity to position."""
        commission_cost = self.commission * 2
        max_loss = opp.get('max_loss', 0)
        
        if max_loss <= 0:
            return None
        
        risk_per_spread = max_loss * 100
        max_risk = self.capital * (self.risk_params['max_risk_per_trade'] / 100)
        contracts = max(1, int(max_risk / risk_per_spread))
        
        position = {
            'ticker': opp['ticker'],
            'type': opp['type'],
            'entry_date': entry_date,
            'expiration': opp['expiration'],
            'short_strike': opp['short_strike'],
            'long_strike': opp['long_strike'],
            'credit': opp['credit'],
            'contracts': contracts,
            'max_loss': max_loss,
            'score': opp.get('score', 0),
            'status': 'open',
            'current_value': opp['credit'] * contracts * 100,
            'commission': commission_cost,
        }
        
        self.capital -= commission_cost
        return position

    def _manage_positions(self, positions: List[Dict], current_date: datetime,
                         price_data: pd.DataFrame, ticker: str) -> List[Dict]:
        """
        Manage open positions with intra-position exit logic.

        Checks daily:
        - Expiration: close with actual P&L based on underlying price
        - 50% profit target: if current spread value drops to 50% of credit received
        - 2x stop loss: if current spread value rises to 3x credit (loss = 2x credit)
        """
        remaining = []

        # Get current underlying price
        try:
            price_row = price_data.loc[price_data.index <= current_date].iloc[-1]
            current_price = float(price_row['Close'])
        except (IndexError, KeyError):
            # No price data for this date, keep all positions
            return positions

        for pos in positions:
            credit = pos['credit']
            short_strike = pos['short_strike']
            long_strike = pos['long_strike']
            spread_type = pos['type']

            # Check expiration first
            if current_date >= pos['expiration']:
                self._close_position(pos, current_date, "expired",
                                     underlying_price=current_price)
                continue

            # Estimate current spread intrinsic value to check profit/stop targets
            if 'put' in spread_type.lower():
                # Bull put spread
                if current_price >= short_strike:
                    current_spread_cost = 0.0  # Both OTM, spread worthless = full profit
                elif current_price <= long_strike:
                    current_spread_cost = abs(short_strike - long_strike)  # Max loss
                else:
                    current_spread_cost = short_strike - current_price  # Partial
            else:
                # Bear call spread
                if current_price <= short_strike:
                    current_spread_cost = 0.0  # Both OTM, spread worthless = full profit
                elif current_price >= long_strike:
                    current_spread_cost = abs(long_strike - short_strike)  # Max loss
                else:
                    current_spread_cost = current_price - short_strike  # Partial

            # Current P&L per contract = credit received - current cost to close
            current_pnl_per_contract = credit - current_spread_cost

            # 50% profit target: if we've captured >= 50% of credit
            if current_pnl_per_contract >= credit * 0.50:
                self._close_position(pos, current_date, "profit_target",
                                     underlying_price=current_price)
                logger.info(f"  Profit target hit: {pos['ticker']} {spread_type} @ ${current_price:.2f}")
                continue

            # 2x credit stop loss: if loss >= 2x the credit received
            if current_pnl_per_contract <= -(credit * 2.0):
                self._close_position(pos, current_date, "stop_loss",
                                     underlying_price=current_price)
                logger.info(f"  Stop loss hit: {pos['ticker']} {spread_type} @ ${current_price:.2f}")
                continue

            # Update position's tracked value
            pos['current_value'] = current_pnl_per_contract * pos['contracts'] * 100
            remaining.append(pos)

        return remaining

    def _close_position(self, position: Dict, close_date: datetime, reason: str,
                        underlying_price: float = None):
        """
        Close a position with ACTUAL P&L calculation.

        For expiring positions, P&L depends on where the underlying price is
        relative to the spread strikes:

        Bull put spread (short put above long put):
            price >= short_strike → full profit (keep entire credit)
            price <= long_strike  → max loss (credit - spread_width)
            between              → partial loss (credit - (short_strike - price))

        Bear call spread (short call below long call):
            price <= short_strike → full profit (keep entire credit)
            price >= long_strike  → max loss (credit - spread_width)
            between              → partial loss (credit - (price - short_strike))
        """
        credit = position['credit']
        contracts = position['contracts']
        short_strike = position['short_strike']
        long_strike = position['long_strike']
        spread_width = abs(short_strike - long_strike)

        if reason == "profit_target":
            # Closed early at 50% profit
            pnl_per_contract = credit * 0.50
        elif reason == "stop_loss":
            # Closed early at 2x credit loss
            pnl_per_contract = -(credit * 2.0)
        elif reason in ("expired", "backtest_end") and underlying_price is not None:
            # Calculate actual P&L based on underlying price at expiration
            spread_type = position['type']

            if 'put' in spread_type.lower():
                # Bull put spread: short_strike > long_strike
                if underlying_price >= short_strike:
                    # Both puts expire OTM → keep full credit
                    pnl_per_contract = credit
                elif underlying_price <= long_strike:
                    # Both puts ITM → max loss
                    pnl_per_contract = credit - spread_width
                else:
                    # Short put ITM, long put OTM → partial loss
                    intrinsic = short_strike - underlying_price
                    pnl_per_contract = credit - intrinsic
            else:
                # Bear call spread: short_strike < long_strike
                if underlying_price <= short_strike:
                    # Both calls expire OTM → keep full credit
                    pnl_per_contract = credit
                elif underlying_price >= long_strike:
                    # Both calls ITM → max loss
                    pnl_per_contract = credit - spread_width
                else:
                    # Short call ITM, long call OTM → partial loss
                    intrinsic = underlying_price - short_strike
                    pnl_per_contract = credit - intrinsic
        else:
            # Fallback: assume full profit (e.g. backtest_end with no price)
            pnl_per_contract = credit

        pnl = pnl_per_contract * contracts * 100
        commission = position.get('commission', 0)
        pnl -= commission  # Subtract commission on close

        self.capital += pnl
        position['exit_date'] = close_date
        position['exit_reason'] = reason
        position['exit_price'] = underlying_price
        position['pnl'] = pnl
        position['status'] = 'closed'

        self.trades.append(position)

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
            'trades': trades_df.to_dict('records'),
            'equity_curve': equity_df.to_dict('records'),
        }
