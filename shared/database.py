"""
Shared SQLite database module for PilotAI.
Single source of truth for trades, alerts, and regime snapshots.
Uses WAL mode for concurrent read access from Python and Node.js.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.constants import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = Path(DATA_DIR) / "pilotai.db"


def get_db(path: Optional[str] = None) -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode enabled."""
    db_path = Path(path) if path else DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Optional[str] = None) -> None:
    """Create tables if they don't exist."""
    conn = get_db(path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                ticker TEXT NOT NULL,
                strategy_type TEXT,
                status TEXT DEFAULT 'open',
                short_strike REAL,
                long_strike REAL,
                expiration TEXT,
                credit REAL,
                contracts INTEGER DEFAULT 1,
                entry_date TEXT,
                exit_date TEXT,
                exit_reason TEXT,
                pnl REAL,
                metadata JSON,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                data JSON NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS regime_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regime TEXT,
                confidence REAL,
                features JSON,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS reconciliation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details JSON,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()

        # Safe column migrations — ADD IF NOT EXISTS (try/except for older SQLite)
        for migration_sql in [
            "ALTER TABLE trades ADD COLUMN alpaca_client_order_id TEXT",
            "ALTER TABLE trades ADD COLUMN alpaca_fill_price REAL",
        ]:
            try:
                conn.execute(migration_sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists

        logger.info(f"Database initialized at {path or DB_PATH}")
    finally:
        conn.close()


def upsert_trade(trade: Dict[str, Any], source: str = "scanner", path: Optional[str] = None) -> None:
    """Insert or update a trade."""
    conn = get_db(path)
    try:
        metadata = {k: v for k, v in trade.items() if k not in (
            "id", "ticker", "type", "strategy_type", "status",
            "short_strike", "long_strike", "expiration", "credit",
            "contracts", "entry_date", "exit_date", "exit_reason", "pnl",
        )}
        conn.execute("""
            INSERT INTO trades (id, source, ticker, strategy_type, status,
                short_strike, long_strike, expiration, credit, contracts,
                entry_date, exit_date, exit_reason, pnl, metadata, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                exit_date=excluded.exit_date,
                exit_reason=excluded.exit_reason,
                pnl=excluded.pnl,
                metadata=excluded.metadata,
                updated_at=datetime('now')
        """, (
            str(trade.get("id", "")),
            source,
            trade.get("ticker", ""),
            trade.get("type") or trade.get("strategy_type", ""),
            trade.get("status", "open"),
            trade.get("short_strike"),
            trade.get("long_strike"),
            str(trade.get("expiration", "")),
            trade.get("credit") or trade.get("credit_per_spread"),
            trade.get("contracts", 1),
            trade.get("entry_date"),
            trade.get("exit_date"),
            trade.get("exit_reason"),
            trade.get("exit_pnl") or trade.get("pnl"),
            json.dumps(metadata, default=str),
        ))
        conn.commit()
    finally:
        conn.close()


def get_trades(
    status: Optional[str] = None,
    source: Optional[str] = None,
    path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch trades with optional filters."""
    conn = get_db(path)
    try:
        query = "SELECT * FROM trades WHERE 1=1"
        params: List[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [_row_to_trade(r) for r in rows]
    finally:
        conn.close()


def close_trade(
    trade_id: str,
    pnl: float,
    reason: str,
    path: Optional[str] = None,
) -> None:
    """Close a trade by setting status, exit_date, pnl, and exit_reason."""
    conn = get_db(path)
    try:
        status = "closed_profit" if pnl > 0 else "closed_loss" if pnl < 0 else "closed_expiry"
        if reason == "manual":
            status = "closed_manual"
        conn.execute("""
            UPDATE trades SET status=?, exit_date=?, exit_reason=?, pnl=?, updated_at=datetime('now')
            WHERE id=?
        """, (status, datetime.now(timezone.utc).isoformat(), reason, pnl, trade_id))
        conn.commit()
    finally:
        conn.close()


def insert_alert(alert: Dict[str, Any], path: Optional[str] = None) -> None:
    """Insert an alert."""
    conn = get_db(path)
    try:
        alert_id = f"alert-{alert.get('ticker', 'UNK')}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        conn.execute(
            "INSERT OR REPLACE INTO alerts (id, ticker, data) VALUES (?, ?, ?)",
            (alert_id, alert.get("ticker", ""), json.dumps(alert, default=str)),
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_alerts(limit: int = 50, path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get the most recent alerts."""
    conn = get_db(path)
    try:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {**json.loads(r["data"]), "id": r["id"], "created_at": r["created_at"]}
            for r in rows
        ]
    finally:
        conn.close()


def insert_regime_snapshot(
    regime: str,
    confidence: float,
    features: Optional[Dict] = None,
    path: Optional[str] = None,
) -> None:
    """Insert a regime detection snapshot."""
    conn = get_db(path)
    try:
        conn.execute(
            "INSERT INTO regime_snapshots (regime, confidence, features) VALUES (?, ?, ?)",
            (regime, confidence, json.dumps(features or {}, default=str)),
        )
        conn.commit()
    finally:
        conn.close()


def insert_reconciliation_event(
    trade_id: str,
    event_type: str,
    details: Optional[Dict] = None,
    path: Optional[str] = None,
) -> None:
    """Append an audit entry to the reconciliation_events table."""
    conn = get_db(path)
    try:
        conn.execute(
            "INSERT INTO reconciliation_events (trade_id, event_type, details) VALUES (?, ?, ?)",
            (trade_id, event_type, json.dumps(details or {}, default=str)),
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_trade(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a database row to a trade dict, merging metadata."""
    d = dict(row)
    metadata = {}
    if d.get("metadata"):
        try:
            metadata = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
    d.pop("metadata", None)
    return {**d, **metadata}
