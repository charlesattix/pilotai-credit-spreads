"""
ML Pipeline - Main Orchestrator

Combines all ML modules into a unified pipeline for credit spread analysis.

This module:
1. Detects market regime
2. Analyzes IV surface
3. Builds comprehensive features
4. Predicts trade profitability
5. Calculates optimal position size
6. Scans for event risk
"""

import numpy as np
import pandas as pd
from collections import Counter
from typing import Dict, Optional
from datetime import datetime
import logging

from .regime_detector import RegimeDetector
from .iv_analyzer import IVAnalyzer
from .feature_engine import FeatureEngine
from .signal_model import SignalModel
from .position_sizer import PositionSizer
from .sentiment_scanner import SentimentScanner
from shared.types import TradeAnalysis

logger = logging.getLogger(__name__)


class MLPipeline:
    """
    Main ML pipeline for credit spread trading.
    
    Orchestrates all ML components to provide enhanced trade analysis.
    """
    
    def __init__(self, config: Optional[Dict] = None, data_cache=None):
        """
        Initialize ML pipeline.

        Args:
            config: Configuration dictionary
            data_cache: Optional DataCache instance for shared data retrieval.
        """
        self.config = config or {}

        # Initialize components
        logger.info("Initializing ML pipeline...")

        self.regime_detector = RegimeDetector(
            lookback_days=self.config.get('regime_lookback_days', 252),
            data_cache=data_cache,
        )

        self.iv_analyzer = IVAnalyzer(
            lookback_days=self.config.get('iv_lookback_days', 252),
            data_cache=data_cache,
        )

        self.feature_engine = FeatureEngine(data_cache=data_cache)
        
        self.signal_model = SignalModel(
            model_dir=self.config.get('model_dir', 'ml/models')
        )
        
        self.position_sizer = PositionSizer(
            max_position_size=self.config.get('max_position_size', 0.10),
            kelly_fraction=self.config.get('kelly_fraction', 0.25),
            max_portfolio_risk=self.config.get('max_portfolio_risk', 0.20),
        )
        
        self.sentiment_scanner = SentimentScanner(data_cache=data_cache)
        
        self.initialized = False
        self.fallback_counter: Counter = Counter()

        logger.info("✓ ML pipeline initialized")
    
    def initialize(self, force_retrain: bool = False) -> bool:
        """
        Initialize all ML models (train if needed).
        
        Args:
            force_retrain: Force model retraining
            
        Returns:
            True if successful
        """
        try:
            logger.info("Initializing ML models...")
            
            # 1. Train regime detector
            if not self.regime_detector.trained or force_retrain:
                logger.info("Training regime detector...")
                if not self.regime_detector.fit(force_retrain=force_retrain):
                    logger.warning("Regime detector training failed, continuing with fallback")
            
            # 2. Load or train signal model
            if not self.signal_model.trained:
                logger.info("Loading signal model...")
                if not self.signal_model.load():
                    logger.info("No saved model found, training on synthetic data...")
                    features_df, labels = self.signal_model.generate_synthetic_training_data(
                        n_samples=2000, win_rate=0.65
                    )
                    self.signal_model.train(features_df, labels)
            
            self.initialized = True
            logger.info("✓ ML pipeline ready")
            
            return True
            
        except Exception as e:
            logger.error(f"Error initializing ML pipeline: {e}", exc_info=True)
            return False
    
    def analyze_trade(
        self,
        ticker: str,
        current_price: float,
        options_chain: pd.DataFrame,
        spread_type: str,
        expiration_date: Optional[datetime] = None,
        technical_signals: Optional[Dict] = None,
        current_positions: Optional[list] = None,
    ) -> TradeAnalysis:
        """
        Comprehensive ML-enhanced trade analysis.
        
        Args:
            ticker: Stock ticker
            current_price: Current stock price
            options_chain: Options chain data
            spread_type: 'bull_put' or 'bear_call'
            expiration_date: Option expiration date
            technical_signals: Technical analysis signals (optional)
            current_positions: Current portfolio positions (optional)
            
        Returns:
            Dictionary with enhanced trade analysis
        """
        if not self.initialized:
            logger.warning("Pipeline not initialized, initializing now...")
            self.initialize()
        
        try:
            logger.info(f"Analyzing {spread_type} spread for {ticker}...")
            
            result = {
                'ticker': ticker,
                'spread_type': spread_type,
                'timestamp': datetime.now().isoformat(),
            }
            
            # 1. Detect market regime
            regime_data = self.regime_detector.detect_regime(ticker='SPY')
            result['regime'] = regime_data
            
            # 2. Analyze IV surface
            iv_analysis = self.iv_analyzer.analyze_surface(
                ticker, options_chain, current_price
            )
            result['iv_analysis'] = iv_analysis
            
            # 3. Build features
            features = self.feature_engine.build_features(
                ticker=ticker,
                current_price=current_price,
                options_chain=options_chain,
                regime_data=regime_data,
                iv_analysis=iv_analysis,
                technical_signals=technical_signals,
            )
            result['features'] = features
            
            # 4. ML prediction
            ml_prediction = self.signal_model.predict(features)
            result['ml_prediction'] = ml_prediction
            
            # 5. Event risk scan
            event_scan = self.sentiment_scanner.scan(
                ticker=ticker,
                expiration_date=expiration_date,
                lookback_days=45,
            )
            result['event_risk'] = event_scan
            
            # 6. Position sizing
            # Estimate expected return/loss for credit spread
            expected_return = 0.30  # 30% return on risk (typical for credit spreads)
            expected_loss = -1.0    # 100% loss (max loss = width - premium)
            
            position_sizing = self.position_sizer.calculate_position_size(
                win_probability=ml_prediction['probability'],
                expected_return=expected_return,
                expected_loss=expected_loss,
                ml_confidence=ml_prediction['confidence'],
                current_positions=current_positions,
                ticker=ticker,
            )
            
            # Adjust for event risk
            adjusted_size = self.sentiment_scanner.adjust_position_for_events(
                base_position_size=position_sizing['recommended_size'],
                event_risk_score=event_scan['event_risk_score'],
            )
            
            position_sizing['event_adjusted_size'] = adjusted_size
            result['position_sizing'] = position_sizing
            
            # 7. Generate enhanced score
            enhanced_score = self._calculate_enhanced_score(result)
            result['enhanced_score'] = enhanced_score
            
            # 8. Overall recommendation
            recommendation = self._generate_recommendation(result)
            result['recommendation'] = recommendation
            
            logger.info(
                f"{ticker} analysis complete: "
                f"ML_prob={ml_prediction['probability']:.2%}, "
                f"Score={enhanced_score:.1f}, "
                f"Rec={recommendation['action']}"
            )
            
            return result
            
        except Exception as e:
            self.fallback_counter['analyze_trade'] += 1
            count = self.fallback_counter['analyze_trade']
            logger.error(f"Error analyzing trade for {ticker} (fallback #{count}): {e}", exc_info=True)
            if count >= 10:
                logger.critical(f"ML pipeline analyze_trade has fallen back {count} times — investigate")
            return self._get_default_analysis(ticker, spread_type)
    
    def _calculate_enhanced_score(self, analysis: Dict) -> float:
        """
        Calculate enhanced trade score (0-100).
        
        Combines:
        - ML probability
        - Regime favorability
        - IV analysis signals
        - Event risk
        - Technical confirmation
        """
        try:
            score = 50.0  # Base score
            
            # 1. ML prediction (0-40 points)
            ml_prob = analysis['ml_prediction']['probability']
            ml_confidence = analysis['ml_prediction']['confidence']
            
            # Convert probability to score contribution
            prob_contribution = (ml_prob - 0.5) * 2 * 40  # -40 to +40
            score += prob_contribution * ml_confidence  # Weight by confidence
            
            # 2. Regime (0-15 points)
            regime = analysis['regime']['regime']
            if regime == 'low_vol_trending':
                score += 15
            elif regime == 'high_vol_trending':
                score += 8
            elif regime == 'mean_reverting':
                score += 5
            elif regime == 'crisis':
                score -= 20
            
            # 3. IV analysis (0-15 points)
            iv_signals = analysis['iv_analysis']['signals']
            
            spread_type = analysis['spread_type']
            if spread_type == 'bull_put' and iv_signals.get('bull_put_favorable'):
                score += 15
            elif spread_type == 'bear_call' and iv_signals.get('bear_call_favorable'):
                score += 15
            elif iv_signals['overall_signal'] == 'favorable_both':
                score += 10
            
            # 4. Event risk (-30 to 0 points)
            event_risk_score = analysis['event_risk']['event_risk_score']
            score -= event_risk_score * 30
            
            # 5. Feature-based adjustments
            features = analysis['features']
            
            # High IV rank is favorable
            if features.get('iv_rank', 50) > 70:
                score += 5
            
            # Positive vol premium
            if features.get('vol_premium', 0) > 0:
                score += 5
            
            # Ensure score is in 0-100 range
            score = max(0, min(100, score))
            
            return round(score, 1)
            
        except Exception as e:
            logger.error(f"Error calculating enhanced score: {e}", exc_info=True)
            return 50.0
    
    def _generate_recommendation(self, analysis: Dict) -> Dict:
        """
        Generate overall trading recommendation.
        """
        try:
            score = analysis['enhanced_score']
            ml_prob = analysis['ml_prediction']['probability']
            event_rec = analysis['event_risk']['recommendation']
            position_size = analysis['position_sizing']['event_adjusted_size']
            
            # Determine action
            if score >= 75 and event_rec in ['proceed', 'proceed_reduced']:
                action = 'strong_buy'
                confidence = 'high'
            elif score >= 60 and event_rec != 'avoid':
                action = 'buy'
                confidence = 'medium'
            elif score >= 50 and event_rec == 'proceed':
                action = 'consider'
                confidence = 'low'
            else:
                action = 'pass'
                confidence = 'low'
            
            # Build reasoning
            reasoning = []
            
            if ml_prob > 0.60:
                reasoning.append(f"ML model predicts {ml_prob:.1%} win probability")
            
            regime = analysis['regime']['regime']
            reasoning.append(f"Market regime: {regime}")
            
            if analysis['event_risk']['events']:
                events_str = ', '.join([e['event_type'] for e in analysis['event_risk']['events']])
                reasoning.append(f"Event risk: {events_str}")
            
            if position_size < analysis['position_sizing']['recommended_size']:
                reasoning.append("Position size reduced due to event risk")
            
            recommendation = {
                'action': action,
                'confidence': confidence,
                'score': score,
                'position_size': position_size,
                'reasoning': reasoning,
                'ml_probability': ml_prob,
            }
            
            return recommendation
            
        except Exception as e:
            logger.error(f"Error generating recommendation: {e}", exc_info=True)
            return {
                'action': 'pass',
                'confidence': 'low',
                'score': 50.0,
                'position_size': 0.0,
                'reasoning': ['Error in analysis'],
                'ml_probability': 0.5,
            }
    
    def batch_analyze(
        self,
        opportunities: list,
        current_positions: Optional[list] = None
    ) -> list:
        """
        Analyze multiple opportunities in batch.
        
        Args:
            opportunities: List of opportunity dictionaries
            current_positions: Current portfolio positions
            
        Returns:
            List of enhanced opportunity dictionaries
        """
        try:
            logger.info(f"Batch analyzing {len(opportunities)} opportunities...")
            
            enhanced_opportunities = []
            
            for opp in opportunities:
                try:
                    # Extract opportunity parameters
                    ticker = opp.get('ticker', '')
                    current_price = opp.get('current_price', 0)
                    options_chain = opp.get('options_chain', pd.DataFrame())
                    spread_type = opp.get('type', 'bull_put')
                    expiration_date = opp.get('expiration')
                    technical_signals = opp.get('technical_signals', {})
                    
                    # Analyze
                    analysis = self.analyze_trade(
                        ticker=ticker,
                        current_price=current_price,
                        options_chain=options_chain,
                        spread_type=spread_type,
                        expiration_date=expiration_date,
                        technical_signals=technical_signals,
                        current_positions=current_positions,
                    )
                    
                    # Merge with original opportunity
                    enhanced_opp = {**opp, **analysis}
                    enhanced_opportunities.append(enhanced_opp)
                    
                except Exception as e:
                    logger.error(f"Error analyzing opportunity {opp.get('ticker', '')}: {e}", exc_info=True)
                    enhanced_opportunities.append(opp)
            
            # Sort by enhanced score
            enhanced_opportunities.sort(
                key=lambda x: x.get('enhanced_score', 0),
                reverse=True
            )
            
            logger.info("✓ Batch analysis complete")
            
            return enhanced_opportunities
            
        except Exception as e:
            logger.error(f"Error in batch analysis: {e}", exc_info=True)
            return opportunities
    
    def get_pipeline_status(self) -> Dict:
        """
        Get status of all pipeline components.
        """
        return {
            'initialized': self.initialized,
            'regime_detector_trained': self.regime_detector.trained,
            'signal_model_trained': self.signal_model.trained,
            'regime_detector_last_train': str(self.regime_detector.last_train_date)
                if self.regime_detector.last_train_date else None,
            'signal_model_stats': self.signal_model.training_stats,
        }
    
    def retrain_models(self) -> Dict:
        """
        Retrain all ML models.
        
        Returns:
            Dictionary with retraining results
        """
        logger.info("Retraining ML models...")
        
        results = {}
        
        # Retrain regime detector
        regime_success = self.regime_detector.fit(force_retrain=True)
        results['regime_detector'] = 'success' if regime_success else 'failed'
        
        # Retrain signal model on synthetic data
        try:
            features_df, labels = self.signal_model.generate_synthetic_training_data(
                n_samples=2000, win_rate=0.65
            )
            train_stats = self.signal_model.train(features_df, labels)
            results['signal_model'] = 'success' if train_stats else 'failed'
            results['signal_model_stats'] = train_stats
        except Exception as e:
            logger.error(f"Error retraining signal model: {e}", exc_info=True)
            results['signal_model'] = 'failed'
        
        logger.info("✓ Model retraining complete")
        
        return results
    
    def _get_default_analysis(self, ticker: str, spread_type: str) -> TradeAnalysis:
        """
        Return default analysis when error occurs.
        """
        return {
            'ticker': ticker,
            'spread_type': spread_type,
            'timestamp': datetime.now().isoformat(),
            'enhanced_score': 50.0,
            'recommendation': {
                'action': 'pass',
                'confidence': 'low',
                'score': 50.0,
                'position_size': 0.0,
                'reasoning': ['Error in analysis - using fallback'],
                'ml_probability': 0.5,
            },
            'error': True,
        }

    def get_fallback_stats(self) -> Dict[str, int]:
        """Return fallback counts for monitoring."""
        return dict(self.fallback_counter)
    
    def get_summary_report(self, analysis: Dict) -> str:
        """
        Generate human-readable summary report.
        
        Args:
            analysis: Result from analyze_trade()
            
        Returns:
            Formatted report string
        """
        ticker = analysis['ticker']
        spread_type = analysis['spread_type']
        score = analysis['enhanced_score']
        rec = analysis['recommendation']
        
        report = f"\n{'='*60}\n"
        report += f"ML-Enhanced Trade Analysis: {ticker} {spread_type.upper()}\n"
        report += f"{'='*60}\n\n"
        
        # Recommendation
        report += f"RECOMMENDATION: {rec['action'].upper()} (Confidence: {rec['confidence']})\n"
        report += f"Enhanced Score: {score:.1f}/100\n"
        report += f"Position Size: {rec['position_size']:.2%}\n\n"
        
        # ML Prediction
        ml = analysis['ml_prediction']
        report += f"ML Prediction:\n"
        report += f"  Win Probability: {ml['probability']:.1%}\n"
        report += f"  Confidence: {ml['confidence']:.2f}\n"
        report += f"  Signal: {ml['signal']}\n\n"
        
        # Regime
        regime = analysis['regime']
        report += f"Market Regime: {regime['regime']} ({regime['confidence']:.1%} confidence)\n\n"
        
        # Event Risk
        event_risk = analysis['event_risk']
        if event_risk['events']:
            report += f"Event Risk: {event_risk['event_risk_score']:.2f}\n"
            for event in event_risk['events']:
                report += f"  - {event['description']}\n"
        else:
            report += "Event Risk: None detected\n"
        
        report += "\n"
        
        # Reasoning
        report += "Key Factors:\n"
        for reason in rec['reasoning']:
            report += f"  • {reason}\n"
        
        report += f"\n{'='*60}\n"
        
        return report
