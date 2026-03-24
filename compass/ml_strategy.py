"""
MLEnhancedStrategy — ML confidence-gated strategy wrapper.

Wraps any BaseStrategy subclass and gates signal generation through
the COMPASS SignalModel (or EnsembleSignalModel when ``ensemble_mode``
is enabled in the ml_config).  Signals with ML confidence below the
configured threshold are dropped before reaching the portfolio engine.

V2 adds confidence-based sizing: instead of binary gating, ML confidence
modulates position size. Low-confidence signals get smaller positions
instead of being killed entirely.

Position management is delegated unchanged to the base strategy.

Model selection
~~~~~~~~~~~~~~~
The ``ensemble_mode`` config flag controls which model class is used:

* ``ensemble_mode: false`` (default) → ``SignalModel`` (single XGBoost)
* ``ensemble_mode: true``           → ``EnsembleSignalModel`` (XGB+RF+ET)

Both classes expose the same public API (``predict``, ``predict_batch``,
``load``, ``save``, ``trained``, ``feature_names``), so the rest of the
pipeline is unaffected.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Union

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

# Type alias — both model classes satisfy the same interface.
AnySignalModel = Union[SignalModel, "EnsembleSignalModel"]

# Lazy import guard so the module loads even if ensemble deps are missing.
_EnsembleSignalModel = None


def _get_ensemble_class():
    """Lazy-import EnsembleSignalModel to avoid circular / heavy imports."""
    global _EnsembleSignalModel
    if _EnsembleSignalModel is None:
        from compass.ensemble_signal_model import EnsembleSignalModel
        _EnsembleSignalModel = EnsembleSignalModel
    return _EnsembleSignalModel


def load_signal_model(
    model_dir: str = "ml/models",
    ensemble_mode: bool = False,
    filename: Optional[str] = None,
) -> Optional[AnySignalModel]:
    """Factory: instantiate and load the appropriate signal model.

    Args:
        model_dir: Directory containing ``.joblib`` model files.
        ensemble_mode: If True, load :class:`EnsembleSignalModel`; otherwise
            load the default single-XGBoost :class:`SignalModel`.
        filename: Explicit model file name.  When ``None``, the most recent
            file matching the model class's glob pattern is loaded.

    Returns:
        A loaded model instance, or ``None`` if loading fails.
    """
    if ensemble_mode:
        cls = _get_ensemble_class()
        model = cls(model_dir=model_dir)
        logger.info("Ensemble mode enabled — loading EnsembleSignalModel")
    else:
        model = SignalModel(model_dir=model_dir)
        logger.info("Default mode — loading SignalModel (XGBoost)")

    if model.load(filename):
        return model

    logger.error(
        "Failed to load %s from %s (filename=%s)",
        type(model).__name__, model_dir, filename,
    )
    return None

# Default confidence threshold — trades with ML confidence below this
# are skipped.  Calibrated models produce probabilities in [0, 1];
# confidence = 2 * |probability - 0.5|, so a threshold of 0.30
# corresponds to probability outside [0.35, 0.65].
DEFAULT_CONFIDENCE_THRESHOLD = 0.30


def confidence_to_size_multiplier(
    confidence: float,
    min_mult: float = 0.25,
    max_mult: float = 1.25,
) -> float:
    """Map ML confidence [0,1] to position size multiplier via linear interpolation.

    Formula: min_mult + (max_mult - min_mult) * clamp(confidence, 0, 1)

    Always returns at least min_mult (default 0.25), NEVER returns 0.
    """
    clamped = max(0.0, min(1.0, confidence))
    return min_mult + (max_mult - min_mult) * clamped


class RegimeModelRouter:
    """Routes predictions to regime-specific ML models.

    Falls back to the default model if a regime-specific model
    is unavailable or fails to load.

    Supports a virtual "defensive" regime that merges bear and high_vol:
    when regime is "bear" or "high_vol" and a "defensive" model is loaded,
    the defensive model is used as a shared fallback for both.
    """

    # Regimes that map to the "defensive" virtual regime
    DEFENSIVE_REGIMES = frozenset({"bear", "high_vol"})

    def __init__(
        self,
        default_model: AnySignalModel,
        regime_model_paths: Optional[Dict[str, str]] = None,
        ensemble_mode: bool = False,
    ):
        self.default_model = default_model
        self.regime_models: Dict[str, AnySignalModel] = {}
        if regime_model_paths:
            for regime, path in regime_model_paths.items():
                model = load_signal_model(
                    model_dir=os.path.dirname(path),
                    ensemble_mode=ensemble_mode,
                    filename=os.path.basename(path),
                )
                if model is not None:
                    self.regime_models[regime] = model
                    logger.info("Loaded regime model for %s from %s", regime, path)
                else:
                    logger.warning("Failed to load regime model for %s from %s", regime, path)

    def predict(self, features: Dict, regime: Optional[str] = None) -> Dict:
        """Predict using regime-specific model if available, else default.

        Lookup order for bear/high_vol regimes:
          1. Exact regime model (e.g. "bear")
          2. "defensive" model (shared bear+high_vol)
          3. Default model
        """
        if regime and regime in self.regime_models:
            return self.regime_models[regime].predict(features)
        # Defensive fallback for bear / high_vol
        if regime in self.DEFENSIVE_REGIMES and "defensive" in self.regime_models:
            return self.regime_models["defensive"].predict(features)
        return self.default_model.predict(features)


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
        signal_model: AnySignalModel,
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

        # Ensemble mode flag — propagated to regime model router so it
        # loads the same model class for regime-specific models.
        self.ensemble_mode = ml_config.get('ensemble_mode', False)

        # V2: confidence sizing mode (kill switch — False = V1 binary gating)
        self.ml_sizing_enabled = ml_config.get('ml_sizing', False)

        # V2: regime model router (only instantiated when ml_sizing=True)
        if self.ml_sizing_enabled:
            regime_model_paths = ml_config.get('regime_model_paths')
            self.regime_router = RegimeModelRouter(
                default_model=signal_model,
                regime_model_paths=regime_model_paths,
                ensemble_mode=self.ensemble_mode,
            )
        else:
            self.regime_router = None

        # Counters for monitoring
        self._total_signals = 0
        self._passed_signals = 0
        self._filtered_signals = 0
        self._feature_miss_signals = 0

        model_label = type(signal_model).__name__
        logger.info(
            "MLEnhancedStrategy wrapping %s "
            "(model=%s, threshold=%.2f, ml_sizing=%s, feature_engine=%s)",
            base_strategy.name,
            model_label,
            self.confidence_threshold,
            self.ml_sizing_enabled,
            feature_engine is not None,
        )

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def generate_signals(
        self, market_data: MarketSnapshot
    ) -> List[Signal]:
        """Generate signals from base strategy, then filter/size by ML confidence.

        V1 (ml_sizing=False): Binary gating — drop signals below threshold.
        V2 (ml_sizing=True): Confidence sizing — never drop, attach size multiplier.
        """
        base_signals = self.base.generate_signals(market_data)
        if not base_signals:
            return []

        kept: List[Signal] = []

        if self.ml_sizing_enabled:
            # V2: confidence sizing — never drop, always attach multiplier
            for signal in base_signals:
                self._total_signals += 1

                features = self._build_features_for_signal(signal, market_data)
                if features is None:
                    # Feature miss → minimum sizing (25%), don't drop
                    self._feature_miss_signals += 1
                    signal.metadata['ml_size_multiplier'] = 0.25
                    signal.metadata['ml_confidence'] = 0.0
                    signal.metadata['ml_gated'] = False
                    kept.append(signal)
                    self._passed_signals += 1
                    logger.debug(
                        "ML V2: feature miss %s %s — multiplier=0.25",
                        signal.ticker,
                        signal.metadata.get('spread_type', ''),
                    )
                    continue

                regime = market_data.regime
                prediction = self.regime_router.predict(features, regime=regime)
                confidence = prediction.get('confidence', 0.0)

                multiplier = confidence_to_size_multiplier(confidence)
                signal.metadata['ml_size_multiplier'] = multiplier
                signal.metadata['ml_confidence'] = confidence
                signal.metadata['ml_prediction'] = prediction
                signal.metadata['ml_gated'] = True
                kept.append(signal)
                self._passed_signals += 1
                logger.debug(
                    "ML V2: PASS %s %s — confidence=%.3f multiplier=%.2f",
                    signal.ticker,
                    signal.metadata.get('spread_type', ''),
                    confidence,
                    multiplier,
                )

            if base_signals:
                logger.info(
                    "ML V2: %d/%d signals sized (all kept)",
                    len(kept),
                    len(base_signals),
                )
        else:
            # V1: existing binary gating (unchanged)
            for signal in base_signals:
                self._total_signals += 1

                features = self._build_features_for_signal(signal, market_data)
                if features is None:
                    self._feature_miss_signals += 1
                    logger.debug(
                        "ML gate: skipping %s %s — feature build returned None",
                        signal.ticker,
                        signal.metadata.get('spread_type', ''),
                    )
                    continue

                prediction = self.signal_model.predict(features)

                confidence = prediction.get('confidence', 0.0)
                probability = prediction.get('probability', 0.5)
                is_fallback = prediction.get('fallback', False)

                if is_fallback:
                    signal.metadata['ml_prediction'] = prediction
                    signal.metadata['ml_gated'] = False
                    kept.append(signal)
                    self._passed_signals += 1
                    continue

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
        """Size position, applying ML confidence multiplier in V2 mode.

        V1: Delegates entirely to base strategy.
        V2: Scales base contracts by ml_size_multiplier (min 1 contract).
        """
        base_contracts = self.base.size_position(signal, portfolio_state)
        if self.ml_sizing_enabled and base_contracts > 0:
            multiplier = signal.metadata.get('ml_size_multiplier', 1.0)
            return max(1, int(round(base_contracts * multiplier)))
        return base_contracts

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
