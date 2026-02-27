"""
Abstract base class and universal data types for all strategy modules.

Every strategy implements: generate_signals(), manage_position(),
size_position(), and get_param_space().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class PositionAction(str, Enum):
    HOLD = "hold"
    CLOSE_PROFIT = "close_profit_target"
    CLOSE_STOP = "close_stop_loss"
    CLOSE_EXPIRY = "close_expiration"
    CLOSE_TIME = "close_time_decay"
    CLOSE_EVENT = "close_event"
    CLOSE_SIGNAL = "close_signal_exit"


class LegType(str, Enum):
    LONG_CALL = "long_call"
    SHORT_CALL = "short_call"
    LONG_PUT = "long_put"
    SHORT_PUT = "short_put"
    LONG_STOCK = "long_stock"
    SHORT_STOCK = "short_stock"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class TradeLeg:
    """One leg of a multi-leg options trade."""
    leg_type: LegType
    strike: float
    expiration: datetime
    contracts: int = 1
    entry_price: float = 0.0


@dataclass
class Signal:
    """Strategy output: a recommended trade entry.

    The portfolio backtester decides whether to accept based on capital
    limits, then calls size_position() for contract count.
    """
    strategy_name: str
    ticker: str
    direction: TradeDirection
    legs: List[TradeLeg]

    # Entry economics (per 1 spread / 1 contract unit)
    net_credit: float = 0.0          # positive = credit, negative = debit
    max_loss: float = 0.0
    max_profit: float = 0.0

    # Exit rules
    profit_target_pct: float = 0.50
    stop_loss_pct: float = 2.0

    # Scoring
    score: float = 0.0
    signal_date: Optional[datetime] = None
    expiration: Optional[datetime] = None
    dte: int = 0

    # Strategy-specific metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    """Active tracked trade managed by the portfolio backtester."""
    id: str
    strategy_name: str
    ticker: str
    direction: TradeDirection
    legs: List[TradeLeg]

    contracts: int = 1
    entry_date: Optional[datetime] = None
    net_credit: float = 0.0
    max_loss_per_unit: float = 0.0
    max_profit_per_unit: float = 0.0

    profit_target_pct: float = 0.50
    stop_loss_pct: float = 2.0

    current_value: float = 0.0
    current_pnl: float = 0.0

    exit_date: Optional[datetime] = None
    exit_reason: Optional[str] = None
    realized_pnl: float = 0.0

    metadata: Dict[str, Any] = field(default_factory=dict)
    commission_paid: float = 0.0


@dataclass
class ParamDef:
    """Definition of one tunable parameter for optimization."""
    name: str
    param_type: str           # "float", "int", "bool", "choice"
    default: Any
    low: Any = None
    high: Any = None
    step: Any = None
    choices: Optional[List[Any]] = None
    description: str = ""


@dataclass
class MarketSnapshot:
    """All market data available on a given trading day.

    Built once per day by the portfolio backtester and passed to every
    strategy's generate_signals() and manage_position().
    """
    date: datetime

    # Per-ticker OHLCV DataFrames (history up to this date)
    price_data: Dict[str, pd.DataFrame]

    # Current close prices (convenience)
    prices: Dict[str, float]

    # VIX
    vix: float = 20.0
    vix_history: Optional[pd.Series] = None

    # Pre-computed indicators per ticker
    iv_rank: Dict[str, float] = field(default_factory=dict)
    realized_vol: Dict[str, float] = field(default_factory=dict)
    rsi: Dict[str, float] = field(default_factory=dict)

    # Economic calendar events within lookahead window
    upcoming_events: List[Dict] = field(default_factory=list)

    # Economic events that recently occurred (within last 2 days)
    recent_events: List[Dict] = field(default_factory=list)

    # Current market regime (from engine.regime.RegimeClassifier)
    regime: Optional[str] = None


@dataclass
class PortfolioState:
    """Current portfolio state passed to size_position()."""
    equity: float
    starting_capital: float
    cash: float
    open_positions: List[Position] = field(default_factory=list)
    total_risk: float = 0.0
    iv_rank: float = 25.0
    max_portfolio_risk_pct: float = 0.40


# ---------------------------------------------------------------------------
# Abstract Base Class
# ---------------------------------------------------------------------------

class BaseStrategy(ABC):
    """Abstract base class for all strategy modules.

    Lifecycle in the portfolio backtester's day loop::

        for date in trading_dates:
            snapshot = build_market_snapshot(...)
            for strategy in strategies:
                for pos in portfolio.positions_for(strategy.name):
                    action = strategy.manage_position(pos, snapshot)
                    if action != HOLD: portfolio.close(pos, action)
                for signal in strategy.generate_signals(snapshot):
                    contracts = strategy.size_position(signal, portfolio.state())
                    if contracts > 0 and portfolio.can_accept(signal, contracts):
                        portfolio.open(signal, contracts)
    """

    def __init__(self, params: Dict[str, Any]):
        self.params = params
        self._name = self.__class__.__name__

    @property
    def name(self) -> str:
        return self._name

    # --- Core API ---

    @abstractmethod
    def generate_signals(
        self, market_data: MarketSnapshot,
    ) -> List[Signal]:
        """Scan for new trade opportunities on the current date."""
        ...

    @abstractmethod
    def manage_position(
        self, position: Position, market_data: MarketSnapshot,
    ) -> PositionAction:
        """Check an open position for exit conditions."""
        ...

    @abstractmethod
    def size_position(
        self, signal: Signal, portfolio_state: PortfolioState,
    ) -> int:
        """Determine how many contracts/units to trade (0 = skip)."""
        ...

    # --- Parameter Space ---

    @classmethod
    @abstractmethod
    def get_param_space(cls) -> List[ParamDef]:
        """Return the full parameter space for optimization."""
        ...

    @classmethod
    def get_default_params(cls) -> Dict[str, Any]:
        return {p.name: p.default for p in cls.get_param_space()}

    # --- Helpers ---

    def _p(self, name: str, default: Any = None) -> Any:
        """Get a parameter value with optional default."""
        return self.params.get(name, default)
