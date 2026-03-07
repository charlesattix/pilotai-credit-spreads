"""
Persistent live-vs-backtest deviation tracking.

Stores comparison snapshots in SQLite for trend analysis, automated daily
tracking via the scheduler, and dashboard/alerting queries.

Reuses functions from scripts/live_vs_backtest.py rather than duplicating logic.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.database import get_db, DB_PATH

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(__file__).parent.parent / "configs" / "champion.json"


def record_deviation_snapshot(
    config_path: Optional[str] = None,
    db_path: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Record a live-vs-backtest deviation snapshot to SQLite.

    Loads live trades, computes metrics, optionally runs backtest,
    compares, and persists the result. Returns the snapshot dict.

    Skips backtest if < 5 live trades (stores live-only snapshot).
    Returns None if no live trades exist.
    """
    from scripts.live_vs_backtest import (
        load_live_trades,
        compute_live_metrics,
        run_backtest_for_range,
        compare_metrics,
    )

    config = Path(config_path) if config_path else DEFAULT_CONFIG

    # Load live trades and compute metrics
    trades = load_live_trades()
    live = compute_live_metrics(trades)
    n = live.get("total_trades", 0)

    if n == 0:
        logger.info("No closed trades found — skipping deviation snapshot")
        return None

    # Determine date range
    if start is None:
        start_str = live.get("start_date")
        if start_str:
            start = datetime.strptime(str(start_str)[:10], "%Y-%m-%d")
        else:
            logger.warning("Cannot determine start date for deviation snapshot")
            return None

    if end is None:
        end_str = live.get("end_date")
        end = datetime.strptime(str(end_str)[:10], "%Y-%m-%d") if end_str else datetime.now()

    snapshot_date = datetime.now().strftime("%Y-%m-%d")

    # Run backtest if enough trades
    backtest = None
    comparisons = None
    overall_status = "INFO"

    if n >= 5 and config.exists():
        try:
            backtest = run_backtest_for_range(config, start, end)
            comparisons = compare_metrics(live, backtest)
            overall_status = _compute_overall_status(comparisons)
        except Exception as e:
            logger.error(f"Backtest failed during deviation snapshot: {e}")

    # Build snapshot dict
    bt_combined = (backtest or {}).get("combined", {}) if backtest else {}
    snapshot = {
        "snapshot_date": snapshot_date,
        "live_trades": n,
        "bt_trades": bt_combined.get("total_trades"),
        "live_win_rate": live.get("win_rate"),
        "bt_win_rate": bt_combined.get("win_rate"),
        "live_pnl": live.get("total_pnl"),
        "bt_pnl": bt_combined.get("total_pnl"),
        "live_return_pct": live.get("return_pct"),
        "bt_return_pct": bt_combined.get("return_pct"),
        "live_profit_factor": live.get("profit_factor"),
        "bt_profit_factor": bt_combined.get("profit_factor"),
        "live_max_dd": live.get("max_drawdown"),
        "bt_max_dd": bt_combined.get("max_drawdown"),
        "overall_status": overall_status,
        "details": {
            "comparisons": comparisons,
            "live_per_strategy": live.get("per_strategy"),
            "bt_per_strategy": (backtest or {}).get("per_strategy"),
            "date_range": {"start": str(start.date()), "end": str(end.date())},
        },
    }

    # Persist — upsert on snapshot_date
    _upsert_snapshot(snapshot, db_path)

    logger.info(f"Deviation snapshot recorded: {snapshot_date} — {overall_status}")
    return snapshot


def get_deviation_history(days: int = 30, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Query deviation_snapshots for the last N days, newest first."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM deviation_snapshots WHERE snapshot_date >= ? ORDER BY snapshot_date DESC",
            (cutoff,),
        ).fetchall()
        return [_row_to_snapshot(r) for r in rows]
    finally:
        conn.close()


def get_latest_deviation(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the most recent deviation snapshot, or None."""
    conn = get_db(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM deviation_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
        return _row_to_snapshot(row) if row else None
    finally:
        conn.close()


def check_deviation_alerts(snapshot: Dict[str, Any]) -> List[str]:
    """Examine a snapshot for WARN/FAIL metrics. Returns human-readable alert strings."""
    alerts: List[str] = []
    if not snapshot:
        return alerts

    details = snapshot.get("details") or {}
    comparisons = details.get("comparisons") or []

    for c in comparisons:
        status = c.get("status", "INFO")
        if status in ("WARN", "FAIL"):
            metric = c.get("metric", "Unknown")
            live_str = c.get("live_str", "?")
            bt_str = c.get("backtest_str", "?")
            alerts.append(f"{metric} deviation: live {live_str} vs backtest {bt_str} ({status})")

    return alerts


# ── Internal helpers ────────────────────────────────────────────────────────


def _compute_overall_status(comparisons: List[Dict[str, Any]]) -> str:
    """Derive overall status from the worst individual metric status."""
    statuses = {c.get("status", "INFO") for c in comparisons}
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    if "PASS" in statuses:
        return "PASS"
    return "INFO"


def _upsert_snapshot(snapshot: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """Insert or replace a deviation snapshot (one per day)."""
    conn = get_db(db_path)
    try:
        conn.execute(
            """
            INSERT INTO deviation_snapshots
                (snapshot_date, live_trades, bt_trades, live_win_rate, bt_win_rate,
                 live_pnl, bt_pnl, live_return_pct, bt_return_pct,
                 live_profit_factor, bt_profit_factor, live_max_dd, bt_max_dd,
                 overall_status, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                live_trades=excluded.live_trades,
                bt_trades=excluded.bt_trades,
                live_win_rate=excluded.live_win_rate,
                bt_win_rate=excluded.bt_win_rate,
                live_pnl=excluded.live_pnl,
                bt_pnl=excluded.bt_pnl,
                live_return_pct=excluded.live_return_pct,
                bt_return_pct=excluded.bt_return_pct,
                live_profit_factor=excluded.live_profit_factor,
                bt_profit_factor=excluded.bt_profit_factor,
                live_max_dd=excluded.live_max_dd,
                bt_max_dd=excluded.bt_max_dd,
                overall_status=excluded.overall_status,
                details=excluded.details,
                created_at=datetime('now')
            """,
            (
                snapshot["snapshot_date"],
                snapshot.get("live_trades"),
                snapshot.get("bt_trades"),
                snapshot.get("live_win_rate"),
                snapshot.get("bt_win_rate"),
                snapshot.get("live_pnl"),
                snapshot.get("bt_pnl"),
                snapshot.get("live_return_pct"),
                snapshot.get("bt_return_pct"),
                snapshot.get("live_profit_factor"),
                snapshot.get("bt_profit_factor"),
                snapshot.get("live_max_dd"),
                snapshot.get("bt_max_dd"),
                snapshot.get("overall_status"),
                json.dumps(snapshot.get("details"), default=str),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_snapshot(row) -> Dict[str, Any]:
    """Convert a database row to a snapshot dict."""
    d = dict(row)
    if d.get("details"):
        try:
            d["details"] = json.loads(d["details"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d
