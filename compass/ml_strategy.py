"""
MLEnhancedStrategy — ML confidence-gated strategy wrapper.

Wraps any BaseStrategy subclass and gates signal generation through
the COMPASS SignalModel. Signals with ML confidence below the
configured threshold are dropped before reaching the portfolio engine.

Position management is delegated unchanged to the base strategy.
"""

import logging
from typing import Any, Dict, List, Optional

from strategies.base import (
    BaseStrategy,
    MarketSnapshot,
    ParamDef,
    PortfolioState,
    Position,
    PositionAction,
    Signal,
)
from compass.signal_model import SignalModel
from compass.features import FeatureEngine

logger = logging.getLogger(__name__)

# Default confidence threshold — trades with ML confidence below this
# are skipped.  Calibrated models produce probabilities in [0, 1];
# confidence = 2 * |probability - 0.5|, so a threshold of 0.30
# corresponds to probability outside [0.35, 0.65].
DEFAULT_CONFIDENCE_THRESHOLD = 0.30


class MLEnhancedStrategy(BaseStrategy):
    """Wraps a BaseStrategy with ML confidence gating.

    Usage::

        base = CreditSpreadStrategy(params)
        ml_strategy = MLEnhancedStrategy(
            base_strategy=base,
            signal_model=signal_model,
            feature_engine=feature_engine,
            ml_config={'confidence_threshold': 0.30},
        )
        signals = ml_strategy.generate_signals(market_data)

    Any signal whose ML confidence falls below ``confidence_threshold``
    is silently dropped. Surviving signals get ML metadata attached
    (probability, confidence, prediction) for downstream logging.
    """

    def __init__(
        self,
        base_strategy: BaseStrategy,
        signal_model: SignalModel,
        feature_engine: Optional[FeatureEngine] = None,
        ml_config: Optional[Dict[str, Any]] = None,
    ):
        ml_config = ml_config or {}
        # Pass base strategy params to BaseStrategy.__init__
        super().__init__(base_strategy.params)

        self.base = base_strategy
        self.signal_model = signal_model
        self.feature_engine = feature_engine
        self.confidence_threshold = ml_config.get(
            'confidence_threshold', DEFAULT_CONFIDENCE_THRESHOLD
        )
        # Override name to include ML prefix for identification
        self._name = f"ML_{base_strategy.name}"

        # Counters for monitoring
        self._total_signals = 0
        self._passed_signals = 0
        self._filtered_signals = 0
        self._feature_miss_signals = 0

        logger.info(
            "MLEnhancedStrategy wrapping %s "
            "(threshold=%.2f, feature_engine=%s)",
            base_strategy.name,
            self.confidence_threshold,
            feature_engine is not None,
        )

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def generate_signals(
        self, market_data: MarketSnapshot
    ) -> List[Signal]:
        """Generate signals from base strategy, then filter by ML confidence.

        For each base signal:
        1. Build features via FeatureEngine (if available)
        2. Call SignalModel.predict()
        3. If confidence >= threshold → keep (attach ML metadata)
        4. If confidence < threshold → drop
        5. If features unavailable → drop (cache miss = skip trade)
        """
        base_signals = self.base.generate_signals(market_data)
        if not base_signals:
            return []

        kept: List[Signal] = []

        for signal in base_signals:
            self._total_signals += 1

            # --- Build features ---
            features = self._build_features_for_signal(signal, market_data)
            if features is None:
                self._feature_miss_signals += 1
                logger.debug(
                    "ML gate: skipping %s %s — feature build returned None",
                    signal.ticker,
                    signal.metadata.get('spread_type', ''),
                )
                continue

            # --- ML prediction ---
            prediction = self.signal_model.predict(features)

            confidence = prediction.get('confidence', 0.0)
            probability = prediction.get('probability', 0.5)
            is_fallback = prediction.get('fallback', False)

            # If the model returned a fallback (not trained), let the
            # signal through — don't block on an untrained model.
            if is_fallback:
                signal.metadata['ml_prediction'] = prediction
                signal.metadata['ml_gated'] = False
                kept.append(signal)
                self._passed_signals += 1
                continue

            # --- Confidence gate ---
            if confidence >= self.confidence_threshold:
                signal.metadata['ml_prediction'] = prediction
                signal.metadata['ml_gated'] = True
                signal.metadata['ml_confidence'] = confidence
                signal.metadata['ml_probability'] = probability
                kept.append(signal)
                self._passed_signals += 1
                logger.debug(
                    "ML gate: PASS %s %s — confidence=%.3f probability=%.3f",
                    signal.ticker,
                    signal.metadata.get('spread_type', ''),
                    confidence,
                    probability,
                )
            else:
                self._filtered_signals += 1
                logger.debug(
                    "ML gate: SKIP %s %s — confidence=%.3f < threshold=%.2f",
                    signal.ticker,
                    signal.metadata.get('spread_type', ''),
                    confidence,
                    self.confidence_threshold,
                )

        if base_signals:
            logger.info(
                "ML gate: %d/%d signals passed (threshold=%.2f)",
                len(kept),
                len(base_signals),
                self.confidence_threshold,
            )

        return kept

    def manage_position(
        self, position: Position, market_data: MarketSnapshot
    ) -> PositionAction:
        """Delegate position management to base strategy unchanged."""
        return self.base.manage_position(position, market_data)

    def size_position(
        self, signal: Signal, portfolio_state: PortfolioState
    ) -> int:
        """Delegate sizing to base strategy.

        ML confidence is already embedded in signal.metadata for
        downstream consumers (e.g. COMPASS PositionSizer) but the
        base strategy's sizing logic is the source of truth.
        """
        return self.base.size_position(signal, portfolio_state)

    @classmethod
    def get_param_space(cls) -> List[ParamDef]:
        """Return ML-specific params.

        Base strategy params are accessed via self.base.get_param_space()
        at runtime.  This classmethod returns only the ML gate params.
        """
        return [
            ParamDef(
                name='ml_confidence_threshold',
                param_type='float',
                default=DEFAULT_CONFIDENCE_THRESHOLD,
                low=0.0,
                high=0.90,
                step=0.05,
                description='Minimum ML confidence to accept a trade signal',
            ),
        ]

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    def get_ml_stats(self) -> Dict[str, Any]:
        """Return ML gating statistics."""
        return {
            'total_signals': self._total_signals,
            'passed_signals': self._passed_signals,
            'filtered_signals': self._filtered_signals,
            'feature_miss_signals': self._feature_miss_signals,
            'pass_rate': (
                self._passed_signals / self._total_signals
                if self._total_signals > 0
                else 0.0
            ),
            'confidence_threshold': self.confidence_threshold,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_features_for_signal(
        self,
        signal: Signal,
        market_data: MarketSnapshot,
    ) -> Optional[Dict]:
        """Build feature dict for a signal.

        Returns None if FeatureEngine is not configured or data is
        unavailable (cache miss).
        """
        if self.feature_engine is None:
            # No feature engine → build a minimal feature dict from
            # what's available in MarketSnapshot + Signal metadata.
            return self._minimal_features(signal, market_data)

        ticker = signal.ticker
        price = market_data.prices.get(ticker)
        if price is None:
            return None

        # FeatureEngine.build_features returns None on cache miss.
        # We pass an empty DataFrame for options_chain — the engine
        # only uses it for credit_to_width_ratio which we can override
        # from Signal metadata.
        import pandas as pd

        features = self.feature_engine.build_features(
            ticker=ticker,
            current_price=price,
            options_chain=pd.DataFrame(),
            regime_data={'regime': market_data.regime} if market_data.regime else None,
        )

        if features is None:
            return None

        # Enrich with signal-level info
        if signal.max_loss > 0 and signal.net_credit > 0:
            width = signal.max_loss + signal.net_credit
            features['credit_to_width_ratio'] = signal.net_credit / width if width > 0 else 0.0

        return features

    @staticmethod
    def _minimal_features(
        signal: Signal,
        market_data: MarketSnapshot,
    ) -> Dict:
        """Build a minimal feature dict from MarketSnapshot fields.

        Used when no FeatureEngine is available.  The signal model will
        fill missing features with 0.0, but we provide what we can.
        """
        ticker = signal.ticker
        features: Dict[str, float] = {}

        # VIX
        features['vix_level'] = market_data.vix

        # IV rank / RSI from snapshot
        features['iv_rank'] = market_data.iv_rank.get(ticker, 50.0)
        features['rsi_14'] = market_data.rsi.get(ticker, 50.0)
        features['current_iv'] = market_data.realized_vol.get(ticker, 20.0)

        # Credit-to-width from signal
        if signal.max_loss > 0 and signal.net_credit > 0:
            width = signal.max_loss + signal.net_credit
            features['credit_to_width_ratio'] = signal.net_credit / width if width > 0 else 0.0

        return features
