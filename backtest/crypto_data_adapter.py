"""
CryptoDataAdapter — duck-typed historical-data provider for crypto ETF options.

Implements the same interface that Backtester._find_real_spread() and
_close_at_expiration_real() expect from self.historical_data, backed by
data/crypto_options_cache.db instead of the SPY Polygon cache.

Tables consumed (all read-only):
  crypto_option_contracts   — strike universe per (ticker, expiration, as_of_date)
  crypto_option_daily       — daily OHLCV + Greeks for each contract
  crypto_underlying_daily   — daily OHLCV for the ETF itself (IBIT, etc.)

No Polygon API calls — if data is absent, methods return None/[]/empty.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


class CryptoDataError(Exception):
    """Raised when the crypto options cache DB is missing or empty."""


class CryptoDataAdapter:
    """Read-only data provider backed by crypto_options_cache.db.

    Drop-in replacement for IronVault in Backtester when backtesting
    IBIT (or any other crypto ETF whose options are in the cache).

    Args:
        db_path: Absolute or relative path to crypto_options_cache.db.

    Raises:
        CryptoDataError: If the DB file does not exist.
    """

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        if not path.exists():
            raise CryptoDataError(
                f"Crypto options cache not found: {db_path}. "
                "Run scripts/fetch_deribit_btc_options.py to build it."
            )
        # Read-only URI connection — safe for concurrent backtest runs.
        uri = f"file:{path.resolve()}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    # ------------------------------------------------------------------
    # OCC symbol builder (same static format as HistoricalOptionsData)
    # ------------------------------------------------------------------

    @staticmethod
    def build_occ_symbol(
        ticker: str,
        expiration: str,
        strike: float,
        option_type: str,
    ) -> str:
        """Build an OCC-format option symbol.

        Format: O:{ticker}{YYMMDD}{type}{strike_8digits}
        Example: O:IBIT241115P00045000  (IBIT $45 put expiring 2024-11-15)

        The strike is expressed in thousandths of a dollar, zero-padded to
        8 digits (matching the Polygon OCC convention used for SPY).

        Args:
            ticker:      Underlying ticker (e.g. "IBIT").
            expiration:  Expiration date string "YYYY-MM-DD".
            strike:      Strike price in dollars (e.g. 45.0).
            option_type: "P" or "C".

        Returns:
            OCC symbol string.
        """
        dt = datetime.strptime(expiration, "%Y-%m-%d")
        date_str = dt.strftime("%y%m%d")
        strike_int = int(round(strike * 1000))
        return f"O:{ticker}{date_str}{option_type.upper()}{strike_int:08d}"

    # ------------------------------------------------------------------
    # Contract price
    # ------------------------------------------------------------------

    def get_contract_price(self, symbol: str, date: str) -> Optional[float]:
        """Return the daily close price for a contract on a given date.

        Args:
            symbol: OCC symbol string.
            date:   Date string "YYYY-MM-DD".

        Returns:
            Close price or None if not in cache.
        """
        row = self._conn.execute(
            "SELECT close FROM crypto_option_daily "
            "WHERE contract_symbol = ? AND date = ?",
            (symbol, date),
        ).fetchone()
        if row and row["close"] is not None:
            return float(row["close"])
        return None

    # ------------------------------------------------------------------
    # Strike discovery
    # ------------------------------------------------------------------

    def get_available_strikes(
        self,
        ticker: str,
        expiration: str,
        as_of_date: str,
        option_type: str = "P",
    ) -> List[float]:
        """Return sorted list of available strikes for a given expiration.

        Queries crypto_option_contracts for rows whose as_of_date <= as_of_date
        (i.e. the strike was known to exist on or before the backtest date).

        Args:
            ticker:      Underlying ticker.
            expiration:  Expiration date string "YYYY-MM-DD".
            as_of_date:  Backtest date string "YYYY-MM-DD" (no lookahead).
            option_type: "P" or "C".

        Returns:
            Sorted list of strike prices (ascending).
        """
        rows = self._conn.execute(
            "SELECT DISTINCT strike FROM crypto_option_contracts "
            "WHERE ticker = ? AND expiration = ? AND option_type = ? "
            "AND as_of_date <= ? "
            "ORDER BY strike ASC",
            (ticker, expiration, option_type.upper(), as_of_date),
        ).fetchall()
        return [float(r["strike"]) for r in rows]

    # ------------------------------------------------------------------
    # Spread pricing (daily only — no intraday bars in crypto cache)
    # ------------------------------------------------------------------

    def get_spread_prices(
        self,
        ticker: str,
        expiration: str,
        short_strike: float,
        long_strike: float,
        option_type: str,
        date: str,
    ) -> Optional[Dict]:
        """Return spread price info for a credit spread.

        Fetches daily close prices for both legs from crypto_option_daily.
        spread_value = short_close - long_close  (net credit received).
        slippage = 0.0 — the backtester adds configured flat slippage on top
        (no intraday bars available to estimate bid/ask half-spread).

        Args:
            ticker:       Underlying ticker.
            expiration:   Expiration date string "YYYY-MM-DD".
            short_strike: Short leg strike.
            long_strike:  Long leg strike.
            option_type:  "P" or "C".
            date:         Pricing date string "YYYY-MM-DD".

        Returns:
            Dict with keys {spread_value, short_price, long_price, slippage,
            short_symbol, long_symbol} or None if either leg is missing.
        """
        short_sym = self.build_occ_symbol(ticker, expiration, short_strike, option_type)
        long_sym = self.build_occ_symbol(ticker, expiration, long_strike, option_type)

        short_price = self.get_contract_price(short_sym, date)
        long_price = self.get_contract_price(long_sym, date)

        if short_price is None or long_price is None:
            return None

        return {
            "spread_value": short_price - long_price,
            "short_price": short_price,
            "long_price": long_price,
            "slippage": 0.0,
            "short_symbol": short_sym,
            "long_symbol": long_sym,
        }

    # ------------------------------------------------------------------
    # Intraday fallback (delegates to daily — no intraday bars in cache)
    # ------------------------------------------------------------------

    def get_intraday_spread_prices(
        self,
        ticker: str,
        expiration: str,
        short_strike: float,
        long_strike: float,
        option_type: str,
        date_str: str,
        hour: int,
        minute: int,
    ) -> Optional[Dict]:
        """Delegate to daily prices (no intraday option bars in crypto cache).

        The backtester calls this for every intraday scan time; returning daily
        prices for all scan times is equivalent to using the end-of-day close —
        conservative and consistent with a thinly-traded options market.
        """
        return self.get_spread_prices(
            ticker, expiration, short_strike, long_strike, option_type, date_str
        )

    # ------------------------------------------------------------------
    # Volume & open interest
    # ------------------------------------------------------------------

    def get_prev_daily_volume(
        self, contract_symbol: str, before_date: str
    ) -> Optional[int]:
        """Return the most recent daily volume for a contract before a date.

        Args:
            contract_symbol: OCC symbol.
            before_date:     Date string "YYYY-MM-DD" (exclusive upper bound).

        Returns:
            Volume as int, or None if not found.
        """
        row = self._conn.execute(
            "SELECT volume FROM crypto_option_daily "
            "WHERE contract_symbol = ? AND date < ? "
            "ORDER BY date DESC LIMIT 1",
            (contract_symbol, before_date),
        ).fetchone()
        if row and row["volume"] is not None:
            return int(row["volume"])
        return None

    def get_prev_daily_oi(
        self, contract_symbol: str, before_date: str
    ) -> Optional[int]:
        """Return the most recent open interest for a contract before a date.

        Args:
            contract_symbol: OCC symbol.
            before_date:     Date string "YYYY-MM-DD" (exclusive upper bound).

        Returns:
            Open interest as int, or None if not found.
        """
        row = self._conn.execute(
            "SELECT open_interest FROM crypto_option_daily "
            "WHERE contract_symbol = ? AND date < ? "
            "ORDER BY date DESC LIMIT 1",
            (contract_symbol, before_date),
        ).fetchone()
        if row and row["open_interest"] is not None:
            return int(row["open_interest"])
        return None

    # ------------------------------------------------------------------
    # Underlying prices (used by run_backtest instead of Yahoo Finance)
    # ------------------------------------------------------------------

    def get_underlying_prices(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """Return OHLCV DataFrame from crypto_underlying_daily.

        Column names match Yahoo Finance convention so the Backtester's
        price_data accessors (price_data.loc[date, 'Close']) work unchanged.

        Args:
            ticker:     Underlying ticker (e.g. "IBIT").
            start_date: Start datetime (inclusive).
            end_date:   End datetime (inclusive).

        Returns:
            DataFrame with DatetimeIndex (tz-naive) and columns
            [Open, High, Low, Close, Volume].  Returns empty DataFrame
            if no data found.
        """
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        rows = self._conn.execute(
            "SELECT date, open, high, low, close, volume "
            "FROM crypto_underlying_daily "
            "WHERE ticker = ? AND date >= ? AND date <= ? "
            "ORDER BY date ASC",
            (ticker, start_str, end_str),
        ).fetchall()

        if not rows:
            return pd.DataFrame()

        records = [
            {
                "Date": pd.Timestamp(r["date"]),
                "Open": float(r["open"]) if r["open"] is not None else float("nan"),
                "High": float(r["high"]) if r["high"] is not None else float("nan"),
                "Low": float(r["low"]) if r["low"] is not None else float("nan"),
                "Close": float(r["close"]) if r["close"] is not None else float("nan"),
                "Volume": int(r["volume"]) if r["volume"] is not None else 0,
            }
            for r in rows
        ]

        df = pd.DataFrame(records).set_index("Date")
        df.index = pd.to_datetime(df.index)
        return df

    # ------------------------------------------------------------------
    # IV series (for risk gate IV percentile check)
    # ------------------------------------------------------------------

    def get_iv_series(
        self,
        ticker: str,
        before_date: str,
        window: int = 90,
    ) -> List[float]:
        """Return historical daily IVs for the risk gate IV percentile check.

        Aggregates the average IV across all contracts for each trading date,
        then returns the last `window` values before `before_date`.

        Args:
            ticker:      Underlying ticker.
            before_date: Date string "YYYY-MM-DD" (exclusive upper bound).
            window:      Number of historical days to return (default 90).

        Returns:
            List of floats (IV values, annualised) ordered oldest→newest.
            Empty list if insufficient data.
        """
        rows = self._conn.execute(
            "SELECT d.date, AVG(d.iv) AS avg_iv "
            "FROM crypto_option_daily d "
            "JOIN crypto_option_contracts c ON d.contract_symbol = c.contract_symbol "
            "WHERE c.ticker = ? AND d.date < ? AND d.iv IS NOT NULL AND d.iv > 0 "
            "GROUP BY d.date "
            "ORDER BY d.date DESC "
            "LIMIT ?",
            (ticker, before_date, window),
        ).fetchall()

        # Return oldest-first (reversed) so caller can use as historical series.
        return [float(r["avg_iv"]) for r in reversed(rows)]

    # ------------------------------------------------------------------
    # Resource cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
