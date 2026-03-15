"""
PortfolioHeatTracker — per-ticker and portfolio-wide capital heat tracking.

"Heat" = sum of open max-loss exposure for a given ticker (or all tickers).

Used by the COMPASS portfolio sizer to prevent over-allocating a ticker's
capital budget when multiple positions are already open.

Design:
  - In-memory ledger: {ticker: {trade_id: max_loss_dollars}}
  - Optionally SQLite-backed (via init/checkpoint) for cross-restart persistence
  - All public methods are thread-safe (GIL is sufficient; dict ops are atomic)
"""

import logging
import sqlite3
from threading import Lock
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# SQLite table used for persistence across restarts (created lazily)
_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS portfolio_heat (
        ticker      TEXT NOT NULL,
        trade_id    TEXT NOT NULL,
        max_loss    REAL NOT NULL DEFAULT 0.0,
        recorded_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (ticker, trade_id)
    )
"""


class PortfolioHeatTracker:
    """Track open max-loss exposure per ticker for COMPASS portfolio sizing.

    Args:
        db_path: Optional path to SQLite file for persistence. When provided,
                 open positions are loaded on init and flushed on checkpoint().
                 Pass None (default) for purely in-memory operation.
    """

    def __init__(self, db_path: Optional[str] = None):
        # {ticker: {trade_id: max_loss_dollars}}
        self._heat: Dict[str, Dict[str, float]] = {}
        self._lock = Lock()
        self._db_path = db_path

        if db_path:
            self._init_db()
            self._load_from_db()

    # ------------------------------------------------------------------
    # Public write methods
    # ------------------------------------------------------------------

    def record_entry(self, ticker: str, trade_id: str, max_loss: float) -> None:
        """Record a new open position's max-loss exposure.

        Args:
            ticker:   Underlying symbol (e.g. "SPY", "XLE").
            trade_id: Unique trade identifier (e.g. Alpaca order ID or UUID).
            max_loss: Dollar value of maximum possible loss for this position.
        """
        if max_loss < 0:
            raise ValueError(f"max_loss must be non-negative, got {max_loss}")
        with self._lock:
            if ticker not in self._heat:
                self._heat[ticker] = {}
            self._heat[ticker][trade_id] = max_loss
            logger.debug(
                "HeatTracker.record_entry: %s trade_id=%s max_loss=$%.0f "
                "| ticker_heat=$%.0f",
                ticker, trade_id, max_loss, self._ticker_heat_unsafe(ticker),
            )
            if self._db_path:
                self._upsert_db(ticker, trade_id, max_loss)

    def record_exit(self, ticker: str, trade_id: str) -> None:
        """Remove a closed position's max-loss contribution.

        No-op if the trade_id is not tracked (idempotent).
        """
        with self._lock:
            removed = self._heat.get(ticker, {}).pop(trade_id, None)
            if removed is not None:
                logger.debug(
                    "HeatTracker.record_exit: %s trade_id=%s freed $%.0f "
                    "| ticker_heat=$%.0f",
                    ticker, trade_id, removed,
                    self._ticker_heat_unsafe(ticker),
                )
                if self._db_path:
                    self._delete_db(ticker, trade_id)

    def clear_ticker(self, ticker: str) -> None:
        """Remove all tracked positions for a ticker (e.g. end-of-day reset)."""
        with self._lock:
            cleared_count = len(self._heat.pop(ticker, {}))
            logger.info("HeatTracker.clear_ticker: %s — cleared %d positions", ticker, cleared_count)
            if self._db_path:
                self._clear_ticker_db(ticker)

    # ------------------------------------------------------------------
    # Public read methods
    # ------------------------------------------------------------------

    def get_ticker_heat(self, ticker: str) -> float:
        """Return total open max-loss dollars for ticker."""
        with self._lock:
            return self._ticker_heat_unsafe(ticker)

    def get_ticker_position_count(self, ticker: str) -> int:
        """Return number of open positions for ticker."""
        with self._lock:
            return len(self._heat.get(ticker, {}))

    def get_portfolio_heat(self) -> float:
        """Return total open max-loss dollars across all tickers."""
        with self._lock:
            return sum(
                sum(positions.values())
                for positions in self._heat.values()
            )

    def get_all_ticker_heats(self) -> Dict[str, float]:
        """Return {ticker: total_heat_dollars} for all tracked tickers."""
        with self._lock:
            return {
                ticker: sum(positions.values())
                for ticker, positions in self._heat.items()
            }

    def is_ticker_at_capacity(
        self,
        ticker: str,
        account_value: float,
        allocation_weight: float,
        heat_capacity_pct: float = 0.95,
    ) -> bool:
        """Return True if ticker has used >= heat_capacity_pct of its allocation.

        Args:
            ticker:             Symbol to check.
            account_value:      Total account value in dollars.
            allocation_weight:  Fraction of account allocated to this ticker (0–1).
            heat_capacity_pct:  How full the allocation must be to block entry.
                                Default 0.95 = block when 95% of budget is used.
        """
        if allocation_weight <= 0 or account_value <= 0:
            return False
        max_heat = account_value * allocation_weight * heat_capacity_pct
        current = self.get_ticker_heat(ticker)
        at_cap = current >= max_heat
        if at_cap:
            logger.info(
                "HeatTracker: %s AT CAPACITY — current=$%.0f max=$%.0f "
                "(alloc=%.1f%% × %.0f%% cap)",
                ticker, current, max_heat,
                allocation_weight * 100, heat_capacity_pct * 100,
            )
        return at_cap

    def log_state(self) -> None:
        """Log the current allocation state for all tracked tickers."""
        with self._lock:
            portfolio_heat = sum(
                sum(v.values()) for v in self._heat.values()
            )
            logger.info("=== PortfolioHeatTracker state — total=$%.0f ===", portfolio_heat)
            for ticker, positions in sorted(self._heat.items()):
                ticker_heat = sum(positions.values())
                logger.info(
                    "  %s: %d positions, heat=$%.0f",
                    ticker, len(positions), ticker_heat,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ticker_heat_unsafe(self, ticker: str) -> float:
        """Sum heat for ticker — caller must hold lock."""
        return sum(self._heat.get(ticker, {}).values())

    # ------------------------------------------------------------------
    # SQLite persistence (optional)
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(_CREATE_TABLE)
            conn.commit()
        finally:
            conn.close()

    def _load_from_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT ticker, trade_id, max_loss FROM portfolio_heat").fetchall()
            for row in rows:
                ticker = row["ticker"]
                if ticker not in self._heat:
                    self._heat[ticker] = {}
                self._heat[ticker][row["trade_id"]] = float(row["max_loss"])
            logger.info("HeatTracker: loaded %d positions from %s", len(rows), self._db_path)
        except sqlite3.OperationalError:
            pass  # table not yet created — fresh DB
        finally:
            conn.close()

    def _upsert_db(self, ticker: str, trade_id: str, max_loss: float) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO portfolio_heat (ticker, trade_id, max_loss) VALUES (?, ?, ?)",
                    (ticker, trade_id, max_loss),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("HeatTracker._upsert_db failed: %s", e)

    def _delete_db(self, ticker: str, trade_id: str) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "DELETE FROM portfolio_heat WHERE ticker=? AND trade_id=?",
                    (ticker, trade_id),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("HeatTracker._delete_db failed: %s", e)

    def _clear_ticker_db(self, ticker: str) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("DELETE FROM portfolio_heat WHERE ticker=?", (ticker,))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("HeatTracker._clear_ticker_db failed: %s", e)
