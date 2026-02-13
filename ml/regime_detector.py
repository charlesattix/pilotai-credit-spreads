"""
Volatility Regime Detection Module

Uses Hidden Markov Models (HMM) and ensemble methods to detect market regimes.
Regimes: low_vol_trending, high_vol_trending, mean_reverting, crisis

Based on research:
- Kritzman et al. (2012): "Regime Shifts: Implications for Dynamic Strategies"
- Ang & Bekaert (2002): "Regime Switches in Interest Rates"
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional
from datetime import datetime, timedelta
import logging
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from hmmlearn import hmm
import yfinance as yf

logger = logging.getLogger(__name__)


class RegimeDetector:
    """
    Detects market volatility regimes using HMM and ensemble methods.
    
    Features:
    - Realized volatility (5/10/20 day)
    - VIX level and term structure
    - SPY-TLT correlation (risk-on/risk-off)
    - Market breadth (advance/decline)
    - RSI regime (overbought/oversold)
    """
    
    # Regime definitions
    REGIMES = {
        0: 'low_vol_trending',      # Low vol + directional (best for credit spreads)
        1: 'high_vol_trending',     # High vol + directional (risky but profitable)
        2: 'mean_reverting',        # Choppy, no trend (moderate risk)
        3: 'crisis',                # Extreme vol + fear (avoid new trades)
    }
    
    def __init__(self, lookback_days: int = 252):
        """
        Initialize regime detector.
        
        Args:
            lookback_days: Historical data window for training
        """
        self.lookback_days = lookback_days
        self.hmm_model = None
        self.rf_model = None
        self.scaler = StandardScaler()
        self.last_train_date = None
        self.trained = False
        
        logger.info(f"RegimeDetector initialized (lookback={lookback_days} days)")
    
    def fit(self, force_retrain: bool = False) -> bool:
        """
        Train the regime detection models.
        
        Args:
            force_retrain: Force retraining even if recently trained
            
        Returns:
            True if training successful
        """
        # Check if we need to retrain (daily retraining)
        if self.trained and not force_retrain:
            if self.last_train_date and (datetime.now().date() == self.last_train_date):
                logger.info("Models already trained today, skipping")
                return True
        
        try:
            logger.info("Training regime detection models...")
            
            # Fetch market data
            features_df = self._fetch_training_data()
            
            if features_df.empty or len(features_df) < 50:
                logger.warning("Insufficient data for training")
                return False
            
            # Prepare features
            X = features_df[self._get_feature_columns()].values
            
            # Handle NaN values
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            
            # Scale features
            X_scaled = self.scaler.fit_transform(X)
            
            # Train HMM (unsupervised regime detection)
            self.hmm_model = hmm.GaussianHMM(
                n_components=4,
                covariance_type="diag",
                n_iter=100,
                random_state=42
            )
            
            self.hmm_model.fit(X_scaled)
            
            # Get HMM state predictions for supervised training
            hmm_states = self.hmm_model.predict(X_scaled)
            
            # Map HMM states to regime labels using heuristics
            regime_labels = self._map_states_to_regimes(features_df, hmm_states)
            
            # Train Random Forest for interpretable regime prediction
            self.rf_model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_split=20,
                random_state=42
            )
            
            self.rf_model.fit(X_scaled, regime_labels)
            
            self.trained = True
            self.last_train_date = datetime.now().date()
            
            logger.info("✓ Regime models trained successfully")
            
            # Log feature importance
            self._log_feature_importance()
            
            return True
            
        except Exception as e:
            logger.error(f"Error training regime models: {e}")
            return False
    
    def detect_regime(self, ticker: str = 'SPY') -> Dict:
        """
        Detect current market regime.
        
        Args:
            ticker: Reference ticker (default: SPY)
            
        Returns:
            Dictionary with regime, confidence, and context
        """
        if not self.trained:
            logger.warning("Models not trained, training now...")
            if not self.fit():
                return self._get_default_regime()
        
        try:
            # Get current market features
            features = self._get_current_features(ticker)
            
            if features is None:
                return self._get_default_regime()
            
            # Prepare feature vector
            X = np.array([features[col] for col in self._get_feature_columns()]).reshape(1, -1)
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            X_scaled = self.scaler.transform(X)
            
            # Get HMM prediction
            hmm_state = self.hmm_model.predict(X_scaled)[0]
            
            # Get RF prediction and confidence
            rf_prediction = self.rf_model.predict(X_scaled)[0]
            rf_proba = self.rf_model.predict_proba(X_scaled)[0]
            confidence = float(rf_proba[rf_prediction])
            
            # Use RF prediction (more interpretable)
            regime_id = int(rf_prediction)
            regime_name = self.REGIMES[regime_id]
            
            result = {
                'regime': regime_name,
                'regime_id': regime_id,
                'confidence': round(confidence, 3),
                'hmm_state': int(hmm_state),
                'features': features,
                'timestamp': datetime.now().isoformat(),
            }
            
            logger.info(f"Detected regime: {regime_name} (confidence={confidence:.2%})")
            
            return result
            
        except Exception as e:
            logger.error(f"Error detecting regime: {e}")
            return self._get_default_regime()
    
    def _fetch_training_data(self) -> pd.DataFrame:
        """
        Fetch and compute features for training.
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.lookback_days + 60)
        
        # Fetch SPY (equity market)
        spy = yf.download('SPY', start=start_date, end=end_date, progress=False)
        
        # Fetch VIX (volatility)
        vix = yf.download('^VIX', start=start_date, end=end_date, progress=False)
        
        # Fetch TLT (bonds - for correlation)
        tlt = yf.download('TLT', start=start_date, end=end_date, progress=False)
        
        if spy.empty or vix.empty:
            logger.error("Failed to fetch market data")
            return pd.DataFrame()
        
        # Flatten MultiIndex columns from yfinance
        for df in [spy, vix, tlt]:
            if hasattr(df, 'columns') and isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        
        # Compute features
        features = pd.DataFrame(index=spy.index)
        
        # Realized volatility (multiple windows)
        returns = spy['Close'].pct_change()
        features['realized_vol_5d'] = returns.rolling(5).std() * np.sqrt(252) * 100
        features['realized_vol_10d'] = returns.rolling(10).std() * np.sqrt(252) * 100
        features['realized_vol_20d'] = returns.rolling(20).std() * np.sqrt(252) * 100
        
        # VIX features
        features['vix_level'] = vix['Close']
        
        # VIX term structure (VIX vs VIX3M ratio - approximated)
        features['vix_term_structure'] = vix['Close'] / vix['Close'].rolling(60).mean()
        
        # Trend strength
        features['spy_sma_20'] = spy['Close'].rolling(20).mean()
        features['spy_sma_50'] = spy['Close'].rolling(50).mean()
        close = spy['Close'].squeeze() if hasattr(spy['Close'], 'squeeze') else spy['Close']
        features['trend_strength'] = (close - features['spy_sma_20']) / features['spy_sma_20'] * 100
        
        # RSI
        features['rsi'] = self._calculate_rsi(close, period=14)
        
        # SPY-TLT correlation (risk-on/risk-off)
        if not tlt.empty:
            spy_ret = spy['Close'].pct_change()
            tlt_ret = tlt['Close'].pct_change()
            features['spy_tlt_corr'] = spy_ret.rolling(20).corr(tlt_ret)
        else:
            features['spy_tlt_corr'] = 0
        
        # Volume ratio (vs 20-day average)
        if 'Volume' in spy.columns:
            features['volume_ratio'] = spy['Volume'] / spy['Volume'].rolling(20).mean()
        else:
            features['volume_ratio'] = 1.0
        
        # Drop NaN rows
        features = features.dropna()
        
        return features
    
    def _get_current_features(self, ticker: str) -> Optional[Dict]:
        """
        Get current market features for regime detection.
        """
        try:
            # Fetch recent data
            spy = yf.download('SPY', period='3mo', progress=False)
            vix = yf.download('^VIX', period='3mo', progress=False)
            tlt = yf.download('TLT', period='3mo', progress=False)
            
            if spy.empty or vix.empty:
                return None
            
            # Flatten MultiIndex columns from yfinance
            for df in [spy, vix, tlt]:
                if hasattr(df, 'columns') and isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
            
            # Latest values
            returns = spy['Close'].pct_change()
            
            features = {
                'realized_vol_5d': float(returns.tail(5).std() * np.sqrt(252) * 100),
                'realized_vol_10d': float(returns.tail(10).std() * np.sqrt(252) * 100),
                'realized_vol_20d': float(returns.tail(20).std() * np.sqrt(252) * 100),
                'vix_level': float(vix['Close'].iloc[-1]),
                'vix_term_structure': float(vix['Close'].iloc[-1] / vix['Close'].tail(60).mean()),
                'spy_sma_20': float(spy['Close'].tail(20).mean()),
                'spy_sma_50': float(spy['Close'].tail(50).mean()),
                'rsi': float(self._calculate_rsi(spy['Close'], period=14).iloc[-1]),
                'volume_ratio': float(spy['Volume'].iloc[-1] / spy['Volume'].tail(20).mean() if 'Volume' in spy.columns else 1.0),
            }
            
            # Trend strength
            close_last = float(spy['Close'].iloc[-1]) if hasattr(spy['Close'].iloc[-1], '__float__') else spy['Close'].iloc[-1]
            features['trend_strength'] = (close_last - features['spy_sma_20']) / features['spy_sma_20'] * 100
            
            # SPY-TLT correlation
            if not tlt.empty:
                spy_ret = spy['Close'].pct_change()
                tlt_ret = tlt['Close'].pct_change()
                features['spy_tlt_corr'] = float(spy_ret.tail(20).corr(tlt_ret.tail(20)))
            else:
                features['spy_tlt_corr'] = 0.0
            
            return features
            
        except Exception as e:
            logger.error(f"Error computing current features: {e}")
            return None
    
    def _map_states_to_regimes(self, features_df: pd.DataFrame, hmm_states: np.ndarray) -> np.ndarray:
        """
        Map HMM states to interpretable regime labels using heuristics.
        """
        regime_labels = np.zeros(len(hmm_states), dtype=int)
        
        for i in range(len(hmm_states)):
            state = hmm_states[i]
            
            # Get feature values
            vix = features_df['vix_level'].iloc[i]
            rv_20 = features_df['realized_vol_20d'].iloc[i]
            trend = abs(features_df['trend_strength'].iloc[i])
            
            # Crisis: VIX > 30 or RV > 30
            if vix > 30 or rv_20 > 30:
                regime_labels[i] = 3  # crisis
            
            # Low vol trending: VIX < 20, RV < 15, strong trend
            elif vix < 20 and rv_20 < 15 and trend > 2:
                regime_labels[i] = 0  # low_vol_trending
            
            # High vol trending: VIX 20-30, strong trend
            elif 20 <= vix < 30 and trend > 2:
                regime_labels[i] = 1  # high_vol_trending
            
            # Mean reverting: choppy, no clear trend
            else:
                regime_labels[i] = 2  # mean_reverting
        
        return regime_labels
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """
        Calculate RSI (Relative Strength Index).
        """
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _get_feature_columns(self) -> list:
        """
        Get ordered list of feature column names.
        """
        return [
            'realized_vol_5d',
            'realized_vol_10d',
            'realized_vol_20d',
            'vix_level',
            'vix_term_structure',
            'spy_sma_20',
            'spy_sma_50',
            'trend_strength',
            'rsi',
            'spy_tlt_corr',
            'volume_ratio',
        ]
    
    def _log_feature_importance(self):
        """
        Log feature importance from Random Forest model.
        """
        if self.rf_model is None:
            return
        
        feature_names = self._get_feature_columns()
        importances = self.rf_model.feature_importances_
        
        logger.info("Feature importance for regime detection:")
        for name, importance in sorted(zip(feature_names, importances), key=lambda x: x[1], reverse=True)[:5]:
            logger.info(f"  {name}: {importance:.3f}")
    
    def _get_default_regime(self) -> Dict:
        """
        Return default regime when detection fails.
        """
        return {
            'regime': 'mean_reverting',
            'regime_id': 2,
            'confidence': 0.5,
            'hmm_state': 2,
            'features': {},
            'timestamp': datetime.now().isoformat(),
            'fallback': True,
        }
