"""
Backtesting Engine
Tests credit spread strategies against historical data.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
import yfinance as yf
from shared.constants import BACKTEST_SHORT_STRIKE_OTM_FRACTION, BACKTEST_CREDIT_FRACTION

logger = logging.getLogger(__name__)


class Backtester:
    """
    Backtest credit spread strategies on historical data.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize backtester.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.backtest_config = config['backtest']
        self.strategy_params = config['strategy']
        self.risk_params = config['risk']
        
        self.starting_capital = self.backtest_config['starting_capital']
        self.commission = self.backtest_config['commission_per_contract']
        self.slippage = self.backtest_config['slippage']
        
        # Trade history
        self.trades = []
        self.equity_curve = []
        
        logger.info("Backtester initialized")
    
    def run_backtest(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime
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
        
        # Simulate trading day by day
        current_date = start_date
        
        while current_date <= end_date:
            # Get price for current date
            if current_date not in price_data.index:
                current_date += timedelta(days=1)
                continue
            
            current_price = price_data.loc[current_date, 'Close']
            
            # Check existing positions
            open_positions = self._manage_positions(
                open_positions, current_date, current_price
            )
            
            # Look for new opportunities (once per week)
            if current_date.weekday() == 0:  # Monday
                if len(open_positions) < self.risk_params['max_positions']:
                    new_position = self._find_backtest_opportunity(
                        ticker, current_date, current_price, price_data
                    )
                    if new_position:
                        open_positions.append(new_position)
            
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
        
        logger.info(f"Backtest complete. Total trades: {len(self.trades)}")
        
        return results
    
    def _get_historical_data(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Retrieve historical price data.
        """
        try:
            stock = yf.Ticker(ticker)
            data = stock.history(start=start_date, end=end_date)
            return data
        except Exception as e:
            logger.error(f"Error getting historical data: {e}", exc_info=True)
            return pd.DataFrame()
    
    def _find_backtest_opportunity(
        self,
        ticker: str,
        date: datetime,
        price: float,
        price_data: pd.DataFrame
    ) -> Optional[Dict]:
        """
        Simulate finding a spread opportunity.
        
        In real backtesting, you'd need historical options data.
        This is a simplified simulation.
        """
        # Simulate a bull put spread (most common)
        # Use technical analysis to decide direction
        
        # Get recent data for indicators
        recent_data = price_data.loc[:date].tail(50)
        
        if len(recent_data) < 20:
            return None
        
        # Simple trend check
        ma20 = recent_data['Close'].rolling(20).mean().iloc[-1]
        
        if price < ma20:
            # Price below MA, skip
            return None
        
        # Simulate a bull put spread
        # Short strike at ~10 delta (roughly 10% below current price)
        short_strike = price * BACKTEST_SHORT_STRIKE_OTM_FRACTION
        long_strike = short_strike - self.strategy_params['spread_width']
        
        # Estimate credit (simplified)
        # Typically 30-40% of spread width for high prob spreads
        credit = self.strategy_params['spread_width'] * BACKTEST_CREDIT_FRACTION
        
        # Apply slippage and commissions
        credit -= self.slippage
        commission_cost = self.commission * 2  # Two legs
        
        max_loss = self.strategy_params['spread_width'] - credit
        
        # Calculate contracts based on risk
        risk_per_spread = max_loss * 100
        max_risk = self.capital * (self.risk_params['max_risk_per_trade'] / 100)
        contracts = max(1, int(max_risk / risk_per_spread))
        
        # Expiration: 35 DTE (middle of range)
        expiration = date + timedelta(days=35)
        
        position = {
            'ticker': ticker,
            'type': 'bull_put_spread',
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
        }
        
        # Deduct entry commissions
        self.capital -= commission_cost
        
        logger.debug(f"Opened position: {ticker} bull put spread @ ${short_strike:.2f}")
        
        return position
    
    def _manage_positions(
        self,
        positions: List[Dict],
        current_date: datetime,
        current_price: float
    ) -> List[Dict]:
        """
        Manage open positions - check for exits.
        """
        remaining_positions = []
        
        for pos in positions:
            # Check if expired
            if current_date >= pos['expiration']:
                # Simulate expiration P&L
                if current_price > pos['short_strike']:
                    # Spread expires worthless (max profit)
                    self._close_position(pos, current_date, current_price, 'expiration_profit')
                else:
                    # Spread in the money (max loss)
                    self._close_position(pos, current_date, current_price, 'expiration_loss')
                continue
            
            # Check profit target (50% of credit)
            # Simulate current spread value
            dte = (pos['expiration'] - current_date).days
            current_spread_value = self._estimate_spread_value(pos, current_price, dte)
            
            # Profit = credit received - current value
            profit = pos['credit'] - current_spread_value
            
            if profit >= pos['profit_target']:
                self._close_position(pos, current_date, current_price, 'profit_target')
                continue
            
            # Check stop loss
            loss = current_spread_value - pos['credit']
            if loss >= pos['stop_loss']:
                self._close_position(pos, current_date, current_price, 'stop_loss')
                continue
            
            # Update current value
            pos['current_value'] = -current_spread_value * pos['contracts'] * 100
            
            remaining_positions.append(pos)
        
        return remaining_positions
    
    def _estimate_spread_value(
        self,
        position: Dict,
        current_price: float,
        dte: int
    ) -> float:
        """
        Estimate current value of spread (simplified).
        
        Real implementation would use options pricing models.
        """
        short_strike = position['short_strike']
        spread_width = position['short_strike'] - position['long_strike']
        
        # If far OTM, value decays toward zero
        if current_price > short_strike * 1.05:
            # Well above short strike - rapid decay
            decay_factor = max(0, dte / 35)
            value = position['credit'] * decay_factor * 0.3
        elif current_price < short_strike * 0.95:
            # Below short strike - at risk
            distance = (short_strike - current_price) / short_strike
            value = spread_width * min(1.0, distance * 2)
        else:
            # Near the money - moderate value
            time_factor = dte / 35
            value = position['credit'] * 0.7 * time_factor
        
        return max(0, value)
    
    def _close_position(
        self,
        position: Dict,
        exit_date: datetime,
        exit_price: float,
        exit_reason: str
    ):
        """
        Close a position and record trade.
        """
        # Calculate P&L
        if exit_reason == 'expiration_profit':
            # Kept full credit
            pnl = position['credit'] * position['contracts'] * 100
        elif exit_reason == 'expiration_loss':
            # Max loss
            pnl = -position['max_loss'] * position['contracts'] * 100
        elif exit_reason == 'profit_target':
            # Closed at 50% profit
            pnl = position['profit_target'] * position['contracts'] * 100
        elif exit_reason == 'stop_loss':
            # Stopped out
            pnl = -position['stop_loss'] * position['contracts'] * 100
        else:
            # Other
            pnl = 0
        
        # Deduct exit commissions
        pnl -= position['commission']
        
        # Update capital
        self.capital += pnl
        
        # Record trade
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
    
    def _calculate_results(self) -> Dict:
        """
        Calculate backtest performance metrics.
        """
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
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
        
        # Profit factor: guard against zero denominators
        winning_total = winners['pnl'].sum() if len(winners) > 0 else 0
        losing_total = losers['pnl'].sum() if len(losers) > 0 else 0
        if losing_total != 0:
            profit_factor = round(abs(winning_total / losing_total), 2)
        elif winning_total > 0:
            profit_factor = float('inf')
        else:
            profit_factor = 0

        # Return percentage: guard against zero starting capital
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
        }
        
        return results
