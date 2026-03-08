"""
Strategy modules for the portfolio backtester.

Each strategy implements BaseStrategy with:
- generate_signals(market_data) -> List[Signal]
- manage_position(position, market_data) -> PositionAction
- size_position(signal, portfolio_state) -> int
- get_param_space() -> List[ParamDef]
"""

from strategies.base import (
    BaseStrategy, Signal, Position, TradeLeg, ParamDef,
    MarketSnapshot, PortfolioState,
    TradeDirection, PositionAction, LegType,
)
from strategies.credit_spread import CreditSpreadStrategy
from strategies.iron_condor import IronCondorStrategy
from strategies.gamma_lotto import GammaLottoStrategy
from strategies.straddle_strangle import StraddleStrangleStrategy
from strategies.debit_spread import DebitSpreadStrategy
from strategies.calendar_spread import CalendarSpreadStrategy
from strategies.momentum_swing import MomentumSwingStrategy

# Registry: name -> class
STRATEGY_REGISTRY = {
    "credit_spread": CreditSpreadStrategy,
    "iron_condor": IronCondorStrategy,
    "gamma_lotto": GammaLottoStrategy,
    "straddle_strangle": StraddleStrangleStrategy,
    "debit_spread": DebitSpreadStrategy,
    "calendar_spread": CalendarSpreadStrategy,
    "momentum_swing": MomentumSwingStrategy,
}

__all__ = [
    "BaseStrategy", "Signal", "Position", "TradeLeg", "ParamDef",
    "MarketSnapshot", "PortfolioState",
    "TradeDirection", "PositionAction", "LegType",
    "CreditSpreadStrategy",
    "IronCondorStrategy",
    "GammaLottoStrategy",
    "StraddleStrangleStrategy",
    "DebitSpreadStrategy",
    "CalendarSpreadStrategy",
    "MomentumSwingStrategy",
    "STRATEGY_REGISTRY",
]
