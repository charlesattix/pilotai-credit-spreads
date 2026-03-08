"""
0DTE/1DTE exit alert monitor.

Watches paper-traded 0DTE positions and fires Telegram alerts when
profit targets (50% of credit) or stop losses (2x credit) are hit.
"""

import logging
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Exit thresholds for 0DTE positions
_PROFIT_TARGET_PCT = 0.50   # 50% of credit received
_STOP_LOSS_MULT = 2.0       # 2x credit


class ZeroDTEExitMonitor:
    """Monitor 0DTE/1DTE paper-trade positions and fire exit alerts.

    Integrates with ``PaperTrader`` for position data and
    ``TelegramBot`` / ``TelegramAlertFormatter`` for notifications.
    """

    def __init__(self, paper_trader, telegram_bot, formatter=None):
        """
        Args:
            paper_trader: ``PaperTrader`` instance with ``open_trades``.
            telegram_bot: ``TelegramBot`` instance for sending alerts.
            formatter: Optional ``TelegramAlertFormatter``; created if None.
        """
        self._paper_trader = paper_trader
        self._telegram_bot = telegram_bot

        if formatter is None:
            from alerts.formatters.telegram import TelegramAlertFormatter
            formatter = TelegramAlertFormatter()
        self._formatter = formatter

        # Track which positions have already been alerted (avoid duplicates)
        self._alerted_positions: Set[str] = set()

    def check_and_alert(self, current_prices: Dict[str, float]) -> List[Dict]:
        """Check open 0DTE/1DTE positions against exit thresholds.

        Args:
            current_prices: Mapping of ticker → current price.

        Returns:
            List of dicts describing triggered exit alerts.
        """
        triggered: List[Dict] = []

        for trade in self._paper_trader.open_trades:
            # Only monitor 0DTE/1DTE positions
            dte_at_entry = trade.get("dte_at_entry", 999)
            if dte_at_entry > 1:
                continue

            trade_id = trade.get("id", "")
            if not trade_id or trade_id in self._alerted_positions:
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

            # Check profit target: P&L >= 50% of credit
            if pnl >= total_credit * _PROFIT_TARGET_PCT:
                self._fire_exit_alert(
                    trade, ticker, pnl, total_credit,
                    reason="profit_target",
                    action="CLOSE — Profit Target",
                    instructions="Take profits. 0DTE theta decay accelerates into close.",
                )
                self._alerted_positions.add(trade_id)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "profit_target",
                    "pnl": pnl,
                })

            # Check stop loss: P&L <= -(2x credit)
            elif pnl <= -(total_credit * _STOP_LOSS_MULT):
                self._fire_exit_alert(
                    trade, ticker, pnl, total_credit,
                    reason="stop_loss",
                    action="CLOSE — Stop Loss",
                    instructions="Cut losses. Do not hold 0DTE losers into close.",
                )
                self._alerted_positions.add(trade_id)
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
            logger.error(f"Failed to send 0DTE exit alert for {ticker}: {e}")
