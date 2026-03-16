"""
shared/iron_vault.py — Iron Vault: The Single Authoritative Data Provider

All options and macro data access for backtesting goes through IronVault.
Hard-fails on missing DB or invalid setup. NEVER returns synthetic data.
No silent fallbacks. No heuristic pricing. Ever.

Usage:
    from shared.iron_vault import IronVault, IronVaultError
    hd = IronVault.instance()
    bt = Backtester(config, historical_data=hd)
"""

import logging
import os
import sqlite3
from typing import Dict, List, Optional

from backtest.historical_data import HistoricalOptionsData
from shared.constants import DATA_DIR

logger = logging.getLogger(__name__)


class IronVaultError(Exception):
    """Raised when Iron Vault cannot provide real data."""


class IronVault:
    """Singleton data provider wrapping HistoricalOptionsData.

    All backtester data access goes through this class.
    Validates DB on startup; delegates all option/price queries to
    HistoricalOptionsData (offline_mode=True — cache-only, no live Polygon calls).

    The IronVaultError is raised only at initialisation if the DB is missing
    or empty.  Per-contract cache misses return None (caller skips the trade)
    — that is the correct behaviour, NOT a fallback to synthetic pricing.
    """

    _instance: Optional["IronVault"] = None

    # ── Singleton factory ──────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "IronVault":
        """Return the process-level singleton, creating it on first call.

        Reads POLYGON_API_KEY from environment (value only needed for live
        backfill; offline_mode=True so no live calls are made here).

        Raises:
            IronVaultError: If options_cache.db is missing or contains no data.
        """
        if cls._instance is None:
            api_key = os.getenv("POLYGON_API_KEY", "")
            cls._instance = cls(api_key)
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset the singleton (useful in tests)."""
        if cls._instance is not None:
            try:
                cls._instance._hd.close()
            except Exception:
                pass
        cls._instance = None

    # ── Constructor ────────────────────────────────────────────────────────────

    def __init__(self, api_key: str, cache_dir: str = DATA_DIR):
        db_path = os.path.join(cache_dir, "options_cache.db")
        if not os.path.exists(db_path):
            raise IronVaultError(
                f"options_cache.db not found at {db_path}. "
                "Run: python scripts/iron_vault_setup.py"
            )
        self._hd = HistoricalOptionsData(api_key, cache_dir=cache_dir, offline_mode=True)
        self._db_path = db_path
        self._validate_has_data()
        logger.info("IronVault initialised (db=%s)", db_path)

    def _validate_has_data(self):
        """Raise IronVaultError if the DB is empty (no contracts at all)."""
        conn = sqlite3.connect(self._db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM option_contracts")
            count = cur.fetchone()[0]
        finally:
            conn.close()
        if count == 0:
            raise IronVaultError(
                "options_cache.db exists but contains no option contracts. "
                "Run: python scripts/iron_vault_setup.py  to check coverage, "
                "then fetch missing data with fetch_sector_options.py."
            )

    # ── HistoricalOptionsData delegation ──────────────────────────────────────
    # All methods below delegate to the underlying HistoricalOptionsData instance.
    # This makes IronVault a drop-in replacement for HistoricalOptionsData
    # everywhere in the codebase.

    @staticmethod
    def build_occ_symbol(ticker, expiration, strike, option_type) -> str:
        return HistoricalOptionsData.build_occ_symbol(ticker, expiration, strike, option_type)

    def get_contract_price(self, symbol: str, date: str) -> Optional[float]:
        return self._hd.get_contract_price(symbol, date)

    def get_available_strikes(
        self, ticker: str, expiration: str, as_of_date: str, option_type: str = "P"
    ) -> List[float]:
        return self._hd.get_available_strikes(ticker, expiration, as_of_date, option_type)

    def get_strikes_with_approx_delta(
        self, ticker, expiration, current_price, date_str,
        option_type="P", iv_estimate=0.25, risk_free_rate=0.045,
    ) -> List[Dict]:
        return self._hd.get_strikes_with_approx_delta(
            ticker, expiration, current_price, date_str,
            option_type, iv_estimate, risk_free_rate,
        )

    def get_spread_prices(
        self, ticker, expiration, short_strike, long_strike, option_type, date
    ) -> Optional[Dict]:
        return self._hd.get_spread_prices(
            ticker, expiration, short_strike, long_strike, option_type, date
        )

    def get_intraday_bar(
        self, symbol: str, date_str: str, hour: int, minute: int
    ) -> Optional[Dict]:
        return self._hd.get_intraday_bar(symbol, date_str, hour, minute)

    def get_intraday_spread_prices(
        self, ticker, expiration, short_strike, long_strike,
        option_type, date_str, hour, minute,
    ) -> Optional[Dict]:
        return self._hd.get_intraday_spread_prices(
            ticker, expiration, short_strike, long_strike,
            option_type, date_str, hour, minute,
        )

    def get_prev_daily_volume(self, contract_symbol: str, before_date: str) -> Optional[int]:
        return self._hd.get_prev_daily_volume(contract_symbol, before_date)

    def get_prev_daily_oi(self, contract_symbol: str, before_date: str) -> Optional[int]:
        return self._hd.get_prev_daily_oi(contract_symbol, before_date)

    # ── Coverage reporting ─────────────────────────────────────────────────────

    def coverage_report(self) -> Dict:
        """Return DB row counts for quick coverage check.

        Returns dict with:
            contracts_total, daily_bars_total, intraday_bars_total,
            by_ticker: {ticker: {contracts, daily_bars, years: [...]}}
        """
        conn = sqlite3.connect(self._db_path)
        try:
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) FROM option_contracts")
            contracts_total = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM option_daily WHERE date != '0000-00-00'")
            daily_total = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM option_intraday WHERE bar_time != 'FETCHED'")
            intraday_total = cur.fetchone()[0]

            # Per-ticker breakdown
            cur.execute("""
                SELECT ticker, COUNT(*) as cnt,
                       MIN(substr(expiration,1,4)) as first_year,
                       MAX(substr(expiration,1,4)) as last_year
                FROM option_contracts
                GROUP BY ticker
                ORDER BY ticker
            """)
            by_ticker = {}
            for row in cur.fetchall():
                ticker, cnt, first_yr, last_yr = row
                years = list(range(int(first_yr), int(last_yr) + 1)) if first_yr else []
                by_ticker[ticker] = {"contracts": cnt, "years": years}

        finally:
            conn.close()

        return {
            "db_path": self._db_path,
            "contracts_total": contracts_total,
            "daily_bars_total": daily_total,
            "intraday_bars_total": intraday_total,
            "by_ticker": by_ticker,
        }

    def close(self):
        self._hd.close()
