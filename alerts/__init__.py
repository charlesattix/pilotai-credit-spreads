"""
Alerts module for generating and sending trade alerts.
"""

from .alert_generator import AlertGenerator
from .alert_position_sizer import AlertPositionSizer
from .alert_router import AlertRouter
from .alert_schema import Alert, AlertType, Confidence, Leg, SizeResult, TimeSensitivity
from .earnings_exit_monitor import EarningsExitMonitor
from .earnings_scanner import EarningsScanner
from .gamma_exit_monitor import GammaExitMonitor
from .gamma_scanner import GammaScanner
from .iron_condor_exit_monitor import IronCondorExitMonitor
from .iron_condor_scanner import IronCondorScanner
from .momentum_exit_monitor import MomentumExitMonitor
from .momentum_scanner import MomentumScanner
from .risk_gate import RiskGate
from .telegram_bot import TelegramBot
from .zero_dte_exit_monitor import ZeroDTEExitMonitor
from .zero_dte_scanner import ZeroDTEScanner

__all__ = [
    'AlertGenerator',
    'TelegramBot',
    'Alert',
    'AlertType',
    'Confidence',
    'TimeSensitivity',
    'Leg',
    'SizeResult',
    'RiskGate',
    'AlertPositionSizer',
    'AlertRouter',
    'ZeroDTEScanner',
    'ZeroDTEExitMonitor',
    'IronCondorScanner',
    'IronCondorExitMonitor',
    'MomentumScanner',
    'MomentumExitMonitor',
    'EarningsScanner',
    'EarningsExitMonitor',
    'GammaScanner',
    'GammaExitMonitor',
]


def get_backtest_validator():
    """Lazy import to avoid pulling in backtest dependencies at import time."""
    from .zero_dte_backtest import ZeroDTEBacktestValidator
    return ZeroDTEBacktestValidator
