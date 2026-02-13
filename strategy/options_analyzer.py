"""
Options Analysis Module
Handles options chain data, Greeks calculation, and IV analysis.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class OptionsAnalyzer:
    """
    Analyze options chains and calculate metrics.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize options analyzer.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.tradier = None
        self.polygon = None
        
        # Initialize data provider
        data_config = config.get('data', {})
        provider = data_config.get('provider', '')
        
        if provider == 'tradier':
            tradier_config = data_config.get('tradier', {})
            api_key = tradier_config.get('api_key', '')
            if api_key and api_key != 'YOUR_TRADIER_API_KEY':
                from strategy.tradier_provider import TradierProvider
                sandbox = tradier_config.get('sandbox', True)
                self.tradier = TradierProvider(api_key, sandbox=sandbox)
                logger.info("Using Tradier for real-time data")
        elif provider == 'polygon':
            polygon_config = data_config.get('polygon', {})
            api_key = polygon_config.get('api_key', '')
            if api_key:
                from strategy.polygon_provider import PolygonProvider
                self.polygon = PolygonProvider(api_key)
                logger.info("Using Polygon for real-time data")
        
        logger.info("OptionsAnalyzer initialized")
    
    def get_options_chain(self, ticker: str) -> pd.DataFrame:
        """
        Retrieve options chain for ticker.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            DataFrame with options chain data
        """
        # Use Tradier if available (real-time + real Greeks)
        if self.tradier:
            return self._get_chain_tradier(ticker)
        
        # Use Polygon if available
        if self.polygon:
            return self._get_chain_polygon(ticker)
        
        return self._get_chain_yfinance(ticker)

    def _get_chain_tradier(self, ticker: str) -> pd.DataFrame:
        """Get options chain via Tradier API with real Greeks."""
        try:
            min_dte = self.config['strategy'].get('min_dte', 30) - 5
            max_dte = self.config['strategy'].get('max_dte', 45) + 5
            chain = self.tradier.get_full_chain(ticker, min_dte=min_dte, max_dte=max_dte)
            if chain.empty:
                logger.warning(f"Tradier returned no data for {ticker}, falling back to yfinance")
                return self._get_chain_yfinance(ticker)
            logger.info(f"Retrieved {len(chain)} options for {ticker} via Tradier (real-time)")
            return chain
        except Exception as e:
            logger.error(f"Tradier error for {ticker}: {e}, falling back to yfinance")
            return self._get_chain_yfinance(ticker)

    def _get_chain_polygon(self, ticker: str) -> pd.DataFrame:
        """Get options chain via Polygon API with real Greeks."""
        try:
            min_dte = self.config['strategy'].get('min_dte', 30) - 5
            max_dte = self.config['strategy'].get('max_dte', 45) + 5
            chain = self.polygon.get_full_chain(ticker, min_dte=min_dte, max_dte=max_dte)
            if chain.empty:
                logger.warning(f"Polygon returned no data for {ticker}, falling back to yfinance")
                return self._get_chain_yfinance(ticker)
            logger.info(f"Retrieved {len(chain)} options for {ticker} via Polygon (real-time)")
            return chain
        except Exception as e:
            logger.error(f"Polygon error for {ticker}: {e}, falling back to yfinance")
            return self._get_chain_yfinance(ticker)

    def _get_chain_yfinance(self, ticker: str) -> pd.DataFrame:
        """Get options chain via yfinance (delayed, estimated Greeks)."""
        try:
            stock = yf.Ticker(ticker)
            expirations = stock.options
            
            if not expirations:
                logger.warning(f"No options available for {ticker}")
                return pd.DataFrame()
            
            all_options = []
            
            for exp_date_str in expirations:
                exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d')
                
                # Get options chain for this expiration
                opt_chain = stock.option_chain(exp_date_str)
                
                # Process calls
                calls = opt_chain.calls.copy()
                calls['type'] = 'call'
                calls['expiration'] = exp_date
                
                # Process puts
                puts = opt_chain.puts.copy()
                puts['type'] = 'put'
                puts['expiration'] = exp_date
                
                all_options.append(calls)
                all_options.append(puts)
            
            if not all_options:
                return pd.DataFrame()
            
            # Combine all options
            options_df = pd.concat(all_options, ignore_index=True)
            
            # Clean and standardize
            options_df = self._clean_options_data(options_df)
            
            logger.info(f"Retrieved {len(options_df)} options for {ticker}")
            
            return options_df
            
        except Exception as e:
            logger.error(f"Error retrieving options for {ticker}: {e}")
            return pd.DataFrame()
    
    def _clean_options_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and standardize options data.
        """
        # Rename columns to standard names
        column_mapping = {
            'lastTradeDate': 'last_trade_date',
            'impliedVolatility': 'iv',
            'inTheMoney': 'itm',
            'contractSymbol': 'contract_symbol',
            'lastPrice': 'last',
        }
        
        df = df.rename(columns=column_mapping)
        
        # Ensure required columns exist
        required_cols = ['strike', 'bid', 'ask', 'type', 'expiration']
        for col in required_cols:
            if col not in df.columns:
                logger.error(f"Missing required column: {col}")
                return pd.DataFrame()
        
        # Calculate mid price
        df['mid'] = (df['bid'] + df['ask']) / 2
        
        # Ensure delta exists (calculate if missing)
        if 'delta' not in df.columns:
            df['delta'] = self._estimate_delta(df)
        
        # Remove rows with zero bid/ask
        df = df[(df['bid'] > 0) & (df['ask'] > 0)].copy()
        
        return df
    
    def _estimate_delta(self, df: pd.DataFrame) -> pd.Series:
        """
        Estimate delta using vectorized Black-Scholes approximation.
        """
        from scipy.stats import norm

        logger.warning("Delta not available in data, using estimates")

        spot = df['strike'].median()
        now = datetime.now()
        risk_free = 0.045

        K = df['strike'].values.astype(float)
        T = np.maximum((df['expiration'] - now).dt.days.values / 365.0, 1/365)
        iv = df['iv'].fillna(0.20).values.astype(float)
        iv = np.where(iv <= 0, 0.20, iv)

        d1 = (np.log(spot / K) + (risk_free + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
        call_delta = norm.cdf(d1)
        put_delta = call_delta - 1

        is_call = (df['type'] == 'call').values
        delta = np.where(is_call, call_delta, put_delta)

        return pd.Series(np.round(np.abs(delta), 4), index=df.index)
    
    def calculate_iv_rank(self, ticker: str, current_iv: float) -> Dict:
        """
        Calculate IV rank and IV percentile.
        
        IV Rank = (Current IV - 52-week Low IV) / (52-week High IV - 52-week Low IV)
        
        Args:
            ticker: Stock ticker
            current_iv: Current implied volatility
            
        Returns:
            Dictionary with IV metrics
        """
        try:
            stock = yf.Ticker(ticker)
            
            # Get historical data (1 year)
            hist = stock.history(period='1y')
            
            if hist.empty:
                logger.warning(f"No historical data for {ticker}")
                return {'iv_rank': 0, 'iv_percentile': 0, 'current_iv': current_iv}
            
            # Calculate historical volatility as proxy for IV range
            # (In production, you'd want actual historical IV data)
            returns = hist['Close'].pct_change().dropna()
            hv_values = returns.rolling(window=20).std() * np.sqrt(252) * 100
            hv_values = hv_values.dropna()
            
            if len(hv_values) == 0:
                return {'iv_rank': 0, 'iv_percentile': 0, 'current_iv': current_iv}
            
            # IV Rank
            iv_min = hv_values.min()
            iv_max = hv_values.max()
            
            if iv_max > iv_min:
                iv_rank = ((current_iv - iv_min) / (iv_max - iv_min)) * 100
            else:
                iv_rank = 50
            
            # IV Percentile (what % of days had lower IV)
            iv_percentile = (hv_values < current_iv).sum() / len(hv_values) * 100
            
            return {
                'iv_rank': round(iv_rank, 2),
                'iv_percentile': round(iv_percentile, 2),
                'current_iv': round(current_iv, 2),
                'iv_min_52w': round(iv_min, 2),
                'iv_max_52w': round(iv_max, 2),
            }
            
        except Exception as e:
            logger.error(f"Error calculating IV rank for {ticker}: {e}")
            return {'iv_rank': 0, 'iv_percentile': 0, 'current_iv': current_iv}
    
    def get_current_iv(self, options_chain: pd.DataFrame) -> float:
        """
        Get current implied volatility from options chain.
        
        Uses ATM options for most accurate reading.
        """
        if options_chain.empty:
            return 0.0
        
        # Get ATM options (closest to current price)
        if 'iv' not in options_chain.columns:
            return 0.0
        
        # Average IV of near-dated ATM options
        iv_values = options_chain['iv'].dropna()
        
        if len(iv_values) == 0:
            return 0.0
        
        current_iv = iv_values.median() * 100  # Convert to percentage
        
        return round(current_iv, 2)
