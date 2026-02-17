"""Backward-compatible re-export shim.

All constants now live in ``shared.constants``.  This file exists only so
that existing ``from constants import ...`` statements keep working while
callers are migrated.
"""

from shared.constants import (  # noqa: F401
    MAX_CONTRACTS_PER_TRADE,
    MANAGEMENT_DTE_THRESHOLD,
    DEFAULT_RISK_FREE_RATE,
    BACKTEST_SHORT_STRIKE_OTM_FRACTION,
    BACKTEST_CREDIT_FRACTION,
)
