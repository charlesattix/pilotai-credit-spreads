"""
Alerts module for generating and sending trade alerts.
"""

from .alert_generator import AlertGenerator
from .telegram_bot import TelegramBot
from .alert_schema import Alert, AlertType, Confidence, TimeSensitivity, Leg, SizeResult
from .risk_gate import RiskGate
from .alert_position_sizer import AlertPositionSizer
from .alert_router import AlertRouter
from .zero_dte_scanner import ZeroDTEScanner
from .zero_dte_exit_monitor import ZeroDTEExitMonitor
from .iron_condor_scanner import IronCondorScanner
from .iron_condor_exit_monitor import IronCondorExitMonitor
from .momentum_scanner import MomentumScanner
from .momentum_exit_monitor import MomentumExitMonitor
from .earnings_scanner import EarningsScanner
from .earnings_exit_monitor import EarningsExitMonitor
from .gamma_scanner import GammaScanner
from .gamma_exit_monitor import GammaExitMonitor

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
