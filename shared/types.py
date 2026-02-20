"""TypedDict definitions for major data shapes used across the system."""

from typing import TypedDict, List
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


class IronCondorOpportunity(SpreadOpportunity):
    """An iron condor opportunity (bull put + bear call on same expiration)."""
    call_short_strike: float
    call_long_strike: float
    put_credit: float
    call_credit: float
    distance_to_put_short: float
    distance_to_call_short: float


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


class StrategyConfig(TypedDict, total=False):
    """Strategy-related configuration."""
    min_dte: int
    max_dte: int
    min_credit: float
    max_spread_width: float
    delta_range: List[float]
    min_pop: float
    min_volume: int
    min_open_interest: int
    symbols: List[str]
    spread_type: str

class RiskConfig(TypedDict, total=False):
    """Risk management configuration."""
    max_position_size: float
    max_portfolio_risk: float
    max_positions: int
    profit_target: float
    stop_loss: float
    max_daily_loss: float
    kelly_fraction: float

class AlertsConfig(TypedDict, total=False):
    """Alert and notification configuration."""
    telegram_enabled: bool
    telegram_token: str
    telegram_chat_id: str
    min_score: float
    alert_interval: int

class MLConfig(TypedDict, total=False):
    """ML pipeline configuration."""
    model_path: str
    retrain_interval: int
    min_confidence: float
    feature_set: List[str]
    lookahead_days: int

class BacktestConfig(TypedDict, total=False):
    """Backtesting configuration."""
    start_date: str
    end_date: str
    initial_capital: float
    commission: float

class AppConfig(TypedDict, total=False):
    """Top-level application configuration."""
    strategy: StrategyConfig
    risk: RiskConfig
    alerts: AlertsConfig
    ml: MLConfig
    backtest: BacktestConfig
    paper_trading: bool
    log_level: str
    data_dir: str
