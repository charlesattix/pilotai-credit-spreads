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
import time
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

_BOT_TOKEN: Optional[str] = os.environ.get("TELEGRAM_BOT_TOKEN")
_CHAT_ID: Optional[str] = os.environ.get("TELEGRAM_CHAT_ID")
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_EXPERIMENT_ID: Optional[str] = os.environ.get("EXPERIMENT_ID")

_warned_not_configured = False

_last_api_failure_alert_time: float = 0.0
_API_FAILURE_ALERT_COOLDOWN_SECS = 300  # 5 minutes


def set_experiment_id(experiment_id: str) -> None:
    """Set the experiment ID prefix for all outgoing messages."""
    global _EXPERIMENT_ID
    _EXPERIMENT_ID = experiment_id or None


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

    if _EXPERIMENT_ID:
        text = f"[{_EXPERIMENT_ID}] {text}"

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
    """Send a Telegram alert for a new trade entry.

    Handles credit spreads, iron condors, and straddles/strangles.
    """
    spread_type = str(trade.get("type", trade.get("strategy_type", ""))).lower()

    # Straddle/strangle: use dedicated formatter
    if "straddle" in spread_type or "strangle" in spread_type:
        try:
            from alerts.formatters.telegram import TelegramAlertFormatter
            msg = TelegramAlertFormatter().format_straddle_open(trade)
            return send_message(msg)
        except Exception as e:
            logger.error("Straddle open notification failed: %s", e)
            return False

    # Credit spread / iron condor: existing format
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
    spread = trade.get("type", trade.get("strategy_type", "spread")).replace("_", " ").title()

    reason_map = {
        "profit_target": "Profit Target Hit",
        "stop_loss": "Stop Loss Hit",
        "expiration": "Expiration",
        "expiration_today": "Expiring Today",
        "management_dte": "DTE Management",
        "dte_management": "DTE Management",
        "closed_external": "Closed Externally",
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


# ── Pre-event warning ─────────────────────────────────────────────────────


def notify_upcoming_events(days_ahead: int = 2) -> bool:
    """Check economic calendar and send a heads-up about upcoming events.

    Intended to be called during the pre_market slot.
    Returns True if an alert was sent, False otherwise.
    """
    try:
        from shared.economic_calendar import EconomicCalendar
        from alerts.formatters.telegram import TelegramAlertFormatter

        cal = EconomicCalendar()
        events = cal.get_upcoming_events(days_ahead=days_ahead)
        if not events:
            return False

        msg = TelegramAlertFormatter().format_event_warning(events)
        return send_message(msg)
    except Exception as e:
        logger.error("Pre-event warning notification failed: %s", e)
        return False


# ── API failure alerts ────────────────────────────────────────────────────


def notify_api_failure(
    error_msg: str,
    context: str,
    unmonitored_positions: int = 0,
) -> bool:
    """Send a rate-limited Telegram alert when an API call fails.

    Args:
        error_msg: The exception/error message string.
        context: What failed (e.g. 'get_positions', 'submit_close', 'polygon_scan').
        unmonitored_positions: Number of positions currently unmonitored due to failure.

    Returns:
        True if alert was sent, False if rate-limited or send failed.
    """
    global _last_api_failure_alert_time

    now = time.time()
    if now - _last_api_failure_alert_time < _API_FAILURE_ALERT_COOLDOWN_SECS:
        logger.debug(
            "API failure alert rate-limited (context=%s, cooldown remaining=%.0fs)",
            context,
            _API_FAILURE_ALERT_COOLDOWN_SECS - (now - _last_api_failure_alert_time),
        )
        return False

    from datetime import datetime, timezone as _tz
    timestamp = datetime.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "\U0001f6a8 <b>API FAILURE ALERT</b>",
        "",
        f"<b>Operation:</b> <code>{context}</code>",
        f"<b>Error:</b> {error_msg}",
    ]
    if unmonitored_positions > 0:
        lines.append(f"<b>Unmonitored positions:</b> {unmonitored_positions}")
    lines.append(f"<b>Time:</b> {timestamp}")

    result = send_message("\n".join(lines))
    if result:
        _last_api_failure_alert_time = now
    return result


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
