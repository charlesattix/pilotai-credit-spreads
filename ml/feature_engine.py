"""
Feature Engineering Module for Credit Spread Trading

Builds comprehensive feature sets combining technical, volatility, market,
event risk, and seasonal factors.

Based on research:
- Fama & French (1993): Multi-factor models
- Jegadeesh & Titman (1993): Momentum factors
- Cooper et al. (2006): Asset growth and returns
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional
from datetime import datetime, timedelta
import logging
import yfinance as yf
from scipy import stats
from shared.indicators import calculate_rsi
from shared.constants import FOMC_DATES

logger = logging.getLogger(__name__)


class FeatureEngine:
    """
    Comprehensive feature engineering for options trading ML models.
    
    Feature categories:
    1. Technical: RSI, MACD, Bollinger %B, ATR, volume
    2. Volatility: IV rank, skew, realized vs implied
    3. Market: VIX, put/call ratio, breadth
    4. Event risk: earnings, FOMC, CPI dates
    5. Seasonal: day of week, month, OPEX
    """
    
    def __init__(self, data_cache=None):
        """
        Initialize feature engine.

        Args:
            data_cache: Optional DataCache instance for shared data retrieval.
        """
        self.data_cache = data_cache
        self.feature_cache = {}
        self.cache_timestamps = {}
        
        # Known FOMC meeting dates 2025-2026
        self.fomc_dates = FOMC_DATES
        
        # CPI release dates (typically 2nd week of month)
        self.cpi_months = list(range(1, 13))
        
        logger.info("FeatureEngine initialized")

    def _download(self, ticker, period='6mo'):
        if self.data_cache:
            return self.data_cache.get_history(ticker, period)
        return yf.download(ticker, period=period, progress=False)

    def build_features(
        self,
        ticker: str,
        current_price: float,
        options_chain: pd.DataFrame,
        regime_data: Optional[Dict] = None,
        iv_analysis: Optional[Dict] = None,
        technical_signals: Optional[Dict] = None,
    ) -> Dict:
        """
        Build complete feature set for a potential trade.
        
        Args:
            ticker: Stock ticker
            current_price: Current stock price
            options_chain: Options chain data
            regime_data: Regime detection results
            iv_analysis: IV surface analysis
            technical_signals: Technical analysis signals
            
        Returns:
            Dictionary of features
        """
        try:
            # Initialize feature dict
            features = {
                'ticker': ticker,
                'timestamp': datetime.now().isoformat(),
                'current_price': current_price,
            }
            
            # 1. Technical features
            tech_features = self._compute_technical_features(ticker, current_price)
            features.update(tech_features)
            
            # 2. Volatility features
            vol_features = self._compute_volatility_features(
                ticker, options_chain, iv_analysis
            )
            features.update(vol_features)
            
            # 3. Market features
            market_features = self._compute_market_features()
            features.update(market_features)
            
            # 4. Event risk features
            event_features = self._compute_event_risk_features(ticker)
            features.update(event_features)
            
            # 5. Seasonal features
            seasonal_features = self._compute_seasonal_features()
            features.update(seasonal_features)
            
            # 6. Regime features (if available)
            if regime_data:
                features.update(self._extract_regime_features(regime_data))
            
            # 7. Derived features
            derived_features = self._compute_derived_features(features)
            features.update(derived_features)
            
            logger.info(f"Built {len(features)} features for {ticker}")
            
            return features
            
        except Exception as e:
            logger.error(f"Error building features for {ticker}: {e}")
            return {'ticker': ticker, 'error': str(e)}
    
    def _compute_technical_features(self, ticker: str, current_price: float) -> Dict:
        """
        Compute technical indicators.
        """
        try:
            # Fetch price data
            stock = self._download(ticker, period='6mo')
            
            if stock.empty:
                return self._get_default_technical_features()
            
            close = stock['Close']
            high = stock['High']
            low = stock['Low']
            volume = stock['Volume'] if 'Volume' in stock.columns else pd.Series(index=stock.index)
            
            features = {}
            
            # RSI (14-day)
            features['rsi_14'] = float(self._calculate_rsi(close, 14).iloc[-1])
            
            # MACD
            macd_line, signal_line, macd_hist = self._calculate_macd(close)
            features['macd'] = float(macd_line.iloc[-1])
            features['macd_signal'] = float(signal_line.iloc[-1])
            features['macd_histogram'] = float(macd_hist.iloc[-1])
            
            # Bollinger Bands %B
            features['bollinger_pct_b'] = float(self._calculate_bollinger_pct_b(close).iloc[-1])
            
            # ATR (14-day)
            features['atr_14'] = float(self._calculate_atr(high, low, close, 14).iloc[-1])
            features['atr_pct'] = float(features['atr_14'] / current_price * 100)
            
            # Volume ratio (current vs 20-day average)
            if not volume.empty:
                vol_ma20 = volume.rolling(20).mean().iloc[-1]
                features['volume_ratio'] = float(volume.iloc[-1] / vol_ma20 if vol_ma20 > 0 else 1.0)
            else:
                features['volume_ratio'] = 1.0
            
            # Price momentum (5, 10, 20 day returns)
            features['return_5d'] = float((close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) > 5 else 0)
            features['return_10d'] = float((close.iloc[-1] / close.iloc[-11] - 1) * 100 if len(close) > 10 else 0)
            features['return_20d'] = float((close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) > 20 else 0)
            
            # Distance from moving averages
            sma_20 = close.rolling(20).mean().iloc[-1]
            sma_50 = close.rolling(50).mean().iloc[-1]
            sma_200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else sma_50
            
            features['dist_from_sma20_pct'] = float((current_price - sma_20) / sma_20 * 100)
            features['dist_from_sma50_pct'] = float((current_price - sma_50) / sma_50 * 100)
            features['dist_from_sma200_pct'] = float((current_price - sma_200) / sma_200 * 100)
            
            return features
            
        except Exception as e:
            logger.error(f"Error computing technical features: {e}")
            return self._get_default_technical_features()
    
    def _compute_volatility_features(
        self,
        ticker: str,
        options_chain: pd.DataFrame,
        iv_analysis: Optional[Dict]
    ) -> Dict:
        """
        Compute volatility-based features.
        """
        try:
            features = {}
            
            # Realized volatility (historical)
            stock = self._download(ticker, period='3mo')
            
            if not stock.empty:
                returns = stock['Close'].pct_change()
                features['realized_vol_10d'] = float(returns.tail(10).std() * np.sqrt(252) * 100)
                features['realized_vol_20d'] = float(returns.tail(20).std() * np.sqrt(252) * 100)
                features['realized_vol_60d'] = float(returns.tail(60).std() * np.sqrt(252) * 100)
            else:
                features['realized_vol_10d'] = 20.0
                features['realized_vol_20d'] = 20.0
                features['realized_vol_60d'] = 20.0
            
            # IV features from analysis
            if iv_analysis and iv_analysis.get('iv_rank_percentile', {}).get('available'):
                iv_data = iv_analysis['iv_rank_percentile']
                features['iv_rank'] = float(iv_data.get('iv_rank', 50))
                features['iv_percentile'] = float(iv_data.get('iv_percentile', 50))
                features['current_iv'] = float(iv_data.get('current_iv', 20))
            else:
                # Fallback: compute from options chain
                if not options_chain.empty and 'iv' in options_chain.columns:
                    features['current_iv'] = float(options_chain['iv'].median() * 100)
                else:
                    features['current_iv'] = 20.0
                
                features['iv_rank'] = 50.0
                features['iv_percentile'] = 50.0
            
            # Realized vs Implied spread
            features['rv_iv_spread'] = features['realized_vol_20d'] - features['current_iv']
            
            # Skew features
            if iv_analysis and iv_analysis.get('skew', {}).get('available'):
                skew_data = iv_analysis['skew']
                features['put_call_skew_ratio'] = float(skew_data.get('put_call_skew_ratio', 1.0))
                features['put_skew_steepness'] = float(skew_data.get('put_skew_steepness', 0))
            else:
                features['put_call_skew_ratio'] = 1.0
                features['put_skew_steepness'] = 0.0
            
            return features
            
        except Exception as e:
            logger.error(f"Error computing volatility features: {e}")
            return {
                'realized_vol_10d': 20.0,
                'realized_vol_20d': 20.0,
                'realized_vol_60d': 20.0,
                'iv_rank': 50.0,
                'iv_percentile': 50.0,
                'current_iv': 20.0,
                'rv_iv_spread': 0.0,
                'put_call_skew_ratio': 1.0,
                'put_skew_steepness': 0.0,
            }
    
    def _compute_market_features(self) -> Dict:
        """
        Compute market-wide features.
        """
        try:
            features = {}
            
            # VIX
            vix = self._download('^VIX', period='5d')
            if not vix.empty:
                features['vix_level'] = float(vix['Close'].iloc[-1])
                features['vix_change_1d'] = float(vix['Close'].pct_change().iloc[-1] * 100)
            else:
                features['vix_level'] = 15.0
                features['vix_change_1d'] = 0.0
            
            # Put/Call ratio (approximation using VIX)
            # In production, use actual CBOE put/call data
            features['put_call_ratio'] = 1.0  # Placeholder
            
            # Market trend (SPY)
            spy = self._download('SPY', period='3mo')
            if not spy.empty:
                spy_returns = spy['Close'].pct_change()
                features['spy_return_5d'] = float((spy['Close'].iloc[-1] / spy['Close'].iloc[-6] - 1) * 100 if len(spy) > 5 else 0)
                features['spy_return_20d'] = float((spy['Close'].iloc[-1] / spy['Close'].iloc[-21] - 1) * 100 if len(spy) > 20 else 0)
                
                # SPY volatility
                features['spy_realized_vol'] = float(spy_returns.tail(20).std() * np.sqrt(252) * 100)
            else:
                features['spy_return_5d'] = 0.0
                features['spy_return_20d'] = 0.0
                features['spy_realized_vol'] = 15.0
            
            return features
            
        except Exception as e:
            logger.error(f"Error computing market features: {e}")
            return {
                'vix_level': 15.0,
                'vix_change_1d': 0.0,
                'put_call_ratio': 1.0,
                'spy_return_5d': 0.0,
                'spy_return_20d': 0.0,
                'spy_realized_vol': 15.0,
            }
    
    def _compute_event_risk_features(self, ticker: str) -> Dict:
        """
        Compute event risk features.
        """
        try:
            features = {}
            now = datetime.now()
            
            # Days to next earnings
            try:
                stock = yf.Ticker(ticker)
                calendar = stock.calendar
                
                if calendar is not None and 'Earnings Date' in calendar:
                    earnings_date = pd.to_datetime(calendar['Earnings Date'])
                    if isinstance(earnings_date, pd.Series):
                        earnings_date = earnings_date.iloc[0]
                    
                    days_to_earnings = (earnings_date - now).days
                    features['days_to_earnings'] = max(0, days_to_earnings)
                else:
                    features['days_to_earnings'] = 999  # Unknown
            except Exception as e:
                logger.warning(f"Failed to get earnings for {ticker}: {e}")
                features['days_to_earnings'] = 999
            
            # Days to next FOMC
            upcoming_fomc = [d for d in self.fomc_dates if d > now]
            if upcoming_fomc:
                days_to_fomc = (min(upcoming_fomc) - now).days
                features['days_to_fomc'] = days_to_fomc
                features['fomc_risk'] = 1.0 if days_to_fomc < 7 else 0.0
            else:
                features['days_to_fomc'] = 999
                features['fomc_risk'] = 0.0
            
            # Days to next CPI (approx 2nd week of each month)
            current_month = now.month
            current_day = now.day
            
            if current_day < 14:
                # CPI this month (around day 12-14)
                days_to_cpi = 13 - current_day
            else:
                # CPI next month
                days_in_month = 30  # Approximation
                days_to_cpi = days_in_month - current_day + 13
            
            features['days_to_cpi'] = days_to_cpi
            features['cpi_risk'] = 1.0 if days_to_cpi < 5 else 0.0
            
            # Overall event risk score
            min_days = min(
                features['days_to_earnings'],
                features['days_to_fomc'],
                features['days_to_cpi']
            )
            
            if min_days < 7:
                features['event_risk_score'] = 0.8
            elif min_days < 14:
                features['event_risk_score'] = 0.5
            else:
                features['event_risk_score'] = 0.2
            
            return features
            
        except Exception as e:
            logger.error(f"Error computing event risk features: {e}")
            return {
                'days_to_earnings': 999,
                'days_to_fomc': 999,
                'days_to_cpi': 30,
                'fomc_risk': 0.0,
                'cpi_risk': 0.0,
                'event_risk_score': 0.2,
            }
    
    def _compute_seasonal_features(self) -> Dict:
        """
        Compute seasonal/calendar features.
        """
        try:
            now = datetime.now()
            
            features = {
                'day_of_week': now.weekday(),  # 0=Monday, 4=Friday
                'day_of_month': now.day,
                'month': now.month,
                'quarter': (now.month - 1) // 3 + 1,
            }
            
            # OPEX week (3rd Friday of month)
            # Simplified: assume days 15-21
            features['is_opex_week'] = 1.0 if 15 <= now.day <= 21 else 0.0
            
            # Monday effect (higher volatility)
            features['is_monday'] = 1.0 if now.weekday() == 0 else 0.0
            
            # End of month effect
            features['is_month_end'] = 1.0 if now.day >= 25 else 0.0
            
            return features
            
        except Exception as e:
            logger.error(f"Error computing seasonal features: {e}")
            return {
                'day_of_week': 2,
                'day_of_month': 15,
                'month': 1,
                'quarter': 1,
                'is_opex_week': 0.0,
                'is_monday': 0.0,
                'is_month_end': 0.0,
            }
    
    def _extract_regime_features(self, regime_data: Dict) -> Dict:
        """
        Extract features from regime detection.
        """
        features = {
            'regime_id': regime_data.get('regime_id', 2),
            'regime_confidence': regime_data.get('confidence', 0.5),
        }
        
        # One-hot encode regime
        regime_id = features['regime_id']
        features['regime_low_vol_trending'] = 1.0 if regime_id == 0 else 0.0
        features['regime_high_vol_trending'] = 1.0 if regime_id == 1 else 0.0
        features['regime_mean_reverting'] = 1.0 if regime_id == 2 else 0.0
        features['regime_crisis'] = 1.0 if regime_id == 3 else 0.0
        
        return features
    
    def _compute_derived_features(self, features: Dict) -> Dict:
        """
        Compute derived/interaction features.
        """
        derived = {}
        
        # RSI extremes
        rsi = features.get('rsi_14', 50)
        derived['rsi_oversold'] = 1.0 if rsi < 30 else 0.0
        derived['rsi_overbought'] = 1.0 if rsi > 70 else 0.0
        
        # IV rank extremes
        iv_rank = features.get('iv_rank', 50)
        derived['iv_rank_high'] = 1.0 if iv_rank > 70 else 0.0
        derived['iv_rank_low'] = 1.0 if iv_rank < 30 else 0.0
        
        # Volatility regime interaction
        # High IV + low realized vol = good for selling premium
        rv = features.get('realized_vol_20d', 20)
        iv = features.get('current_iv', 20)
        derived['vol_premium'] = iv - rv
        derived['vol_premium_pct'] = (iv - rv) / rv * 100 if rv > 0 else 0
        
        # Risk-adjusted momentum
        atr_pct = features.get('atr_pct', 2)
        return_20d = features.get('return_20d', 0)
        derived['risk_adjusted_momentum'] = return_20d / atr_pct if atr_pct > 0 else 0
        
        return derived
    
    # Helper methods for technical indicators
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI."""
        return calculate_rsi(prices, period)
    
    def _calculate_macd(self, prices: pd.Series, fast=12, slow=26, signal=9) -> tuple:
        """Calculate MACD."""
        ema_fast = prices.ewm(span=fast).mean()
        ema_slow = prices.ewm(span=slow).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    def _calculate_bollinger_pct_b(self, prices: pd.Series, period=20, std_dev=2) -> pd.Series:
        """Calculate Bollinger %B."""
        sma = prices.rolling(period).mean()
        std = prices.rolling(period).std()
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        pct_b = (prices - lower_band) / (upper_band - lower_band)
        return pct_b
    
    def _calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
        """Calculate ATR."""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return atr
    
    def _get_default_technical_features(self) -> Dict:
        """Return default technical features."""
        return {
            'rsi_14': 50.0,
            'macd': 0.0,
            'macd_signal': 0.0,
            'macd_histogram': 0.0,
            'bollinger_pct_b': 0.5,
            'atr_14': 1.0,
            'atr_pct': 2.0,
            'volume_ratio': 1.0,
            'return_5d': 0.0,
            'return_10d': 0.0,
            'return_20d': 0.0,
            'dist_from_sma20_pct': 0.0,
            'dist_from_sma50_pct': 0.0,
            'dist_from_sma200_pct': 0.0,
        }
    
    def get_feature_names(self) -> list:
        """
        Get list of all feature names for model training.
        """
        return [
            # Technical
            'rsi_14', 'macd', 'macd_signal', 'macd_histogram',
            'bollinger_pct_b', 'atr_pct', 'volume_ratio',
            'return_5d', 'return_10d', 'return_20d',
            'dist_from_sma20_pct', 'dist_from_sma50_pct', 'dist_from_sma200_pct',
            
            # Volatility
            'realized_vol_10d', 'realized_vol_20d', 'realized_vol_60d',
            'iv_rank', 'iv_percentile', 'current_iv', 'rv_iv_spread',
            'put_call_skew_ratio', 'put_skew_steepness',
            
            # Market
            'vix_level', 'vix_change_1d', 'put_call_ratio',
            'spy_return_5d', 'spy_return_20d', 'spy_realized_vol',
            
            # Event risk
            'days_to_earnings', 'days_to_fomc', 'days_to_cpi',
            'event_risk_score',
            
            # Seasonal
            'day_of_week', 'is_opex_week', 'is_monday', 'is_month_end',
            
            # Regime
            'regime_id', 'regime_confidence',
            'regime_low_vol_trending', 'regime_high_vol_trending',
            'regime_mean_reverting', 'regime_crisis',
            
            # Derived
            'rsi_oversold', 'rsi_overbought',
            'iv_rank_high', 'iv_rank_low',
            'vol_premium', 'vol_premium_pct',
            'risk_adjusted_momentum',
        ]
