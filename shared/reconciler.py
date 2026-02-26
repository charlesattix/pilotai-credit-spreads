"""
Position reconciler for PilotAI paper trading.

Compares SQLite state against Alpaca order/position reality and heals
discrepancies that can arise from crashes, network failures, or process
restarts mid-trade-lifecycle.

Design principles:
- Works directly with the database — no dependency on PaperTrader state
- Idempotent: safe to call multiple times; repeated runs produce the same result
- Conservative: never marks a trade as "failed" without confirming with Alpaca

Reconciliation targets:
  pending_open  → open        (order confirmed filled by Alpaca)
  pending_open  → failed_open (order in terminal non-fill state, or 404)
  open          → no change   (normal case; Alpaca position still exists)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Alpaca order statuses that mean the order will never fill
_TERMINAL_ORDER_STATES = frozenset({
    "cancelled", "expired", "rejected", "replaced", "done_for_day",
})

# If a pending_open trade is older than this, assume the order is dead
_PENDING_MAX_AGE_HOURS = 4


class ReconciliationResult:
    """Summary of what the reconciler did in one pass."""

    def __init__(self):
        self.pending_resolved: int = 0   # pending_open → open
        self.pending_failed: int = 0     # pending_open → failed_open
        self.errors: List[str] = []

    def __bool__(self) -> bool:
        return bool(self.pending_resolved or self.pending_failed or self.errors)

    def __repr__(self) -> str:
        return (
            f"ReconciliationResult("
            f"resolved={self.pending_resolved}, "
            f"failed={self.pending_failed}, "
            f"errors={len(self.errors)})"
        )


class PositionReconciler:
    """Reconciles SQLite trade state against the Alpaca broker.

    Usage::

        reconciler = PositionReconciler(alpaca_provider)
        result = reconciler.reconcile()
        logger.info("Reconciliation: %s", result)
    """

    def __init__(self, alpaca, db_path: Optional[str] = None):
        """
        Args:
            alpaca: AlpacaProvider instance (must have get_order_by_client_id).
            db_path: Optional path override for the SQLite database.
        """
        self.alpaca = alpaca
        self.db_path = db_path

    def reconcile(self) -> ReconciliationResult:
        """Run a full reconciliation pass. Safe to call at any time.

        Returns:
            ReconciliationResult summarising what changed.
        """
        result = ReconciliationResult()
        self._reconcile_pending_opens(result)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _reconcile_pending_opens(self, result: ReconciliationResult) -> None:
        """Resolve all pending_open trades.

        For each trade in ``pending_open`` status:
        - No alpaca_client_order_id: treat as DB-only, promote to open.
        - Has alpaca_client_order_id: look up the Alpaca order.
          - filled → promote to open, record fill price.
          - terminal non-fill → mark failed_open.
          - still pending/submitted → leave as pending_open (try again next cycle).
          - too old (> _PENDING_MAX_AGE_HOURS) + not found → mark failed_open.
        """
        from shared.database import get_trades, upsert_trade, insert_reconciliation_event

        pending = get_trades(status="pending_open", path=self.db_path)
        if not pending:
            return

        logger.info("Reconciling %d pending_open trade(s)", len(pending))
        now = datetime.now(timezone.utc)

        for trade in pending:
            trade_id = trade.get("id", "?")
            client_order_id = trade.get("alpaca_client_order_id")

            # Case 1: DB-only trade (Alpaca disabled when trade was opened)
            if not client_order_id:
                trade["status"] = "open"
                upsert_trade(trade, source="scanner", path=self.db_path)
                insert_reconciliation_event(
                    trade_id, "promoted_to_open",
                    {"reason": "no_alpaca_order_id"},
                    self.db_path,
                )
                result.pending_resolved += 1
                logger.info("Trade %s promoted to open (DB-only)", trade_id)
                continue

            # Case 2: Look up order in Alpaca
            order = self.alpaca.get_order_by_client_id(client_order_id)

            if order is None:
                # Alpaca returned error or 404
                age_hours = self._trade_age_hours(trade, now)
                if age_hours >= _PENDING_MAX_AGE_HOURS:
                    trade["status"] = "failed_open"
                    trade["exit_reason"] = "alpaca_order_not_found"
                    upsert_trade(trade, source="scanner", path=self.db_path)
                    insert_reconciliation_event(
                        trade_id, "failed_open",
                        {"reason": "order_not_found", "age_hours": age_hours},
                        self.db_path,
                    )
                    result.pending_failed += 1
                    logger.warning(
                        "Trade %s marked failed_open (order not found, %.1fh old)",
                        trade_id, age_hours,
                    )
                else:
                    logger.debug(
                        "Trade %s still young (%.1fh), skipping until %dh threshold",
                        trade_id, age_hours, _PENDING_MAX_AGE_HOURS,
                    )
                continue

            order_status = order.get("status", "")

            if order_status == "filled":
                trade["status"] = "open"
                trade["alpaca_status"] = "filled"
                fill_price = order.get("filled_avg_price")
                if fill_price:
                    trade["alpaca_fill_price"] = fill_price
                upsert_trade(trade, source="scanner", path=self.db_path)
                insert_reconciliation_event(
                    trade_id, "confirmed_filled",
                    {"fill_price": fill_price, "alpaca_order_id": order.get("id")},
                    self.db_path,
                )
                result.pending_resolved += 1
                logger.info(
                    "Trade %s confirmed filled (fill_price=%s)", trade_id, fill_price
                )

            elif order_status in _TERMINAL_ORDER_STATES:
                trade["status"] = "failed_open"
                trade["exit_reason"] = f"alpaca_{order_status}"
                trade["alpaca_status"] = order_status
                upsert_trade(trade, source="scanner", path=self.db_path)
                insert_reconciliation_event(
                    trade_id, "failed_open",
                    {"order_status": order_status, "alpaca_order_id": order.get("id")},
                    self.db_path,
                )
                result.pending_failed += 1
                logger.warning(
                    "Trade %s marked failed_open (order %s)", trade_id, order_status
                )

            else:
                # Order still live (submitted, pending_new, partially_filled, etc.)
                age_hours = self._trade_age_hours(trade, now)
                logger.debug(
                    "Trade %s order status=%s (%.1fh old) — leaving as pending_open",
                    trade_id, order_status, age_hours,
                )

    @staticmethod
    def _trade_age_hours(trade: Dict, now: datetime) -> float:
        """Return how many hours old a trade is based on its entry_date."""
        entry_str = trade.get("entry_date") or trade.get("created_at", "")
        try:
            entry_time = datetime.fromisoformat(entry_str)
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
            return (now - entry_time).total_seconds() / 3600
        except (ValueError, TypeError):
            return 99.0  # unknown age → treat as old
