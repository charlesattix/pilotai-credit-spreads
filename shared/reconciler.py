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
        self.pending_resolved: int = 0   # pending_open → open (fill confirmed)
        self.pending_failed: int = 0     # pending_open → failed_open (terminal state)
        self.phantom_resolved: int = 0   # open → needs_investigation (not in Alpaca)
        self.orphans_detected: int = 0   # Alpaca positions not in DB (logged, record created)
        self.errors: List[str] = []

    def __bool__(self) -> bool:
        return bool(
            self.pending_resolved or self.pending_failed
            or self.phantom_resolved or self.orphans_detected
            or self.errors
        )

    def __repr__(self) -> str:
        return (
            f"ReconciliationResult("
            f"resolved={self.pending_resolved}, "
            f"failed={self.pending_failed}, "
            f"phantoms={self.phantom_resolved}, "
            f"orphans={self.orphans_detected}, "
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

    def reconcile_pending_only(self) -> ReconciliationResult:
        """Resolve pending_open orders only (step 1 of full reconciliation).

        Called every monitor cycle to promote intra-day fills.  Does NOT run
        phantom or orphan detection — those are reserved for startup via
        ``reconcile()``.

        Returns:
            ReconciliationResult with pending_resolved / pending_failed counts.
        """
        result = ReconciliationResult()
        self._reconcile_pending_opens(result)
        if result:
            logger.info("Pending-open reconciliation: %s", result)
        return result

    def reconcile(self) -> ReconciliationResult:
        """Run a full reconciliation pass against Alpaca's live state.

        Steps:
          1. Resolve pending_open orders (check fills, terminal states).
          2. Detect phantom positions: DB says open but Alpaca has no matching legs.
          3. Detect orphan positions: Alpaca has option positions not in DB.

        Safe to call at any time; idempotent (repeated calls converge to same state).

        Returns:
            ReconciliationResult summarising what changed.
        """
        result = ReconciliationResult()

        # Step 1: pending_open → open / failed_open
        self._reconcile_pending_opens(result)

        # Steps 2+3: only possible if we can fetch Alpaca positions
        alpaca_positions = self._fetch_alpaca_positions()
        if alpaca_positions is not None:
            # Step 2: detect open DB trades whose legs have disappeared from Alpaca
            self._reconcile_open_positions(result, alpaca_positions)
            # Step 3: detect Alpaca option positions with no DB record
            self._detect_orphan_positions(result, alpaca_positions)

        if result:
            logger.info("Reconciliation complete: %s", result)
        else:
            logger.info("Reconciliation complete: nothing to do")

        return result

    def _fetch_alpaca_positions(self) -> Optional[Dict]:
        """Fetch all current Alpaca positions as {symbol: pos_dict}.

        Returns None if the API call fails (non-fatal — Steps 2+3 are skipped).
        """
        try:
            positions = self.alpaca.get_positions()
            return {p["symbol"]: p for p in positions}
        except Exception as e:
            logger.warning(
                "Reconciler: could not fetch Alpaca positions (%s) — "
                "skipping open-position and orphan reconciliation",
                e,
            )
            return None

    def _reconcile_open_positions(
        self, result: ReconciliationResult, alpaca_positions: Dict
    ) -> None:
        """Detect phantom positions: DB status=open but ALL legs missing from Alpaca.

        A position can disappear from Alpaca because it:
        - Expired worthless (the most common case — no action needed)
        - Was externally closed (manual close in Alpaca dashboard)
        - Was assigned (stock position appeared instead)

        Rather than guess, we mark these as ``needs_investigation`` so a human
        (or later automation) can determine the cause and record the correct P&L.
        """
        from shared.database import get_trades, upsert_trade, insert_reconciliation_event

        open_trades = get_trades(status="open", path=self.db_path)
        if not open_trades:
            return

        for trade in open_trades:
            trade_id = trade.get("id", "?")
            ticker = trade.get("ticker", "")
            exp = str(trade.get("expiration", "")).split(" ")[0]
            spread_type = str(trade.get("strategy_type", trade.get("type", ""))).lower()

            if not ticker or not exp:
                continue

            try:
                syms = self._expected_symbols(trade, ticker, exp, spread_type)
            except Exception as e:
                logger.warning(
                    "Reconciler: OCC symbol error for trade %s: %s — skipping", trade_id, e
                )
                continue

            if not syms:
                continue

            all_missing = all(sym not in alpaca_positions for sym in syms)
            if not all_missing:
                continue  # at least one leg still present — all good

            logger.warning(
                "Reconciler: PHANTOM POSITION — trade %s (open) has no legs in Alpaca. "
                "Expected: %s. Marking needs_investigation.",
                trade_id, syms,
            )
            trade["status"] = "needs_investigation"
            trade["exit_reason"] = "legs_not_found_in_alpaca"
            try:
                upsert_trade(trade, source="reconciler", path=self.db_path)
                insert_reconciliation_event(
                    trade_id, "needs_investigation",
                    {"reason": "legs_not_found_in_alpaca", "expected_symbols": syms},
                    self.db_path,
                )
            except Exception as e:
                logger.error(
                    "Reconciler: DB write failed for phantom %s: %s", trade_id, e
                )
                result.errors.append(f"phantom_write_fail:{trade_id}")
            result.phantom_resolved += 1

    def _detect_orphan_positions(
        self, result: ReconciliationResult, alpaca_positions: Dict
    ) -> None:
        """Detect orphan option positions: in Alpaca but not in any DB open trade.

        Orphans are logged and a minimal DB record is created with
        ``status=unmanaged`` so they show up in reports and are not silently ignored.
        The system does NOT attempt to close or manage orphans automatically.
        """
        from shared.database import get_trades, upsert_trade

        open_trades = get_trades(status="open", path=self.db_path)

        # Build the full set of OCC symbols managed by open DB trades
        managed_symbols: set = set()
        for trade in open_trades:
            ticker = trade.get("ticker", "")
            exp = str(trade.get("expiration", "")).split(" ")[0]
            spread_type = str(trade.get("strategy_type", trade.get("type", ""))).lower()
            if not ticker or not exp:
                continue
            try:
                for sym in self._expected_symbols(trade, ticker, exp, spread_type):
                    managed_symbols.add(sym)
            except Exception:
                pass

        for symbol, pos_data in alpaca_positions.items():
            asset_class = str(pos_data.get("asset_class", "")).lower()
            if "option" not in asset_class:
                continue
            if symbol in managed_symbols:
                continue

            qty = pos_data.get("qty", "?")
            logger.warning(
                "Reconciler: ORPHAN POSITION — %s qty=%s has no DB record. "
                "Creating unmanaged record. Manual review required.",
                symbol, qty,
            )
            orphan_id = f"orphan-{symbol[:20]}"
            orphan_record = {
                "id": orphan_id,
                "ticker": symbol[:3],
                "strategy_type": "unknown",
                "status": "unmanaged",
                "credit": 0.0,
                "contracts": 0,
                "short_strike": 0.0,
                "long_strike": 0.0,
                "expiration": "",
                "entry_date": datetime.now(timezone.utc).isoformat(),
                "alpaca_symbol": symbol,
            }
            try:
                upsert_trade(orphan_record, source="reconciler", path=self.db_path)
            except Exception as e:
                logger.error(
                    "Reconciler: failed to create orphan record for %s: %s", symbol, e
                )
                result.errors.append(f"orphan_write_fail:{symbol}")
            result.orphans_detected += 1

    def _expected_symbols(
        self, trade: Dict, ticker: str, exp: str, spread_type: str
    ) -> List[str]:
        """Return the list of OCC symbols expected for this trade's legs."""
        syms = []
        if "condor" in spread_type:
            legs = [
                (trade.get("put_short_strike") or trade.get("short_strike"), "put"),
                (trade.get("put_long_strike") or trade.get("long_strike"), "put"),
                (trade.get("call_short_strike"), "call"),
                (trade.get("call_long_strike"), "call"),
            ]
        else:
            opt_type = "call" if "call" in spread_type else "put"
            legs = [
                (trade.get("short_strike"), opt_type),
                (trade.get("long_strike"), opt_type),
            ]
        for strike, ot in legs:
            if strike:
                syms.append(self.alpaca._build_occ_symbol(ticker, exp, strike, ot))
        return syms

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

            # Case 1: No Alpaca order ID — order was never submitted to the broker
            # (e.g. crash or network failure after DB write but before Alpaca submission).
            # The reconciler only runs when Alpaca is active, so a missing order ID
            # means there is no live position to track. Mark failed_open immediately
            # rather than promoting to open where the trade would have no Alpaca coverage.
            if not client_order_id:
                trade["status"] = "failed_open"
                trade["exit_reason"] = "stale_no_order_id"
                upsert_trade(trade, source="reconciler", path=self.db_path)
                insert_reconciliation_event(
                    trade_id, "failed_open",
                    {"reason": "no_alpaca_order_id"},
                    self.db_path,
                )
                result.pending_failed += 1
                logger.warning(
                    "Trade %s marked failed_open (no Alpaca order ID — never submitted)",
                    trade_id,
                )
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
