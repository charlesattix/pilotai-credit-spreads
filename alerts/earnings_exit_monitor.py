"""
Earnings play exit alert monitor.

Watches paper-traded earnings iron condor positions and fires Telegram alerts:
1. Post-earnings close — close morning after earnings to capture IV crush (req 5.5)
2. 50% profit — P&L >= 50% of credit received
3. 2x stop loss — P&L <= -(2x credit)
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Exit thresholds for earnings condor positions
_PROFIT_TARGET_PCT = 0.50   # 50% of credit received (req 5.4)
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


def _is_post_earnings(trade: Dict, now_et: datetime) -> bool:
    """Check if earnings have already passed for this trade.

    Reads ``earnings_date`` from trade metadata and compares to current time.
    """
    earnings_str = trade.get("earnings_date", "")
    if not earnings_str:
        return False

    try:
        from datetime import timezone as tz
        if isinstance(earnings_str, str):
            earnings_dt = datetime.fromisoformat(earnings_str)
        elif isinstance(earnings_str, datetime):
            earnings_dt = earnings_str
        else:
            return False

        # Normalize to UTC for comparison
        if earnings_dt.tzinfo is None:
            earnings_dt = earnings_dt.replace(tzinfo=tz.utc)
        if now_et.tzinfo is None:
            now_compare = now_et.replace(tzinfo=tz.utc)
        else:
            now_compare = now_et

        return now_compare > earnings_dt
    except Exception:
        return False


class EarningsExitMonitor:
    """Monitor earnings iron condor positions and fire exit alerts.

    Integrates with ``PaperTrader`` for position data and
    ``TelegramBot`` / ``TelegramAlertFormatter`` for notifications.

    Uses composite dedup keys (``trade_id:reason``) so a position can
    receive multiple distinct alerts (e.g., post-earnings + profit target).
    """

    def __init__(self, paper_trader, telegram_bot, formatter=None):
        self._paper_trader = paper_trader
        self._telegram_bot = telegram_bot

        if formatter is None:
            from alerts.formatters.telegram import TelegramAlertFormatter
            formatter = TelegramAlertFormatter()
        self._formatter = formatter

        # Composite dedup: "trade_id:reason" -> already alerted
        self._alerted: Set[str] = set()

    def check_and_alert(
        self,
        current_prices: Dict[str, float],
        now_et: Optional[datetime] = None,
    ) -> List[Dict]:
        """Check open earnings positions against exit thresholds.

        Args:
            current_prices: Mapping of ticker -> current price.
            now_et: Optional ET datetime for testing.

        Returns:
            List of dicts describing triggered exit alerts.
        """
        triggered: List[Dict] = []
        et_now = _now_et(now_et)

        for trade in self._paper_trader.open_trades:
            # Only monitor earnings positions
            strategy_type = (
                trade.get("strategy_type")
                or trade.get("type", "")
            )
            if "earnings" not in strategy_type:
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

            # --- 1. Post-earnings close (req 5.5) ---
            post_key = f"{trade_id}:post_earnings"
            if post_key not in self._alerted and _is_post_earnings(trade, et_now):
                self._fire_exit_alert(
                    trade, ticker, pnl, total_credit,
                    reason="post_earnings",
                    action="CLOSE — Post-Earnings IV Crush",
                    instructions=(
                        "Close morning after earnings to capture IV crush. "
                        "Close all four legs of the iron condor."
                    ),
                )
                self._alerted.add(post_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "post_earnings",
                    "pnl": pnl,
                })

            # --- 2. Profit target: P&L >= 50% of credit ---
            profit_key = f"{trade_id}:profit_target"
            if profit_key not in self._alerted and pnl >= total_credit * _PROFIT_TARGET_PCT:
                self._fire_exit_alert(
                    trade, ticker, pnl, total_credit,
                    reason="profit_target",
                    action="CLOSE — Profit Target (50%)",
                    instructions="Take profits on earnings iron condor. Close all four legs.",
                )
                self._alerted.add(profit_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "profit_target",
                    "pnl": pnl,
                })

            # --- 3. Stop loss: P&L <= -(2x credit) ---
            stop_key = f"{trade_id}:stop_loss"
            if stop_key not in self._alerted and pnl <= -(total_credit * _STOP_LOSS_MULT):
                self._fire_exit_alert(
                    trade, ticker, pnl, total_credit,
                    reason="stop_loss",
                    action="CLOSE — Stop Loss (2x credit)",
                    instructions=(
                        "Cut losses on earnings iron condor. "
                        "Close all four legs immediately."
                    ),
                )
                self._alerted.add(stop_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "stop_loss",
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
            logger.error(f"Failed to send earnings exit alert for {ticker}: {e}")
