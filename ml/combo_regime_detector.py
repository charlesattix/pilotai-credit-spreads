"""Unified regime detector combining multiple signal sources with safety overrides.

Voting rules:
    - BULL requires ALL 3 signals to agree (unanimous).
    - BEAR requires ALL 3 signals to agree (unanimous 3/3).
    - 2/3 bearish → NEUTRAL (not enough conviction for BEAR).
    - Everything else → NEUTRAL.

Safety overrides (applied in priority order):
    1. VIX circuit breaker: VIX > 40 → forced BEAR (bypasses hysteresis).
    2. MA200 abstain zone: price within ±2% of MA200 → forced NEUTRAL.
    3. Hysteresis: prevents regime changes within the cooldown window.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Regime constants
# ---------------------------------------------------------------------------
BULL = "BULL"
NEUTRAL = "NEUTRAL"
BEAR = "BEAR"

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
VIX_CIRCUIT_BREAKER_LEVEL = 40
DEFAULT_HYSTERESIS_HOURS = 24
DEFAULT_MA200_BAND_PCT = 0.02  # ±2%


class ComboRegimeDetector:
    """Unified regime detector with VIX circuit breaker, hysteresis, and
    MA200 abstain zone."""

    def __init__(
        self,
        hysteresis_hours: float = DEFAULT_HYSTERESIS_HOURS,
        ma200_band_pct: float = DEFAULT_MA200_BAND_PCT,
    ) -> None:
        self._hysteresis_hours = hysteresis_hours
        self._ma200_band_pct = ma200_band_pct
        self._last_regime: Optional[str] = None
        self._last_regime_time: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        *,
        vix: float,
        price: float,
        ma200: float,
        signals: List[str],
        now: Optional[datetime] = None,
    ) -> Dict:
        """Run unified regime detection.

        Args:
            vix: Current VIX index level.
            price: Current price of the underlying (e.g. SPY).
            ma200: 200-day simple moving average of the underlying.
            signals: Exactly 3 directional votes, each ``BULL``, ``BEAR``,
                     or ``NEUTRAL``.
            now: Optional explicit timestamp (for deterministic testing).

        Returns:
            Dict with keys ``regime``, ``confidence``, ``reason``,
            ``timestamp``, ``hysteresis_active``.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # --- 1. VIX circuit breaker (bypasses hysteresis) ----------------
        if vix > VIX_CIRCUIT_BREAKER_LEVEL:
            return self._finalize(
                BEAR, 1.0, "vix_circuit_breaker", now, bypass_hysteresis=True,
            )

        # --- 2. MA200 abstain zone --------------------------------------
        if ma200 > 0:
            distance_pct = abs(price - ma200) / ma200
            if distance_pct <= self._ma200_band_pct:
                return self._finalize(NEUTRAL, 0.5, "ma200_abstain", now)

        # --- 3. Signal voting --------------------------------------------
        bull_count = sum(1 for s in signals if s == BULL)
        bear_count = sum(1 for s in signals if s == BEAR)
        n = len(signals)

        if bull_count == n and n >= 3:
            raw_regime, confidence = BULL, 1.0
        elif bear_count == n and n >= 3:
            raw_regime, confidence = BEAR, 1.0
        elif bear_count >= 2:
            raw_regime, confidence = NEUTRAL, 0.6
        else:
            raw_regime, confidence = NEUTRAL, 0.5

        return self._finalize(raw_regime, confidence, "vote", now)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_hysteresis(self, proposed: str, now: datetime) -> str:
        """Block regime flips that occur within the cooldown window."""
        if self._last_regime is None:
            return proposed

        if proposed == self._last_regime:
            return proposed

        elapsed = now - self._last_regime_time  # type: ignore[operator]
        if elapsed < timedelta(hours=self._hysteresis_hours):
            return self._last_regime  # block the flip

        return proposed  # allow the flip

    def _finalize(
        self,
        raw_regime: str,
        confidence: float,
        reason: str,
        now: datetime,
        *,
        bypass_hysteresis: bool = False,
    ) -> Dict:
        if bypass_hysteresis:
            final_regime = raw_regime
            hysteresis_active = False
        else:
            final_regime = self._apply_hysteresis(raw_regime, now)
            hysteresis_active = final_regime != raw_regime

        # Update state only on actual regime change (or first call).
        if self._last_regime is None or final_regime != self._last_regime:
            self._last_regime = final_regime
            self._last_regime_time = now

        return {
            "regime": final_regime,
            "confidence": round(confidence, 3),
            "reason": reason,
            "timestamp": now.isoformat(),
            "hysteresis_active": hysteresis_active,
        }
