"""
Historical Options Data Provider
Fetches real historical options prices from Polygon.io and caches locally in SQLite.
"""

import logging
import os
import sqlite3
import time
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from shared.constants import DATA_DIR

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"

# How far back to fetch when caching a new contract (covers most backtests)
_DEFAULT_LOOKBACK_YEARS = 2


class HistoricalOptionsData:
    """Fetch and cache historical daily OHLCV for individual option contracts."""

    def __init__(self, api_key: str, cache_dir: str = DATA_DIR):
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        self.api_key = api_key
        self.cache_dir = cache_dir

        # HTTP session with automatic retries for transient failures
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            backoff_jitter=0.25,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

        # Rate-limit tracking
        self._last_api_call = 0.0
        self._api_calls = 0

        # SQLite cache
        os.makedirs(cache_dir, exist_ok=True)
        self._db_path = os.path.join(cache_dir, "options_cache.db")
        self._conn = sqlite3.connect(self._db_path)
        self._init_cache_db()

        logger.info("HistoricalOptionsData initialized (cache: %s)", self._db_path)

    def _init_cache_db(self):
        """Create cache tables if they don't exist."""
        cur = self._conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS option_daily (
                contract_symbol TEXT NOT NULL,
                date            TEXT NOT NULL,
                open            REAL,
                high            REAL,
                low             REAL,
                close           REAL,
                volume          INTEGER,
                PRIMARY KEY (contract_symbol, date)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS option_contracts (
                ticker          TEXT NOT NULL,
                expiration      TEXT NOT NULL,
                strike          REAL NOT NULL,
                option_type     TEXT NOT NULL,
                contract_symbol TEXT NOT NULL,
                as_of_date      TEXT NOT NULL,
                PRIMARY KEY (ticker, expiration, strike, option_type)
            )
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # OCC symbol construction
    # ------------------------------------------------------------------

    @staticmethod
    def build_occ_symbol(
        ticker: str, expiration: datetime, strike: float, option_type: str
    ) -> str:
        """Construct a Polygon OCC option symbol.

        Format: O:SPY250321P00450000
          - ticker (padded to 6 chars historically, but Polygon uses raw ticker)
          - YYMMDD expiration
          - P/C
          - strike * 1000, zero-padded to 8 digits

        Args:
            ticker: Underlying ticker (e.g. "SPY")
            expiration: Expiration date
            strike: Strike price (e.g. 450.0)
            option_type: "P" or "C" (or "put"/"call")

        Returns:
            OCC symbol string like "O:SPY250321P00450000"
        """
        exp_str = expiration.strftime("%y%m%d")
        ot = option_type[0].upper()  # "P" or "C"
        strike_int = int(round(strike * 1000))
        return f"O:{ticker}{exp_str}{ot}{strike_int:08d}"

    # ------------------------------------------------------------------
    # Price lookups (cache-first)
    # ------------------------------------------------------------------

    def get_contract_price(self, symbol: str, date: str) -> Optional[float]:
        """Get the closing price for an option contract on a specific date.

        Checks the local cache first. On cache miss, fetches the full
        daily series from Polygon and caches everything.

        Args:
            symbol: OCC symbol (e.g. "O:SPY250321P00450000")
            date: Date string "YYYY-MM-DD"

        Returns:
            Closing price or None if no data available.
        """
        # Check cache
        cur = self._conn.cursor()
        cur.execute(
            "SELECT close FROM option_daily WHERE contract_symbol = ? AND date = ?",
            (symbol, date),
        )
        row = cur.fetchone()
        if row is not None:
            return row[0]

        # Check if we already fetched this contract (just no data for this date)
        cur.execute(
            "SELECT 1 FROM option_daily WHERE contract_symbol = ? LIMIT 1",
            (symbol,),
        )
        if cur.fetchone() is not None:
            # Already fetched full series — date just doesn't exist
            return None

        # Cache miss — fetch full series
        self._fetch_and_cache(symbol)

        # Retry from cache
        cur.execute(
            "SELECT close FROM option_daily WHERE contract_symbol = ? AND date = ?",
            (symbol, date),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def _fetch_and_cache(self, symbol: str):
        """Fetch full daily OHLCV series for an option contract and cache it.

        Calls /v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}
        One API call per contract; results cached for all future lookups.
        """
        end = datetime.now()
        start = end - timedelta(days=_DEFAULT_LOOKBACK_YEARS * 365)
        from_str = start.strftime("%Y-%m-%d")
        to_str = end.strftime("%Y-%m-%d")

        data = self._api_get(
            f"/v2/aggs/ticker/{symbol}/range/1/day/{from_str}/{to_str}",
            params={"adjusted": "true", "sort": "asc", "limit": 5000},
        )

        results = data.get("results", [])
        if not results:
            # Insert a sentinel so we don't re-fetch
            cur = self._conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO option_daily (contract_symbol, date, close) VALUES (?, ?, ?)",
                (symbol, "0000-00-00", None),
            )
            self._conn.commit()
            logger.debug("No data from Polygon for %s", symbol)
            return

        cur = self._conn.cursor()
        rows = []
        for bar in results:
            ts = bar.get("t", 0)
            dt = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            rows.append((
                symbol,
                dt,
                bar.get("o"),
                bar.get("h"),
                bar.get("l"),
                bar.get("c"),
                bar.get("v", 0),
            ))

        cur.executemany(
            "INSERT OR IGNORE INTO option_daily "
            "(contract_symbol, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        logger.debug("Cached %d bars for %s", len(rows), symbol)

    # ------------------------------------------------------------------
    # Contract discovery
    # ------------------------------------------------------------------

    def get_available_strikes(
        self, ticker: str, expiration: str, as_of_date: str, option_type: str = "P"
    ) -> List[float]:
        """Find available option strikes for a given expiration.

        Checks local cache first, then queries Polygon /v3/reference/options/contracts.

        Args:
            ticker: Underlying ticker
            expiration: Expiration date "YYYY-MM-DD"
            as_of_date: Date to query as-of
            option_type: "P" for puts or "C" for calls

        Returns:
            Sorted list of available strike prices.
        """
        ot = option_type[0].upper()

        # Check cache
        cur = self._conn.cursor()
        cur.execute(
            "SELECT strike FROM option_contracts "
            "WHERE ticker = ? AND expiration = ? AND option_type = ?",
            (ticker, expiration, ot),
        )
        cached = [row[0] for row in cur.fetchall()]
        if cached:
            return sorted(cached)

        # Fetch from Polygon
        contracts = self._fetch_contracts(ticker, expiration, as_of_date, ot)

        if not contracts:
            return []

        # Cache
        rows = []
        for c in contracts:
            strike = c.get("strike_price", 0)
            sym = c.get("ticker", "")
            rows.append((ticker, expiration, strike, ot, sym, as_of_date))

        cur.executemany(
            "INSERT OR IGNORE INTO option_contracts "
            "(ticker, expiration, strike, option_type, contract_symbol, as_of_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

        return sorted(c.get("strike_price", 0) for c in contracts)

    def _fetch_contracts(
        self, ticker: str, expiration: str, as_of_date: str, option_type: str
    ) -> List[Dict]:
        """Fetch option contracts from Polygon reference endpoint."""
        ct = "put" if option_type == "P" else "call"
        params = {
            "underlying_ticker": ticker,
            "expiration_date": expiration,
            "contract_type": ct,
            "as_of": as_of_date,
            "limit": 1000,
        }
        data = self._api_get("/v3/reference/options/contracts", params=params)
        return data.get("results", [])

    # ------------------------------------------------------------------
    # Spread pricing convenience
    # ------------------------------------------------------------------

    def get_spread_prices(
        self,
        ticker: str,
        expiration: datetime,
        short_strike: float,
        long_strike: float,
        option_type: str,
        date: str,
    ) -> Optional[Dict]:
        """Get both legs of a spread and compute credit/debit.

        Args:
            ticker: Underlying ticker
            expiration: Expiration datetime
            short_strike: Short leg strike price
            long_strike: Long leg strike price
            option_type: "P" or "C"
            date: Date to look up prices "YYYY-MM-DD"

        Returns:
            Dict with short_close, long_close, spread_value or None if data missing.
        """
        short_sym = self.build_occ_symbol(ticker, expiration, short_strike, option_type)
        long_sym = self.build_occ_symbol(ticker, expiration, long_strike, option_type)

        short_close = self.get_contract_price(short_sym, date)
        long_close = self.get_contract_price(long_sym, date)

        if short_close is None or long_close is None:
            return None

        # For puts: short is higher strike, credit = short - long
        # For calls: short is lower strike, credit = short - long
        spread_value = short_close - long_close

        return {
            "short_close": short_close,
            "long_close": long_close,
            "spread_value": spread_value,
        }

    # ------------------------------------------------------------------
    # Polygon API helpers
    # ------------------------------------------------------------------

    def _api_get(self, path: str, params: Optional[Dict] = None) -> Dict:
        """Make an authenticated GET request to Polygon with rate limiting."""
        # Enforce minimum 1s between API calls
        now = time.time()
        elapsed = now - self._last_api_call
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

        p = (params or {}).copy()
        p["apiKey"] = self.api_key
        url = f"{BASE_URL}{path}"

        try:
            resp = self.session.get(url, params=p, timeout=15)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 429:
                # Rate limited — back off and retry once
                delay = 5.0 + random.uniform(0, 3)
                logger.warning("Rate limited by Polygon, waiting %.1fs", delay)
                time.sleep(delay)
                resp = self.session.get(url, params=p, timeout=15)
                resp.raise_for_status()
            else:
                logger.error("Polygon API error (%s): %s", path, e)
                return {}
        except requests.exceptions.RequestException as e:
            logger.error("Polygon API request failed (%s): %s", path, e)
            return {}

        self._last_api_call = time.time()
        self._api_calls += 1
        return resp.json()

    @property
    def api_calls_made(self) -> int:
        """Number of API calls made this session."""
        return self._api_calls

    def close(self):
        """Close database connection and HTTP session."""
        self._conn.close()
        self.session.close()

    def clear_cache(self):
        """Delete all cached data (for --clear-cache flag)."""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM option_daily")
        cur.execute("DELETE FROM option_contracts")
        self._conn.commit()
        logger.info("Options cache cleared")
