"""Shared constants used across the trading system.

This is the single canonical location for all named constants.  Do NOT
create secondary ``constants.py`` files elsewhere in the tree.
"""

from datetime import datetime

# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------
MAX_CONTRACTS_PER_TRADE = 10

# ---------------------------------------------------------------------------
# Position management
# ---------------------------------------------------------------------------
MANAGEMENT_DTE_THRESHOLD = 21

# ---------------------------------------------------------------------------
# Options pricing
# ---------------------------------------------------------------------------
DEFAULT_RISK_FREE_RATE = 0.045

# ---------------------------------------------------------------------------
# Backtesting defaults
# ---------------------------------------------------------------------------
BACKTEST_SHORT_STRIKE_OTM_FRACTION = 0.90
BACKTEST_CREDIT_FRACTION = 0.35

# ---------------------------------------------------------------------------
# Economic calendar
# ---------------------------------------------------------------------------

# Known FOMC meeting dates 2025-2026
FOMC_DATES = [
    datetime(2025, 1, 29),
    datetime(2025, 3, 19),
    datetime(2025, 5, 7),
    datetime(2025, 6, 18),
    datetime(2025, 7, 30),
    datetime(2025, 9, 17),
    datetime(2025, 11, 5),
    datetime(2025, 12, 17),
    datetime(2026, 1, 28),
    datetime(2026, 2, 4),
    datetime(2026, 3, 18),
    datetime(2026, 5, 6),
    datetime(2026, 6, 17),
    datetime(2026, 7, 29),
    datetime(2026, 9, 16),
    datetime(2026, 11, 4),
    datetime(2026, 12, 16),
]

# CPI release dates (typically 2nd Tuesday-Thursday of month)
CPI_RELEASE_DAYS = [12, 13, 14]
