"""
Signal Model - ML-based Trade Prediction

XGBoost classifier to predict credit spread profitability.
Target: Binary classification (profitable=1, unprofitable=0)

Based on research:
- Chen & Guestrin (2016): XGBoost paper
- Niculescu-Mizil & Caruana (2005): Predicting good probabilities with supervised learning
"""

import json
import os
import threading

import numpy as np
import pandas as pd
from collections import Counter
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone
import logging
import joblib
from pathlib import Path

try:
    import xgboost as xgb
except ImportError:
    xgb = None
    logging.warning("XGBoost not available, install with: pip install xgboost")

from sklearn.model_selection import train_test_split
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
from shared.indicators import sanitize_features
from shared.types import PredictionResult

logger = logging.getLogger(__name__)


class SignalModel:
    """
    XGBoost-based signal model for credit spread trading.
    
    Predicts probability that a credit spread will be profitable at expiration.
    Uses calibrated probabilities for better position sizing.
    """

    def __init__(self, model_dir: str = 'ml/models'):
        """
        Initialize signal model.
        
        Args:
            model_dir: Directory to save/load trained models
        """
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self.model = None
        self.calibrated_model = None
        self.feature_names = None
        self.trained = False
        self.training_stats = {}
        self.feature_means: Optional[np.ndarray] = None
        self.feature_stds: Optional[np.ndarray] = None
        self._fallback_lock = threading.Lock()
        self.fallback_counter: Counter = Counter()

        logger.info(f"SignalModel initialized (model_dir={model_dir})")

    def train(
        self,
        features_df: pd.DataFrame,
        labels: np.ndarray,
        calibrate: bool = True,
        save_model: bool = True
    ) -> Dict:
        """
        Train the signal model.
        
        Args:
            features_df: Feature DataFrame
            labels: Binary labels (1=profitable, 0=unprofitable)
            calibrate: Whether to calibrate probabilities
            save_model: Whether to save trained model
            
        Returns:
            Training statistics dictionary
        """
        if xgb is None:
            logger.error("XGBoost not installed")
            return {}

        try:
            logger.info(f"Training signal model on {len(features_df)} samples...")

            # Prepare data
            self.feature_names = list(features_df.columns)
            X = features_df.values
            y = labels

            # Handle NaN and inf
            X = sanitize_features(X)

            # Train/test split
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )

            # Split training data to create a validation set (for early
            # stopping) and optionally a calibration set. The held-out test
            # set is NEVER used during training or early stopping to prevent
            # data leakage.
            if calibrate:
                # 60% inner train, 20% validation (early stopping), 20% calibration
                X_train_rest, X_cal, y_train_rest, y_cal = train_test_split(
                    X_train, y_train, test_size=0.2, random_state=42, stratify=y_train
                )
                X_train_inner, X_val, y_train_inner, y_val = train_test_split(
                    X_train_rest, y_train_rest, test_size=0.25, random_state=42, stratify=y_train_rest
                )
            else:
                # 80% inner train, 20% validation (early stopping)
                X_train_inner, X_val, y_train_inner, y_val = train_test_split(
                    X_train, y_train, test_size=0.2, random_state=42, stratify=y_train
                )

            # XGBoost parameters (tuned for credit spread prediction)
            params = {
                'objective': 'binary:logistic',
                'max_depth': 6,
                'learning_rate': 0.05,
                'n_estimators': 200,
                'min_child_weight': 5,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'gamma': 1,
                'reg_alpha': 0.1,
                'reg_lambda': 1.0,
                'random_state': 42,
                'eval_metric': 'logloss',
            }

            # Train model on inner training set; use validation set for early
            # stopping (NOT the test set — that would cause data leakage).
            self.model = xgb.XGBClassifier(**params)

            self.model.fit(
                X_train_inner, y_train_inner,
                eval_set=[(X_val, y_val)],
                verbose=False
            )

            # Predictions
            y_pred_train = self.model.predict(X_train_inner)
            y_pred_test = self.model.predict(X_test)

            y_proba_train = self.model.predict_proba(X_train_inner)[:, 1]
            y_proba_test = self.model.predict_proba(X_test)[:, 1]

            # Calibration on held-out calibration set (not test set)
            if calibrate:
                logger.info("Calibrating probabilities on held-out calibration set...")
                self.calibrated_model = CalibratedClassifierCV(
                    self.model,
                    method='sigmoid',
                    cv='prefit'
                )
                self.calibrated_model.fit(X_cal, y_cal)

                y_proba_test_cal = self.calibrated_model.predict_proba(X_test)[:, 1]
            else:
                self.calibrated_model = None
                y_proba_test_cal = y_proba_test

            # Compute metrics
            stats = {
                'train_accuracy': float(accuracy_score(y_train_inner, y_pred_train)),
                'test_accuracy': float(accuracy_score(y_test, y_pred_test)),
                'train_precision': float(precision_score(y_train_inner, y_pred_train, zero_division=0)),
                'test_precision': float(precision_score(y_test, y_pred_test, zero_division=0)),
                'train_recall': float(recall_score(y_train_inner, y_pred_train, zero_division=0)),
                'test_recall': float(recall_score(y_test, y_pred_test, zero_division=0)),
                'train_auc': float(roc_auc_score(y_train_inner, y_proba_train)),
                'test_auc': float(roc_auc_score(y_test, y_proba_test)),
                'test_auc_calibrated': float(roc_auc_score(y_test, y_proba_test_cal)) if calibrate else None,
                'n_train': len(X_train_inner),
                'n_validation': len(X_val),
                'n_test': len(X_test),
                'n_calibration': len(X_cal) if calibrate else 0,
                'n_features': X.shape[1],
                'positive_rate': float(y.mean()),
            }

            self.training_stats = stats
            self.trained = True

            logger.info("✓ Model training complete")
            logger.info(f"  Test Accuracy: {stats['test_accuracy']:.3f}")
            logger.info(f"  Test AUC: {stats['test_auc']:.3f}")
            logger.info(f"  Test Precision: {stats['test_precision']:.3f}")
            logger.info(f"  Test Recall: {stats['test_recall']:.3f}")

            # Feature importance
            self._log_feature_importance()

            # Compute feature distribution stats for drift monitoring
            self.feature_means = np.mean(X, axis=0)
            self.feature_stds = np.std(X, axis=0)
            logger.info("Computed feature distribution stats for monitoring")

            # Save model
            if save_model:
                self.save(f"signal_model_{datetime.now(timezone.utc).strftime('%Y%m%d')}.joblib")

            return stats

        except Exception as e:
            logger.error(f"Error training model: {e}", exc_info=True)
            return {}

    def predict(self, features: Dict) -> PredictionResult:
        """
        Predict profitability for a single trade.
        
        Args:
            features: Feature dictionary
            
        Returns:
            Prediction dictionary with probability and confidence
        """
        if not self.trained:
            logger.warning("Model not trained, loading default model...")
            if not self.load():
                return self._get_default_prediction()

        try:
            # Prepare feature vector
            X = self._features_to_array(features)

            if X is None:
                return self._get_default_prediction()

            # Check for feature distribution drift
            self._check_feature_distribution(X)

            # Predict with calibrated model if available
            model = self.calibrated_model if self.calibrated_model else self.model

            prediction = int(model.predict(X)[0])
            probability = float(model.predict_proba(X)[0, 1])

            # Confidence score (distance from 0.5)
            confidence = abs(probability - 0.5) * 2

            result = {
                'prediction': prediction,
                'probability': round(probability, 4),
                'confidence': round(confidence, 4),
                'signal': 'bullish' if probability > 0.55 else 'bearish' if probability < 0.45 else 'neutral',
                'signal_strength': round(probability * 100, 1),
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }

            return result

        except Exception as e:
            with self._fallback_lock:
                self.fallback_counter['predict'] += 1
                count = self.fallback_counter['predict']
            logger.error(f"Error making prediction (fallback #{count}): {e}", exc_info=True)
            if count >= 10:
                logger.critical(f"SignalModel predict has fallen back {count} times — investigate")
            return self._get_default_prediction()

    def predict_batch(self, features_df: pd.DataFrame) -> np.ndarray:
        """
        Predict probabilities for a batch of trades.
        
        Args:
            features_df: Feature DataFrame
            
        Returns:
            Array of probabilities
        """
        if not self.trained:
            logger.warning("Model not trained")
            return np.ones(len(features_df)) * 0.5

        try:
            X = features_df[self.feature_names].values
            X = sanitize_features(X)

            # Check for feature distribution drift
            self._check_feature_distribution(X)

            model = self.calibrated_model if self.calibrated_model else self.model
            probabilities = model.predict_proba(X)[:, 1]

            return probabilities

        except Exception as e:
            with self._fallback_lock:
                self.fallback_counter['predict_batch'] += 1
                count = self.fallback_counter['predict_batch']
            logger.error(f"Error in batch prediction (fallback #{count}): {e}", exc_info=True)
            if count >= 10:
                logger.critical(f"SignalModel predict_batch has fallen back {count} times — investigate")
            return np.ones(len(features_df)) * 0.5

    def backtest(self, features_df: pd.DataFrame, labels: np.ndarray) -> Dict:
        """
        Backtest the model on historical data.
        
        Args:
            features_df: Historical features
            labels: Historical outcomes
            
        Returns:
            Backtest metrics
        """
        try:
            if not self.trained:
                logger.error("Model not trained")
                return {}

            logger.info(f"Backtesting on {len(features_df)} historical trades...")

            # Predict
            probabilities = self.predict_batch(features_df)
            predictions = (probabilities > 0.5).astype(int)

            # Metrics
            accuracy = accuracy_score(labels, predictions)
            precision = precision_score(labels, predictions, zero_division=0)
            recall = recall_score(labels, predictions, zero_division=0)
            auc = roc_auc_score(labels, probabilities)

            # Profitability by confidence threshold
            confidence_thresholds = [0.6, 0.7, 0.8]
            threshold_results = {}

            for thresh in confidence_thresholds:
                confident_mask = np.abs(probabilities - 0.5) * 2 >= (thresh - 0.5)

                if confident_mask.sum() > 0:
                    conf_accuracy = accuracy_score(
                        labels[confident_mask],
                        predictions[confident_mask]
                    )
                    conf_count = confident_mask.sum()

                    threshold_results[f'conf_{thresh:.1f}'] = {
                        'accuracy': float(conf_accuracy),
                        'count': int(conf_count),
                        'pct_trades': float(conf_count / len(labels) * 100),
                    }

            results = {
                'accuracy': float(accuracy),
                'precision': float(precision),
                'recall': float(recall),
                'auc': float(auc),
                'n_trades': len(labels),
                'win_rate': float(labels.mean()),
                'threshold_results': threshold_results,
            }

            logger.info("✓ Backtest complete")
            logger.info(f"  Accuracy: {accuracy:.3f}")
            logger.info(f"  AUC: {auc:.3f}")
            logger.info(f"  Win Rate: {labels.mean():.3f}")

            return results

        except Exception as e:
            logger.error(f"Error in backtest: {e}", exc_info=True)
            return {}

    def _features_to_array(self, features: Dict) -> Optional[np.ndarray]:
        """
        Convert feature dictionary to numpy array.
        """
        if self.feature_names is None:
            logger.error("Feature names not set")
            return None

        try:
            # Extract features in correct order
            feature_values = []
            missing = []
            for name in self.feature_names:
                if name not in features:
                    missing.append(name)
                    feature_values.append(0.0)
                    continue
                value = features[name]
                if value is None or np.isnan(value):
                    value = 0.0
                feature_values.append(value)
            if missing:
                logger.warning(f"Missing {len(missing)} features (filled with 0.0): {missing}")

            X = np.array(feature_values).reshape(1, -1)
            X = sanitize_features(X)

            return X

        except Exception as e:
            logger.error(f"Error converting features to array: {e}", exc_info=True)
            return None

    def _check_feature_distribution(self, X: np.ndarray) -> None:
        """
        Check whether any feature values are far from the training distribution.

        Logs a warning for each feature whose value is more than 3 standard
        deviations from its training mean.  Silently skips the check when
        distribution stats are unavailable (e.g. models saved before this
        feature was added).

        Args:
            X: Feature array of shape (n_samples, n_features).
        """
        try:
            if self.feature_means is None or self.feature_stds is None:
                return
            if self.feature_names is None:
                return

            means = self.feature_means
            stds = self.feature_stds

            for row in X:
                for i, (value, mean, std) in enumerate(zip(row, means, stds)):
                    if std == 0 or np.isnan(std) or np.isnan(mean):
                        continue
                    n_stds = abs(value - mean) / std
                    if n_stds > 3.0:
                        feature_name = self.feature_names[i] if i < len(self.feature_names) else f"feature_{i}"
                        logger.warning(
                            f"Feature '{feature_name}' value {value:.3f} is "
                            f"{n_stds:.1f} std devs from training mean"
                        )
        except Exception as e:
            # Never let monitoring errors break prediction
            logger.debug(f"Feature distribution check error (non-fatal): {e}")

    def _log_feature_importance(self, top_n: int = 15):
        """
        Log top N most important features.
        """
        if self.model is None or self.feature_names is None:
            return

        try:
            importance = self.model.feature_importances_
            feature_importance = sorted(
                zip(self.feature_names, importance),
                key=lambda x: x[1],
                reverse=True
            )

            logger.info(f"Top {top_n} most important features:")
            for name, imp in feature_importance[:top_n]:
                logger.info(f"  {name}: {imp:.4f}")

        except Exception as e:
            logger.error(f"Error logging feature importance: {e}", exc_info=True)

    def save(self, filename: str):
        """
        Save trained model to disk.

        Also saves feature distribution statistics (means and standard
        deviations) as a companion JSON file for distribution monitoring.
        """
        try:
            filepath = self.model_dir / filename

            model_data = {
                'model': self.model,
                'calibrated_model': self.calibrated_model,
                'feature_names': self.feature_names,
                'training_stats': self.training_stats,
                'feature_means': self.feature_means,
                'feature_stds': self.feature_stds,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }

            joblib.dump(model_data, filepath)

            # Also save feature stats as a standalone JSON for easy inspection
            if self.feature_means is not None and self.feature_stds is not None:
                stats_path = filepath.with_suffix('.feature_stats.json')
                stats_data = {
                    'feature_names': self.feature_names,
                    'feature_means': self.feature_means.tolist(),
                    'feature_stds': self.feature_stds.tolist(),
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }
                with open(stats_path, 'w') as f:
                    json.dump(stats_data, f, indent=2)
                logger.info(f"Feature distribution stats saved to {stats_path}")

            logger.info(f"✓ Model saved to {filepath}")

        except Exception as e:
            logger.error(f"Error saving model: {e}", exc_info=True)

    def load(self, filename: Optional[str] = None) -> bool:
        """
        Load trained model from disk.

        Args:
            filename: Model file name (if None, loads most recent)

        Returns:
            True if successful
        """
        try:
            if filename is None:
                # Find most recent model file
                model_files = list(self.model_dir.glob('signal_model_*.joblib'))
                if not model_files:
                    logger.warning("No saved models found")
                    return False

                filepath = max(model_files, key=lambda p: p.stat().st_mtime)
            else:
                filepath = self.model_dir / filename

            if not filepath.exists():
                logger.warning(f"Model file not found: {filepath}")
                return False

            # SEC-DATA-03: Validate that the resolved model path is within
            # the expected model directory to prevent path traversal attacks.
            # joblib.load can execute arbitrary code during deserialization,
            # so we must ensure the file originates from a trusted location.
            resolved_path = os.path.realpath(filepath)
            expected_dir = os.path.realpath(self.model_dir)
            if not resolved_path.startswith(expected_dir + os.sep) and resolved_path != expected_dir:
                logger.error(
                    f"SECURITY: Model path '{resolved_path}' is outside expected "
                    f"directory '{expected_dir}'. Refusing to load — possible path traversal."
                )
                return False

            logger.warning(
                f"Loading serialized model from disk: {filepath}. "
                "joblib.load can execute arbitrary code — only load models from trusted sources."
            )
            model_data = joblib.load(filepath)

            self.model = model_data['model']
            self.calibrated_model = model_data.get('calibrated_model')
            self.feature_names = model_data['feature_names']
            self.training_stats = model_data.get('training_stats', {})
            self.trained = True

            # Load feature distribution stats for monitoring (backward-compatible)
            loaded_means = model_data.get('feature_means')
            loaded_stds = model_data.get('feature_stds')
            if loaded_means is not None and loaded_stds is not None:
                self.feature_means = np.asarray(loaded_means)
                self.feature_stds = np.asarray(loaded_stds)
                logger.info("Feature distribution stats loaded for monitoring")
            else:
                self.feature_means = None
                self.feature_stds = None
                logger.info("No feature distribution stats in model file (old model format)")

            # ARCH-ML-12: Warn if model is stale (older than 30 days)
            model_timestamp = model_data.get('timestamp')
            if model_timestamp:
                try:
                    trained_at = datetime.fromisoformat(model_timestamp)
                    age_days = (datetime.now(timezone.utc) - trained_at).days
                    if age_days > 30:
                        logger.warning(
                            f"Model is {age_days} days old (trained {model_timestamp}). "
                            "Consider retraining for current market conditions."
                        )
                    else:
                        logger.info(f"Model age: {age_days} days")
                except (ValueError, TypeError):
                    logger.warning("Could not parse model timestamp for staleness check")

            logger.info(f"✓ Model loaded from {filepath}")

            return True

        except Exception as e:
            logger.error(f"Error loading model: {e}", exc_info=True)
            return False

    def _get_default_prediction(self) -> PredictionResult:
        """
        Return default prediction when model unavailable.
        """
        return {
            'prediction': 0,
            'probability': 0.5,
            'confidence': 0.0,
            'signal': 'neutral',
            'signal_strength': 50.0,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'fallback': True,
        }

    def get_fallback_stats(self) -> Dict[str, int]:
        """Return fallback counts for monitoring."""
        return dict(self.fallback_counter)

    def generate_synthetic_training_data(
        self,
        n_samples: int = 1000,
        win_rate: float = 0.65
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """
        Generate synthetic training data for initial model training.
        
        This creates realistic scenarios based on typical credit spread behavior:
        - High IV + low realized vol = more likely to win
        - Strong trend + good regime = more likely to win
        - Event risk nearby = less likely to win
        
        Args:
            n_samples: Number of synthetic samples to generate
            win_rate: Target overall win rate
            
        Returns:
            Tuple of (features_df, labels)
        """
        from .feature_engine import FeatureEngine

        logger.info(f"Generating {n_samples} synthetic training samples...")

        feature_engine = FeatureEngine()
        feature_names = feature_engine.get_feature_names()

        # Generate random features with realistic distributions
        # Use a local RNG to avoid mutating global numpy random state
        rng = np.random.default_rng(42)

        features_list = []
        labels = []

        for i in range(n_samples):
            # Random base features
            features = {}

            # Technical (mostly neutral with some bias)
            features['rsi_14'] = rng.normal(50, 15)
            features['macd'] = rng.normal(0, 2)
            features['macd_signal'] = rng.normal(0, 2)
            features['macd_histogram'] = features['macd'] - features['macd_signal']
            features['bollinger_pct_b'] = rng.beta(2, 2)
            features['atr_pct'] = rng.gamma(2, 1)
            features['volume_ratio'] = rng.lognormal(0, 0.3)
            features['return_5d'] = rng.normal(0, 2)
            features['return_10d'] = rng.normal(0, 3)
            features['return_20d'] = rng.normal(0, 4)
            features['dist_from_sma20_pct'] = rng.normal(0, 3)
            features['dist_from_sma50_pct'] = rng.normal(0, 5)
            features['dist_from_sma200_pct'] = rng.normal(0, 8)

            # Volatility
            features['realized_vol_10d'] = rng.gamma(4, 4)
            features['realized_vol_20d'] = rng.gamma(4, 4)
            features['realized_vol_60d'] = rng.gamma(4, 4)
            features['iv_rank'] = rng.uniform(0, 100)
            features['iv_percentile'] = rng.uniform(0, 100)
            features['current_iv'] = rng.gamma(4, 5)
            features['rv_iv_spread'] = features['realized_vol_20d'] - features['current_iv']
            features['put_call_skew_ratio'] = rng.lognormal(0, 0.2)
            features['put_skew_steepness'] = rng.normal(0, 3)

            # Market
            features['vix_level'] = rng.gamma(3, 5)
            features['vix_change_1d'] = rng.normal(0, 10)
            features['put_call_ratio'] = rng.lognormal(0, 0.2)
            features['spy_return_5d'] = rng.normal(0, 2)
            features['spy_return_20d'] = rng.normal(0, 4)
            features['spy_realized_vol'] = rng.gamma(3, 5)

            # Event risk
            features['days_to_earnings'] = rng.integers(0, 90)
            features['days_to_fomc'] = rng.integers(0, 60)
            features['days_to_cpi'] = rng.integers(0, 30)
            features['event_risk_score'] = (
                0.8 if min(features['days_to_earnings'], features['days_to_fomc'], features['days_to_cpi']) < 7
                else 0.5 if min(features['days_to_earnings'], features['days_to_fomc'], features['days_to_cpi']) < 14
                else 0.2
            )

            # Seasonal
            features['day_of_week'] = rng.integers(0, 5)
            features['is_opex_week'] = rng.choice([0, 1], p=[0.75, 0.25])
            features['is_monday'] = 1 if features['day_of_week'] == 0 else 0
            features['is_month_end'] = rng.choice([0, 1], p=[0.8, 0.2])

            # Regime
            regime_id = rng.choice([0, 1, 2, 3], p=[0.3, 0.2, 0.4, 0.1])
            features['regime_id'] = regime_id
            features['regime_confidence'] = rng.beta(3, 2)
            features['regime_low_vol_trending'] = 1 if regime_id == 0 else 0
            features['regime_high_vol_trending'] = 1 if regime_id == 1 else 0
            features['regime_mean_reverting'] = 1 if regime_id == 2 else 0
            features['regime_crisis'] = 1 if regime_id == 3 else 0

            # Derived
            features['rsi_oversold'] = 1 if features['rsi_14'] < 30 else 0
            features['rsi_overbought'] = 1 if features['rsi_14'] > 70 else 0
            features['iv_rank_high'] = 1 if features['iv_rank'] > 70 else 0
            features['iv_rank_low'] = 1 if features['iv_rank'] < 30 else 0
            features['vol_premium'] = features['current_iv'] - features['realized_vol_20d']
            features['vol_premium_pct'] = (features['vol_premium'] / features['realized_vol_20d'] * 100
                                          if features['realized_vol_20d'] > 0 else 0)
            features['risk_adjusted_momentum'] = (features['return_20d'] / features['atr_pct']
                                                 if features['atr_pct'] > 0 else 0)

            # Determine label based on feature logic
            win_score = 0

            # High IV rank increases win probability
            if features['iv_rank'] > 70:
                win_score += 30

            # Positive vol premium (IV > RV)
            if features['vol_premium'] > 0:
                win_score += 20

            # Good regime
            if regime_id == 0:  # low_vol_trending
                win_score += 25
            elif regime_id == 3:  # crisis
                win_score -= 40

            # Event risk penalty
            if features['event_risk_score'] > 0.6:
                win_score -= 30

            # Trend strength
            if abs(features['return_20d']) > 5:
                win_score += 15

            # RSI extremes (slight edge for mean reversion)
            if features['rsi_14'] < 30 or features['rsi_14'] > 70:
                win_score += 10

            # Add randomness
            win_score += rng.normal(0, 20)

            # Convert to binary label
            base_threshold = (1 - win_rate) * 100
            label = 1 if win_score > base_threshold else 0

            features_list.append(features)
            labels.append(label)

        # Create DataFrame
        features_df = pd.DataFrame(features_list)
        labels = np.array(labels)

        actual_win_rate = labels.mean()
        logger.info(f"✓ Generated {n_samples} synthetic samples (win_rate={actual_win_rate:.2%})")

        return features_df, labels
