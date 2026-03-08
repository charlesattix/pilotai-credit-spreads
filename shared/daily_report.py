"""
Daily P&L report generator for the credit spread system.

Usage::

    from shared.daily_report import generate_daily_report

    report = generate_daily_report()       # today
    report = generate_daily_report(db_path="data/trades.db")

The report is a plain-text string suitable for printing, logging, or Telegram.
"""

import logging
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def generate_daily_report(
    db_path: Optional[str] = None,
    report_date: Optional[date] = None,
) -> str:
    """Generate a text daily trading report from the SQLite database.

    Args:
        db_path: Optional path to the SQLite database. Uses default if None.
        report_date: Date to report on. Defaults to today (UTC).

    Returns:
        Multi-line string report.
    """
    from shared.database import get_trades

    today = report_date or datetime.now(timezone.utc).date()
    today_str = today.isoformat()

    try:
        all_trades = get_trades(path=db_path)
    except Exception as e:
        logger.error("daily_report: failed to load trades: %s", e)
        return f"=== DAILY REPORT — {today_str} ===\n[ERROR: could not load trades: {e}]\n"

    open_trades: List[Dict] = [t for t in all_trades if t.get("status") == "open"]
    pending_trades: List[Dict] = [
        t for t in all_trades if t.get("status") in ("pending_open", "pending_close")
    ]

    # Trades opened today (entry_date starts with today_str)
    opened_today: List[Dict] = [
        t for t in all_trades if str(t.get("entry_date", "")).startswith(today_str)
    ]

    # Closed statuses set by close_trade(): closed_profit, closed_loss, closed_expiry, closed_manual
    _CLOSED_STATUSES = frozenset({"closed", "closed_profit", "closed_loss", "closed_expiry", "closed_manual"})

    # Trades closed today
    closed_today: List[Dict] = [
        t for t in all_trades
        if str(t.get("exit_date", "")).startswith(today_str)
        and t.get("status") in _CLOSED_STATUSES
    ]

    # P&L
    realized_today = sum(float(t.get("pnl") or 0) for t in closed_today)
    realized_total = sum(
        float(t.get("pnl") or 0) for t in all_trades if t.get("status") in _CLOSED_STATUSES
    )

    lines = [
        f"=== DAILY TRADING REPORT — {today_str} ===",
        "",
        "POSITIONS",
        f"  Open:    {len(open_trades)}",
        f"  Pending: {len(pending_trades)}",
        "",
        "TODAY'S ACTIVITY",
        f"  Opened:  {len(opened_today)}",
        f"  Closed:  {len(closed_today)}",
    ]

    for t in closed_today:
        pnl_val = float(t.get("pnl") or 0)
        reason = t.get("exit_reason", "?")
        ticker = t.get("ticker", "?")
        trade_id = str(t.get("id", "?"))[:12]
        lines.append(
            f"    - {trade_id} | {ticker} | {reason} | P&L ${pnl_val:+.2f}"
        )

    lines += [
        "",
        "P&L SUMMARY",
        f"  Today Realized:  ${realized_today:+.2f}",
        f"  Total Realized:  ${realized_total:+.2f}",
        "",
        "OPEN POSITIONS",
    ]

    if open_trades:
        for t in open_trades:
            credit = float(t.get("credit") or 0)
            ticker = t.get("ticker", "?")
            exp = str(t.get("expiration", ""))[:10]
            spread_type = t.get("strategy_type", t.get("type", "?"))
            contracts = t.get("contracts", 1)
            trade_id = str(t.get("id", "?"))[:12]
            lines.append(
                f"  {trade_id} | {ticker} | {spread_type} | "
                f"x{contracts} | credit={credit:.2f} | exp={exp}"
            )
    else:
        lines.append("  (none)")

    # Risk summary
    total_max_loss = 0.0
    for t in open_trades:
        credit = float(t.get("credit") or 0)
        contracts = int(t.get("contracts") or 1)
        # Approximate max loss: assumes $5 wide spread
        spread_width = 5.0
        max_loss = (spread_width - credit) * contracts * 100
        total_max_loss += max_loss

    lines += [
        "",
        "RISK",
        f"  Max Aggregate Loss: ${total_max_loss:,.2f} (estimated, assuming $5 spreads)",
        "",
    ]

    return "\n".join(lines)
