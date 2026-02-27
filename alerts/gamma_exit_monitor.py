"""
Gamma/lotto play exit alert monitor.

Watches paper-traded gamma lotto positions and fires Telegram alerts
using a trailing stop state machine:

1. Trailing stop activation — P&L >= 3x debit → fire "SET TRAILING STOP at 2x entry"
2. Trailing stop triggered — after activation, if P&L drops below 2x debit → fire "CLOSE"
3. Total loss — option worthless (P&L <= -debit) → fire "EXPIRED WORTHLESS"
"""

import logging
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Trailing stop thresholds (multiples of debit paid)
_TRAILING_STOP_ACTIVATION = 3.0   # activate at 3x entry
_TRAILING_STOP_LEVEL = 2.0        # trail at 2x entry


class GammaExitMonitor:
    """Monitor gamma lotto positions with trailing stop state machine.

    Integrates with ``PaperTrader`` for position data and
    ``TelegramBot`` / ``TelegramAlertFormatter`` for notifications.

    Uses composite dedup keys (``trade_id:reason``) so a position can
    receive multiple distinct alerts.
    """

    def __init__(self, paper_trader, telegram_bot, formatter=None):
        self._paper_trader = paper_trader
        self._telegram_bot = telegram_bot

        if formatter is None:
            from alerts.formatters.telegram import TelegramAlertFormatter
            formatter = TelegramAlertFormatter()
        self._formatter = formatter

        # Trailing stop state: trade_id → {activated: bool, peak_pnl: float}
        self._trailing_stops: Dict[str, Dict] = {}

        # Composite dedup: "trade_id:reason" → already alerted
        self._alerted: Set[str] = set()

    def check_and_alert(
        self,
        current_prices: Dict[str, float],
        now_et=None,
    ) -> List[Dict]:
        """Check open gamma positions against trailing stop thresholds.

        Args:
            current_prices: Mapping of ticker → current price.
            now_et: Optional datetime for testing (unused but matches interface).

        Returns:
            List of dicts describing triggered exit alerts.
        """
        triggered: List[Dict] = []

        for trade in self._paper_trader.open_trades:
            # Only monitor gamma/lotto positions
            strategy_type = (
                trade.get("strategy_type")
                or trade.get("type", "")
            )
            if "gamma" not in strategy_type and "lotto" not in strategy_type:
                continue

            trade_id = trade.get("id", "")
            if not trade_id:
                continue

            ticker = trade.get("ticker", "")
            price = current_prices.get(ticker)
            if price is None:
                continue

            debit = trade.get("debit", trade.get("entry_price", 0))
            if debit <= 0:
                continue

            # Evaluate P&L via paper trader
            pnl, _close_reason = self._paper_trader._evaluate_position(
                trade, price, dte=0
            )

            # Initialize trailing stop state if needed
            if trade_id not in self._trailing_stops:
                self._trailing_stops[trade_id] = {
                    "activated": False,
                    "peak_pnl": 0.0,
                }

            state = self._trailing_stops[trade_id]

            # Track peak P&L
            if pnl > state["peak_pnl"]:
                state["peak_pnl"] = pnl

            # --- 1. Trailing stop activation: P&L >= 3x debit ---
            activation_key = f"{trade_id}:trailing_stop_activation"
            activation_threshold = debit * _TRAILING_STOP_ACTIVATION * 100  # per-contract dollars
            if (
                activation_key not in self._alerted
                and not state["activated"]
                and pnl >= activation_threshold
            ):
                state["activated"] = True
                self._fire_exit_alert(
                    trade, ticker, pnl, debit,
                    reason="trailing_stop_activation",
                    action="SET TRAILING STOP at 2x entry",
                    instructions=(
                        f"Gamma lotto hit {_TRAILING_STOP_ACTIVATION:.0f}x entry! "
                        f"Set trailing stop at ${debit * _TRAILING_STOP_LEVEL:.2f} "
                        f"({_TRAILING_STOP_LEVEL:.0f}x entry). Let winners run."
                    ),
                )
                self._alerted.add(activation_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "trailing_stop_activation",
                    "pnl": pnl,
                })

            # --- 2. Trailing stop triggered: activated + P&L drops below 2x ---
            trailing_key = f"{trade_id}:trailing_stop_triggered"
            trailing_threshold = debit * _TRAILING_STOP_LEVEL * 100
            if (
                trailing_key not in self._alerted
                and state["activated"]
                and pnl < trailing_threshold
            ):
                self._fire_exit_alert(
                    trade, ticker, pnl, debit,
                    reason="trailing_stop_triggered",
                    action="CLOSE — Trailing Stop Hit",
                    instructions=(
                        f"Gamma lotto trailing stop hit. "
                        f"P&L dropped below {_TRAILING_STOP_LEVEL:.0f}x entry. "
                        f"Close position to lock in remaining gains."
                    ),
                )
                self._alerted.add(trailing_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "trailing_stop_triggered",
                    "pnl": pnl,
                })

            # --- 3. Total loss: option expired worthless ---
            worthless_key = f"{trade_id}:expired_worthless"
            if (
                worthless_key not in self._alerted
                and pnl <= -(debit * 100)
            ):
                self._fire_exit_alert(
                    trade, ticker, pnl, debit,
                    reason="expired_worthless",
                    action="EXPIRED WORTHLESS",
                    instructions=(
                        "Gamma lotto expired worthless. "
                        "Max loss = debit paid. No action needed."
                    ),
                )
                self._alerted.add(worthless_key)
                triggered.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "expired_worthless",
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
        debit: float,
        reason: str,
        action: str,
        instructions: str,
    ) -> None:
        """Format and send an exit alert via Telegram."""
        pnl_pct = (pnl / (debit * 100) * 100) if debit > 0 else 0.0
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
            logger.error(f"Failed to send gamma exit alert for {ticker}: {e}")
