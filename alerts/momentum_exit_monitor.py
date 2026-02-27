"""
Momentum swing exit alert monitor.

Watches paper-traded momentum/debit spread positions and fires Telegram alerts:
1. Profit target hit (100% of debit = 2:1 R:R)
2. Stop loss hit (50% of debit)
3. Time decay warning (DTE <= 3 → "close or roll")
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Exit thresholds for momentum debit positions
_PROFIT_TARGET_PCT = 1.00   # 100% of debit paid (req 4.5)
_STOP_LOSS_PCT = 0.50       # 50% of debit
_TIME_DECAY_DTE = 3         # warn when DTE <= 3


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


class MomentumExitMonitor:
    """Monitor momentum/debit spread positions and fire exit alerts.

    Integrates with ``PaperTrader`` for position data and
    ``TelegramBot`` / ``TelegramAlertFormatter`` for notifications.

    Uses composite dedup keys (``trade_id:reason``) so a position can
    receive both a profit alert AND a time decay warning.
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
        """Check open momentum positions against exit thresholds.

        Args:
            current_prices: Mapping of ticker -> current price.
            now_et: Optional ET datetime for testing.

        Returns:
            List of dicts describing triggered exit alerts.
        """
        triggered: List[Dict] = []

        for trade in self._paper_trader.open_trades:
            # Only monitor debit/momentum positions
            strategy_type = (
                trade.get("strategy_type")
                or trade.get("type", "")
            )
            if "debit" not in strategy_type and "momentum" not in strategy_type:
                continue

            trade_id = trade.get("id", "")
            if not trade_id:
                continue

            ticker = trade.get("ticker", "")
            price = current_prices.get(ticker)
            if price is None:
                continue

            total_debit = trade.get("total_debit", 0)
            if total_debit <= 0:
                continue

            # Evaluate P&L via paper trader
            pnl, _close_reason = self._paper_trader._evaluate_position(
                trade, price, dte=0
            )

            # --- 1. Profit target: P&L >= 100% of debit ---
            profit_key = f"{trade_id}:profit_target"
            if profit_key not in self._alerted and pnl >= total_debit * _PROFIT_TARGET_PCT:
                self._fire_exit_alert(
                    trade, ticker, pnl, total_debit,
                    reason="profit_target",
                    action="CLOSE — Profit Target (100%)",
                    instructions="Take profits on debit spread. Close both legs.",
                )
                self._alerted.add(profit_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "profit_target",
                    "pnl": pnl,
                })

            # --- 2. Stop loss: P&L <= -(50% of debit) ---
            stop_key = f"{trade_id}:stop_loss"
            if stop_key not in self._alerted and pnl <= -(total_debit * _STOP_LOSS_PCT):
                self._fire_exit_alert(
                    trade, ticker, pnl, total_debit,
                    reason="stop_loss",
                    action="CLOSE — Stop Loss (50% of debit)",
                    instructions="Cut losses on debit spread. Close both legs immediately.",
                )
                self._alerted.add(stop_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "stop_loss",
                    "pnl": pnl,
                })

            # --- 3. Time decay warning: DTE <= 3 ---
            dte = trade.get("dte", 999)
            time_key = f"{trade_id}:time_decay"
            if time_key not in self._alerted and dte <= _TIME_DECAY_DTE:
                self._fire_exit_alert(
                    trade, ticker, pnl, total_debit,
                    reason="time_decay",
                    action="WARNING — Time Decay (DTE ≤ 3)",
                    instructions=(
                        "Debit spread approaching expiration with accelerating "
                        "time decay. Close or roll to later expiration."
                    ),
                )
                self._alerted.add(time_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "time_decay",
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
        total_debit: float,
        reason: str,
        action: str,
        instructions: str,
    ) -> None:
        """Format and send an exit alert via Telegram."""
        pnl_pct = (pnl / total_debit * 100) if total_debit else 0.0
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
            logger.error(f"Failed to send momentum exit alert for {ticker}: {e}")
