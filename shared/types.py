"""TypedDict definitions for major data shapes used across the system."""

from typing import TypedDict, List, Optional
from datetime import datetime


class PositionSizeResult(TypedDict):
    """Return type of PositionSizer.calculate_position_size."""
    recommended_size: float
    kelly_size: float
    fractional_kelly: float
    confidence_adjusted: float
    capped_size: float
    applied_constraints: list
    expected_value: float
    kelly_fraction_used: float
    ml_confidence: float


class PredictionResult(TypedDict, total=False):
    """Return type of SignalModel.predict.

    The ``fallback`` key is only present when the model is unavailable and a
    default prediction is returned.
    """
    prediction: int
    probability: float
    confidence: float
    signal: str
    signal_strength: float
    timestamp: str
    fallback: bool


class SpreadOpportunity(TypedDict):
    """A single credit-spread opportunity produced by CreditSpreadStrategy._find_spreads."""
    ticker: str
    type: str  # e.g. 'bull_put_spread' or 'bear_call_spread'
    expiration: datetime
    dte: int
    short_strike: float
    long_strike: float
    short_delta: float
    credit: float
    max_loss: float
    max_profit: float
    profit_target: float
    stop_loss: float
    spread_width: float
    current_price: float
    distance_to_short: float
    pop: float
    risk_reward: float


class ScoredSpreadOpportunity(SpreadOpportunity):
    """SpreadOpportunity after scoring by _score_opportunities."""
    score: float


class TradeRecommendation(TypedDict):
    """Recommendation sub-dict inside TradeAnalysis."""
    action: str
    confidence: str
    score: float
    position_size: float
    reasoning: List[str]
    ml_probability: float


class TradeAnalysis(TypedDict, total=False):
    """Return type of MLPipeline.analyze_trade.

    Uses ``total=False`` because some keys (regime, iv_analysis, features,
    ml_prediction, event_risk, position_sizing, enhanced_score,
    recommendation) are absent in the fallback/default case, while
    ``error`` is only present in the fallback case.
    """
    ticker: str
    spread_type: str
    timestamp: str
    regime: dict
    iv_analysis: dict
    features: dict
    ml_prediction: PredictionResult
    event_risk: dict
    position_sizing: dict
    enhanced_score: float
    recommendation: TradeRecommendation
    error: bool
