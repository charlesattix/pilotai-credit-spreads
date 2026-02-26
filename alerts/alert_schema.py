"""
Universal alert schema for the MASTERPLAN options alert system.

Defines the canonical Alert dataclass, supporting enums, and conversion
utilities.  All five alert types (credit_spread, momentum_swing,
iron_condor, earnings_play, gamma_lotto) share this schema.
"""

import uuid
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional

from shared.constants import MAX_RISK_PER_TRADE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AlertType(str, Enum):
    credit_spread = "credit_spread"
    momentum_swing = "momentum_swing"
    iron_condor = "iron_condor"
    earnings_play = "earnings_play"
    gamma_lotto = "gamma_lotto"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    SPECULATIVE = "SPECULATIVE"


class TimeSensitivity(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    WITHIN_1HR = "WITHIN_1HR"
    TODAY = "TODAY"


class AlertStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    expired = "expired"
    cancelled = "cancelled"


class Direction(str, Enum):
    bullish = "bullish"
    bearish = "bearish"
    neutral = "neutral"


# ---------------------------------------------------------------------------
# Sub-dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Leg:
    """A single option leg in the alert."""
    strike: float
    option_type: str   # "put" or "call"
    action: str        # "sell" or "buy"
    expiration: str    # ISO date string


@dataclass
class SizeResult:
    """Output of the position sizer."""
    risk_pct: float
    contracts: int
    dollar_risk: float
    max_loss: float


# ---------------------------------------------------------------------------
# Alert dataclass
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    """Universal alert containing all 8 MASTERPLAN-required fields plus metadata."""

    # --- Required MASTERPLAN fields ---
    type: AlertType
    ticker: str
    direction: Direction
    legs: List[Leg]
    entry_price: float          # credit received (for credit strategies)
    stop_loss: float
    profit_target: float
    risk_pct: float             # fraction of account risked (0–0.05)

    # --- Supporting fields ---
    confidence: Confidence = Confidence.MEDIUM
    thesis: str = ""
    time_sensitivity: TimeSensitivity = TimeSensitivity.TODAY
    management_instructions: str = ""
    expires_at: Optional[datetime] = None

    # --- Scoring / status ---
    score: float = 0.0
    status: AlertStatus = AlertStatus.pending
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # --- Position sizing (attached after risk gate) ---
    sizing: Optional[SizeResult] = None

    # --- Identity ---
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        """Validate invariants."""
        if not self.legs:
            raise ValueError("Alert must have at least one leg")
        if self.risk_pct <= 0 or self.risk_pct > MAX_RISK_PER_TRADE:
            raise ValueError(
                f"risk_pct must be in (0, {MAX_RISK_PER_TRADE}], got {self.risk_pct}"
            )
        if self.entry_price <= 0:
            raise ValueError(f"entry_price must be > 0, got {self.entry_price}")

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_opportunity(cls, opp: dict) -> "Alert":
        """Convert an existing SpreadOpportunity dict to an Alert.

        This bridges the legacy AlertGenerator format to the new universal
        schema.  Fields that don't exist in the old format get sensible
        defaults.
        """
        opp_type = opp.get("type", "bull_put_spread")
        expiration = str(opp.get("expiration", ""))

        # Map legacy type → AlertType
        if "condor" in opp_type:
            alert_type = AlertType.iron_condor
        elif "put" in opp_type:
            alert_type = AlertType.credit_spread
        else:
            alert_type = AlertType.credit_spread

        # Infer direction
        if "condor" in opp_type:
            direction = Direction.neutral
        elif "put" in opp_type:
            direction = Direction.bullish
        else:
            direction = Direction.bearish

        # Build legs
        legs: List[Leg] = []
        if "condor" in opp_type:
            # Put side
            legs.append(Leg(opp["short_strike"], "put", "sell", expiration))
            legs.append(Leg(opp["long_strike"], "put", "buy", expiration))
            # Call side
            legs.append(Leg(opp["call_short_strike"], "call", "sell", expiration))
            legs.append(Leg(opp["call_long_strike"], "call", "buy", expiration))
        elif "put" in opp_type:
            legs.append(Leg(opp["short_strike"], "put", "sell", expiration))
            legs.append(Leg(opp["long_strike"], "put", "buy", expiration))
        else:
            legs.append(Leg(opp["short_strike"], "call", "sell", expiration))
            legs.append(Leg(opp["long_strike"], "call", "buy", expiration))

        # Risk percentage: estimate from max_loss relative to a notional
        # account.  Use 2% as default since we don't know account size here.
        risk_pct = min(opp.get("risk_pct", 0.02), MAX_RISK_PER_TRADE)
        if risk_pct <= 0:
            risk_pct = 0.02

        # Score
        score = opp.get("score", 0)

        # Confidence mapping based on score
        if score >= 80:
            confidence = Confidence.HIGH
        elif score >= 60:
            confidence = Confidence.MEDIUM
        else:
            confidence = Confidence.SPECULATIVE

        # 0DTE-aware time sensitivity and expiry
        dte = opp.get("dte", 999)
        if dte <= 1:
            time_sensitivity = TimeSensitivity.IMMEDIATE
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        else:
            time_sensitivity = TimeSensitivity.TODAY
            expires_at = datetime.now(timezone.utc) + timedelta(hours=4)

        # Build thesis — enrich for cash-settled instruments
        thesis = opp.get("thesis", f"{opp['ticker']} {opp_type} at score {score:.0f}")
        if opp.get("settlement") == "cash":
            thesis += " (cash-settled, Section 1256)"

        # Management instructions — use opportunity-provided if available
        default_instructions = (
            "Close at 50% profit or stop loss. Roll if challenged before expiration."
        )
        if opp.get("alert_source") == "zero_dte" and opp.get("management_instructions"):
            management_instructions = opp["management_instructions"]
        else:
            management_instructions = opp.get("management_instructions", default_instructions)

        return cls(
            type=alert_type,
            ticker=opp["ticker"],
            direction=direction,
            legs=legs,
            entry_price=opp.get("credit", 0.01),
            stop_loss=opp.get("stop_loss", 0.0),
            profit_target=opp.get("profit_target", 0.0),
            risk_pct=risk_pct,
            confidence=confidence,
            thesis=thesis,
            time_sensitivity=time_sensitivity,
            management_instructions=management_instructions,
            expires_at=expires_at,
            score=score,
        )

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON / SQLite storage."""
        d = asdict(self)
        # Convert enums to their values
        d["type"] = self.type.value
        d["direction"] = self.direction.value
        d["confidence"] = self.confidence.value
        d["time_sensitivity"] = self.time_sensitivity.value
        d["status"] = self.status.value
        # Convert datetimes to ISO strings
        d["created_at"] = self.created_at.isoformat()
        if self.expires_at:
            d["expires_at"] = self.expires_at.isoformat()
        return d
