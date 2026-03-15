"""
Daily summary report utilities.

Builds the metrics dict consumed by TelegramAlertFormatter.format_daily_summary()
and shared/daily_report.py for the scheduled end-of-day report.

Imported lazily by shared/telegram_alerts.py.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def get_daily_summary_metrics(
    report_date: Optional[str] = None,
    account_size: float = 100_000.0,
) -> dict:
    """Collect today's summary metrics from SQLite and Alpaca.

    Returns a dict matching the kwargs expected by
    TelegramAlertFormatter.format_daily_summary().

    Keys:
        date, alerts_fired, closed_today, wins, losses, day_pnl,
        day_pnl_pct, open_positions, total_risk_pct, account_balance,
        pct_from_start, best, worst.
    """
    from shared.database import get_trades, get_latest_alerts

    date_str = report_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Closed trades today
    db_path = os.environ.get("PILOTAI_DB_PATH")
    closed_all = (
        get_trades(status="closed_profit", path=db_path) +
        get_trades(status="closed_loss", path=db_path)
    )
    closed_today = [
        t for t in closed_all
        if str(t.get("exit_date", "")).startswith(date_str)
    ]
    wins = [t for t in closed_today if (t.get("pnl") or 0) > 0]
    losses = [t for t in closed_today if (t.get("pnl") or 0) <= 0]
    day_pnl = sum(t.get("pnl", 0) for t in closed_today)
    day_pnl_pct = (day_pnl / account_size * 100) if account_size > 0 else 0.0

    # Open positions
    open_trades = get_trades(status="open", path=db_path)

    # Alerts fired today
    alerts = get_latest_alerts(limit=100, path=db_path)
    alerts_today = [a for a in alerts if str(a.get("created_at", "")).startswith(date_str)]

    # Best / worst trade
    best = ""
    worst = ""
    if closed_today:
        sorted_by_pnl = sorted(closed_today, key=lambda t: t.get("pnl", 0), reverse=True)
        b = sorted_by_pnl[0]
        w = sorted_by_pnl[-1]
        best = f"{b.get('ticker', 'UNK')} {'+' if (b.get('pnl') or 0) >= 0 else ''}${b.get('pnl', 0):.2f}"
        worst = f"{w.get('ticker', 'UNK')} {'+' if (w.get('pnl') or 0) >= 0 else ''}${w.get('pnl', 0):.2f}"

    return {
        "date": date_str,
        "alerts_fired": len(alerts_today),
        "closed_today": len(closed_today),
        "wins": len(wins),
        "losses": len(losses),
        "day_pnl": round(day_pnl, 2),
        "day_pnl_pct": round(day_pnl_pct, 4),
        "open_positions": len(open_trades),
        "total_risk_pct": 0.0,
        "account_balance": account_size + day_pnl,
        "pct_from_start": round(day_pnl_pct, 4),
        "best": best,
        "worst": worst,
    }
