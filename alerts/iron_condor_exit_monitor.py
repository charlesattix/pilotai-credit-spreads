"""
Iron condor exit alert monitor.

Watches paper-traded iron condor positions and fires Telegram alerts when:
1. Profit target hit (50% of credit received)
2. Stop loss hit (2x credit)
3. Weekly close approaching (Thursday warning, Friday force close)
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

from alerts.iron_condor_config import CLOSE_DAYS

logger = logging.getLogger(__name__)

# Exit thresholds for iron condor positions
_PROFIT_TARGET_PCT = 0.50   # 50% of credit received (req 3.4)
_STOP_LOSS_MULT = 2.0       # 2x credit


def _now_et(now_et: Optional[datetime] = None) -> datetime:
    """Return *now_et* or the current time in US/Eastern."""
    if now_et is not None:
        if now_et.tzinfo is not None:
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo
            return now_et.astimezone(ZoneInfo("America/New_York"))
        return now_et

    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York"))


class IronCondorExitMonitor:
    """Monitor iron condor paper-trade positions and fire exit alerts.

    Integrates with ``PaperTrader`` for position data and
    ``TelegramBot`` / ``TelegramAlertFormatter`` for notifications.

    Uses composite dedup keys (``trade_id:reason``) so a position can
    receive both a Thursday warning AND a Friday force-close alert.
    """

    def __init__(self, paper_trader, telegram_bot, formatter=None):
        self._paper_trader = paper_trader
        self._telegram_bot = telegram_bot

        if formatter is None:
            from alerts.formatters.telegram import TelegramAlertFormatter
            formatter = TelegramAlertFormatter()
        self._formatter = formatter

        # Composite dedup: "trade_id:reason" → already alerted
        self._alerted: Set[str] = set()

    def check_and_alert(
        self,
        current_prices: Dict[str, float],
        now_et: Optional[datetime] = None,
    ) -> List[Dict]:
        """Check open iron condor positions against exit thresholds.

        Args:
            current_prices: Mapping of ticker -> current price.
            now_et: Optional ET datetime for testing.

        Returns:
            List of dicts describing triggered exit alerts.
        """
        triggered: List[Dict] = []
        et_now = _now_et(now_et)
        weekday = et_now.weekday()

        for trade in self._paper_trader.open_trades:
            # Only monitor iron condor positions
            strategy_type = (
                trade.get("strategy_type")
                or trade.get("type", "")
            )
            if "condor" not in strategy_type:
                continue

            trade_id = trade.get("id", "")
            if not trade_id:
                continue

            ticker = trade.get("ticker", "")
            price = current_prices.get(ticker)
            if price is None:
                continue

            total_credit = trade.get("total_credit", 0)
            if total_credit <= 0:
                continue

            # Evaluate P&L via paper trader
            pnl, _close_reason = self._paper_trader._evaluate_position(
                trade, price, dte=0
            )

            # --- 1. Profit target: P&L >= 50% of credit ---
            profit_key = f"{trade_id}:profit_target"
            if profit_key not in self._alerted and pnl >= total_credit * _PROFIT_TARGET_PCT:
                self._fire_exit_alert(
                    trade, ticker, pnl, total_credit,
                    reason="profit_target",
                    action="CLOSE — Profit Target (50%)",
                    instructions="Take profits on iron condor. Close all four legs.",
                )
                self._alerted.add(profit_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "profit_target",
                    "pnl": pnl,
                })

            # --- 2. Stop loss: P&L <= -(2x credit) ---
            stop_key = f"{trade_id}:stop_loss"
            if stop_key not in self._alerted and pnl <= -(total_credit * _STOP_LOSS_MULT):
                self._fire_exit_alert(
                    trade, ticker, pnl, total_credit,
                    reason="stop_loss",
                    action="CLOSE — Stop Loss (2x credit)",
                    instructions="Cut losses on iron condor. Close all four legs immediately.",
                )
                self._alerted.add(stop_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "stop_loss",
                    "pnl": pnl,
                })

            # --- 3. Weekly close alerts (req 3.6) ---
            # Thursday (weekday=3): "plan to close" warning
            if weekday == 3:
                warn_key = f"{trade_id}:weekly_close_warning"
                if warn_key not in self._alerted:
                    self._fire_exit_alert(
                        trade, ticker, pnl, total_credit,
                        reason="weekly_close_warning",
                        action="PLAN TO CLOSE — Thursday Warning",
                        instructions=(
                            "Iron condor approaching weekly expiration. "
                            "Plan to close by end of day Friday."
                        ),
                    )
                    self._alerted.add(warn_key)
                    triggered.append({
                        "trade_id": trade_id,
                        "ticker": ticker,
                        "reason": "weekly_close_warning",
                        "pnl": pnl,
                    })

            # Friday (weekday=4): "close now" force close
            if weekday == 4:
                close_key = f"{trade_id}:weekly_close_now"
                if close_key not in self._alerted:
                    self._fire_exit_alert(
                        trade, ticker, pnl, total_credit,
                        reason="weekly_close_now",
                        action="CLOSE NOW — Friday Expiration",
                        instructions=(
                            "Iron condor at weekly expiration. "
                            "Close all four legs immediately to avoid assignment risk."
                        ),
                    )
                    self._alerted.add(close_key)
                    triggered.append({
                        "trade_id": trade_id,
                        "ticker": ticker,
                        "reason": "weekly_close_now",
                        "pnl": pnl,
                    })

        return triggered

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fire_exit_alert(
        self,
        trade: Dict,
        ticker: str,
        pnl: float,
        total_credit: float,
        reason: str,
        action: str,
        instructions: str,
    ) -> None:
        """Format and send an exit alert via Telegram."""
        pnl_pct = (pnl / total_credit * 100) if total_credit else 0.0
        msg = self._formatter.format_exit_alert(
            ticker=ticker,
            action=action,
            current_pnl=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
            instructions=instructions,
        )
        try:
            self._telegram_bot.send_alert(msg)
        except Exception as e:
            logger.error(f"Failed to send iron condor exit alert for {ticker}: {e}")
