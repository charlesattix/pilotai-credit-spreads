"""
strategies/ml_enhanced_strategy.py — ML V2 Aggressive strategy wrapper.

Wraps any BaseStrategy and applies regime-aware position sizing via
RegimeModelRouter.  Designed to run as a drop-in replacement for
CreditSpreadStrategy inside build_strategy_list().

Sizing behaviour (ML V2 Aggressive profile):
  bull     → max_mult (1.50×) — lean in hard when trend is positive
  neutral  → 1.00×            — normal sizing
  low_vol  → 1.20×            — calm markets, slightly more
  high_vol → min_mult (0.10×) — near-flat, defensive
  bear     → min_mult (0.10×) — near-flat, defensive
  crash    → 0.00×            — no new trades

Signal generation:
  - Delegate to wrapped strategy
  - In crash/fully-defensive: suppress all signals (return [])
  - In bear/high_vol: suppress signals when regime_gate=True (default)
  - Scale signal.score by multiplier so downstream scorers rank them correctly
  - Attach ml_v2_risk_mult + regime metadata for Telegram/logging

Config keys under strategy.ml_enhanced:
  enabled          bool  True
  min_mult         float 0.10
  max_mult         float 1.50
  neutral_mult     float 1.00
  low_vol_mult     float 1.20
  crash_mult       float 0.00
  regime_gate      bool  True  — suppress signals entirely in defensive regimes
  use_signal_model bool  True  — blend pre-trained ML model confidence
  ml_blend_weight  float 0.25
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from strategies.base import BaseStrategy, MarketSnapshot, PortfolioState, Signal, PositionAction

log = logging.getLogger(__name__)


class MLEnhancedStrategy(BaseStrategy):
    """
    ML V2 Aggressive wrapper around any BaseStrategy.

    Applies regime-aware multiplier from RegimeModelRouter to:
      1. Signal score   — scales downstream signal ranking
      2. Contract count — scales size_position() output
      3. Signal gate    — suppresses signals in defensive regimes
    """

    name = "ml_enhanced_v2"

    def __init__(
        self,
        params: Dict[str, Any],
        wrapped: BaseStrategy,
    ) -> None:
        super().__init__(params)
        self._wrapped = wrapped

        # Lazy-import to avoid circular dependency
        from ml.regime_model_router import RegimeModelRouter
        self._router = RegimeModelRouter(params)

        self._regime_gate: bool = bool(params.get("regime_gate", True))
        self._min_score_threshold: float = float(params.get("min_score_threshold", 30.0))

        log.info(
            "MLEnhancedStrategy: wrapping=%s  regime_gate=%s",
            wrapped.name, self._regime_gate,
        )
        log.info("%s", self._router.describe())

    # ─────────────────────────────────────────────────────────────────────────
    # BaseStrategy interface
    # ─────────────────────────────────────────────────────────────────────────

    def generate_signals(
        self, market_data: MarketSnapshot, portfolio_state: Optional[PortfolioState] = None
    ) -> List[Signal]:
        """
        Generate signals from wrapped strategy, filtered and scored by regime.
        """
        regime = market_data.regime

        # Get regime multiplier
        meta = self._router.get_multiplier_with_metadata(regime)
        mult = meta["multiplier"]

        # Hard gate: crash or fully-defensive regimes
        if mult == 0.0:
            log.info(
                "MLEnhancedStrategy: GATE — regime=%s mult=0.0, no signals",
                regime,
            )
            return []

        # Soft gate: suppress in bear/high_vol when regime_gate is active
        if self._regime_gate and meta["is_defensive"]:
            log.info(
                "MLEnhancedStrategy: GATE — regime=%s (defensive), suppressing signals",
                regime,
            )
            return []

        # Delegate to wrapped strategy
        try:
            if portfolio_state is not None:
                raw_signals = self._wrapped.generate_signals(market_data, portfolio_state)
            else:
                raw_signals = self._wrapped.generate_signals(market_data)
        except TypeError:
            # Wrapped strategy may not accept portfolio_state
            raw_signals = self._wrapped.generate_signals(market_data)

        if not raw_signals:
            return []

        # Apply regime multiplier to signals
        enhanced: List[Signal] = []
        for sig in raw_signals:
            # Scale score by multiplier
            scaled_score = sig.score * mult

            # Drop signals that score too low after scaling
            if scaled_score < self._min_score_threshold and mult < 1.0:
                continue

            # Attach ML V2 metadata for audit trail
            new_meta = dict(sig.metadata or {})
            new_meta.update({
                "ml_v2_risk_mult":   mult,
                "ml_v2_regime":      meta["regime"],
                "ml_v2_confidence":  meta.get("ml_confidence"),
                "ml_v2_defensive":   meta["is_defensive"],
            })

            # Build enhanced signal — use dataclass replace pattern
            import dataclasses
            enhanced_sig = dataclasses.replace(
                sig,
                score=round(scaled_score, 1),
                metadata=new_meta,
                strategy_name=self.name,
            )
            enhanced.append(enhanced_sig)

        log.debug(
            "MLEnhancedStrategy: regime=%s mult=%.2f raw=%d enhanced=%d",
            regime, mult, len(raw_signals), len(enhanced),
        )
        return enhanced

    def manage_position(
        self, position: Any, market_data: MarketSnapshot
    ) -> PositionAction:
        """Delegate position management to wrapped strategy."""
        return self._wrapped.manage_position(position, market_data)

    def size_position(
        self,
        signal: Signal,
        market_data: MarketSnapshot,
        portfolio_state: PortfolioState,
    ) -> int:
        """Apply regime multiplier to base strategy's contract count."""
        base_size = self._wrapped.size_position(signal, market_data, portfolio_state)
        mult = self._router.get_multiplier(market_data.regime)
        sized = max(1, int(round(base_size * mult)))
        log.debug(
            "MLEnhancedStrategy.size_position: base=%d mult=%.2f → %d",
            base_size, mult, sized,
        )
        return sized

    def get_param_space(self) -> List:
        """Expose wrapped strategy's param space plus ML params."""
        from strategies.base import ParamDef
        ml_params = [
            ParamDef("min_mult",       "float", 0.10, low=0.0,  high=0.5,  step=0.05),
            ParamDef("max_mult",       "float", 1.50, low=1.0,  high=2.0,  step=0.25),
            ParamDef("neutral_mult",   "float", 1.00, low=0.5,  high=1.5,  step=0.25),
            ParamDef("low_vol_mult",   "float", 1.20, low=0.8,  high=1.8,  step=0.20),
        ]
        return self._wrapped.get_param_space() + ml_params
