"""
Notifier — dispatches critical events to the log and optionally to Telegram.

Every significant system event (stop-loss, assignment, circuit breaker, orphan,
rate limit, etc.) should flow through this module so there is one consistent
place to add/remove notification channels.

Usage::

    notifier = Notifier(config)
    notifier.critical("Stop-loss triggered on trade cs-abc123")
    notifier.warning("Partial fill detected — 2 of 3 contracts filled")
    notifier.info("Daily report ready")

Priority levels:
  critical — immediate human action required (stop-loss, assignment, CB, outage)
  warning  — attention needed within 1 hour (partial fill, 429, stale close, etc.)
  info     — informational (daily report, fills, position opened/closed)
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class Notifier:
    """Thin wrapper that logs events and optionally forwards them to Telegram.

    Telegram integration is optional: if no valid bot_token is configured,
    the notifier degrades gracefully to logging only.
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Args:
            config: Full application config dict. Reads alerts.telegram section.
                    If None or Telegram is not configured, logging-only mode.
        """
        self._telegram_bot = None
        config = config or {}
        telegram_cfg = config.get("alerts", {}).get("telegram", {})
        if (
            telegram_cfg.get("enabled")
            and telegram_cfg.get("bot_token") not in (None, "", "YOUR_BOT_TOKEN_HERE")
        ):
            try:
                from alerts.telegram_bot import TelegramBot
                self._telegram_bot = TelegramBot(config)
                logger.info("Notifier: Telegram alerts enabled")
            except Exception as e:
                logger.warning("Notifier: failed to initialise Telegram bot: %s", e)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def critical(self, msg: str) -> None:
        """Log + send a CRITICAL alert (immediate human action required)."""
        logger.critical("ALERT CRITICAL: %s", msg)
        self._send(f"[CRITICAL] {msg}")

    def warning(self, msg: str) -> None:
        """Log + send a WARNING alert (attention needed within 1 hour)."""
        logger.warning("ALERT WARNING: %s", msg)
        self._send(f"[WARNING] {msg}")

    def info(self, msg: str) -> None:
        """Log + send an INFO notification (informational)."""
        logger.info("ALERT INFO: %s", msg)
        self._send(f"[INFO] {msg}")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, text: str) -> None:
        if self._telegram_bot is None:
            return
        try:
            self._telegram_bot.send_alert(text)
        except Exception as e:
            logger.warning("Notifier: Telegram send failed: %s", e)
