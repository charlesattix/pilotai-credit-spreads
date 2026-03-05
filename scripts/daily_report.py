#!/usr/bin/env python3
"""
Daily P&L Report — Paper Trading
Generates a formatted daily summary from SQLite trade data.

Usage:
    python scripts/daily_report.py              # Today's report
    python scripts/daily_report.py --date 2026-03-05  # Specific date
"""

import argparse
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# Allow running from project root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from shared.database import get_trades, init_db


def generate_daily_report(report_date: str = None) -> str:
    """Generate a daily P&L report string.

    Args:
        report_date: Date string 'YYYY-MM-DD'. Defaults to today (UTC).

    Returns:
        Formatted report string.
    """
    if report_date is None:
        report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    init_db()

    # Load all paper trader trades
    all_trades = get_trades(source="scanner")

    # Separate open vs closed
    open_trades = [t for t in all_trades if t.get("status") == "open"]
    closed_trades = [t for t in all_trades if t.get("status") != "open"]

    # Today's closed trades (exit_date matches report_date)
    today_closed = [
        t for t in closed_trades
        if (t.get("exit_date") or "")[:10] == report_date
    ]

    # Today's opened trades (entry_date matches report_date)
    today_opened = [
        t for t in all_trades
        if (t.get("entry_date") or "")[:10] == report_date
    ]

    # Calculate P&L
    today_pnl = sum(t.get("pnl") or 0 for t in today_closed)
    total_pnl = sum(t.get("pnl") or 0 for t in closed_trades)
    winners = [t for t in closed_trades if (t.get("pnl") or 0) > 0]
    losers = [t for t in closed_trades if (t.get("pnl") or 0) <= 0]
    win_rate = (len(winners) / len(closed_trades) * 100) if closed_trades else 0

    # Open position exposure
    open_exposure = 0
    for t in open_trades:
        contracts = t.get("contracts", 1)
        short = t.get("short_strike") or 0
        long = t.get("long_strike") or 0
        width = abs(short - long)
        credit = t.get("credit") or 0
        max_loss = (width - credit) * contracts * 100
        open_exposure += max_loss

    # Build report
    pnl_emoji = "+" if today_pnl >= 0 else ""
    total_emoji = "+" if total_pnl >= 0 else ""

    lines = []
    lines.append("=" * 60)
    lines.append(f"  DAILY P&L REPORT — {report_date}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("  TODAY'S ACTIVITY")
    lines.append(f"    Trades Opened:  {len(today_opened):>6}")
    lines.append(f"    Trades Closed:  {len(today_closed):>6}")
    lines.append(f"    Day P&L:        ${today_pnl:>+10,.2f}")
    lines.append("")

    if today_closed:
        lines.append("  CLOSED TODAY:")
        for t in today_closed:
            pnl = t.get("pnl") or 0
            lines.append(
                f"    {t.get('ticker', '???'):>5} {t.get('strategy_type', ''):>15} "
                f"${t.get('short_strike', 0)}/{t.get('long_strike', 0)} "
                f"x{t.get('contracts', 1)} | {t.get('exit_reason', ''):>12} | "
                f"P&L: ${pnl:>+8,.2f}"
            )
        lines.append("")

    lines.append("  CUMULATIVE")
    lines.append(f"    Total Trades:   {len(closed_trades):>6}")
    lines.append(f"    Win Rate:       {win_rate:>5.1f}%")
    lines.append(f"    Winners/Losers: {len(winners):>4} / {len(losers)}")
    lines.append(f"    Total P&L:      ${total_pnl:>+10,.2f}")
    lines.append("")

    lines.append(f"  OPEN POSITIONS ({len(open_trades)})")
    if open_trades:
        for t in open_trades:
            entry = (t.get("entry_date") or "")[:10]
            lines.append(
                f"    {t.get('ticker', '???'):>5} {t.get('strategy_type', ''):>15} "
                f"${t.get('short_strike', 0)}/{t.get('long_strike', 0)} "
                f"x{t.get('contracts', 1)} | Entered: {entry} | "
                f"Exp: {(t.get('expiration') or '')[:10]}"
            )
        lines.append(f"    Total Exposure: ${open_exposure:>10,.2f}")
    else:
        lines.append("    (none)")
    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Daily P&L Report")
    parser.add_argument(
        "--date",
        default=None,
        help="Report date (YYYY-MM-DD). Defaults to today.",
    )
    args = parser.parse_args()
    report = generate_daily_report(report_date=args.date)
    print(report)


if __name__ == "__main__":
    main()
