"""Shared constants used across the trading system."""

from datetime import datetime

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
