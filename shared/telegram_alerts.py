"""
Standalone Telegram notification module for paper trading alerts.

Uses raw HTTP via ``requests`` to POST to the Telegram Bot API —
no ``python-telegram-bot`` dependency required.

Credentials are read from environment variables:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID

When credentials are missing the module degrades gracefully (logs a
warning on the first call, never crashes).
"""

import logging
import os
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

_BOT_TOKEN: Optional[str] = os.environ.get("TELEGRAM_BOT_TOKEN")
_CHAT_ID: Optional[str] = os.environ.get("TELEGRAM_CHAT_ID")
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

_warned_not_configured = False


def is_configured() -> bool:
    """Return True if both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""
    return bool(_BOT_TOKEN) and bool(_CHAT_ID)


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message via the Telegram Bot API.

    Returns True on success, False on failure.  Never raises.
    """
    global _warned_not_configured

    if not is_configured():
        if not _warned_not_configured:
            logger.warning(
                "Telegram alerts not configured — set TELEGRAM_BOT_TOKEN "
                "and TELEGRAM_CHAT_ID environment variables"
            )
            _warned_not_configured = True
        return False

    try:
        resp = requests.post(
            _TELEGRAM_API.format(token=_BOT_TOKEN),
            json={"chat_id": _CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False


# ── Trade alerts ───────────────────────────────────────────────────────────


def notify_trade_open(trade: dict) -> bool:
    """Send a Telegram alert for a new trade entry."""
    dte = trade.get("dte_at_entry", "?")
    spread = trade.get("type", "spread").replace("_", " ").title()
    lines = [
        f"\U0001f7e2 <b>NEW TRADE: {trade.get('ticker', '?')} {spread}</b>",
        "",
        f"Strikes: ${trade.get('short_strike', '?')}/{trade.get('long_strike', '?')}",
        f"Contracts: {trade.get('contracts', '?')}",
        f"Credit: ${trade.get('total_credit', 0):.2f}",
        f"Max Loss: ${trade.get('total_max_loss', 0):.2f}",
        f"DTE: {dte}",
    ]
    return send_message("\n".join(lines))


def notify_trade_close(
    trade: dict, pnl: float, reason: str, balance: float
) -> bool:
    """Send a Telegram alert for a trade exit."""
    emoji = "\U0001f4c8" if pnl >= 0 else "\U0001f4c9"
    sign = "+" if pnl >= 0 else "-"
    ticker = trade.get("ticker", "?")
    spread = trade.get("type", "spread").replace("_", " ").title()

    reason_map = {
        "profit_target": "Profit Target Hit",
        "stop_loss": "Stop Loss Hit",
        "expiration": "Expiration",
        "management_dte": "DTE Management",
    }
    reason_display = reason_map.get(reason, reason)

    lines = [
        f"{emoji} <b>CLOSED: {ticker} {spread}</b>",
        "",
        f"P&L: {sign}${abs(pnl):.2f}",
        f"Reason: {reason_display}",
        f"Balance: ${balance:,.2f}",
    ]
    return send_message("\n".join(lines))


# ── Daily summary ─────────────────────────────────────────────────────────


def notify_daily_summary(
    report_date: str = None, account_size: float = 100_000
) -> bool:
    """Build and send the daily summary via the existing formatter."""
    try:
        from scripts.daily_report import get_daily_summary_metrics
        from alerts.formatters.telegram import TelegramAlertFormatter

        metrics = get_daily_summary_metrics(
            report_date=report_date, account_size=account_size
        )
        msg = TelegramAlertFormatter().format_daily_summary(**metrics)
        return send_message(msg)
    except Exception as e:
        logger.error("Daily summary notification failed: %s", e)
        return False


# ── Deviation alerts ──────────────────────────────────────────────────────


def notify_deviation_alerts(snapshot: dict) -> bool:
    """Send deviation alerts if any WARN/FAIL metrics exist in *snapshot*."""
    try:
        from shared.deviation_tracker import check_deviation_alerts

        alerts: List[str] = check_deviation_alerts(snapshot)
        if not alerts:
            return False

        header = "\u26a0\ufe0f <b>DEVIATION ALERTS</b>\n"
        body = "\n".join(f"• {a}" for a in alerts)
        return send_message(header + body)
    except Exception as e:
        logger.error("Deviation alert notification failed: %s", e)
        return False
