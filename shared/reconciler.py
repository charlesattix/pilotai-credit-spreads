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
  failed_open   → open        (Fix 4: live position found matching a mismarked trade)
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

# How often to run orphan detection from reconcile_pending_only() (minutes)
_ORPHAN_CHECK_INTERVAL_MINUTES = 30

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

        Called every monitor cycle to promote intra-day fills.  Also runs
        orphan detection every ``_ORPHAN_CHECK_INTERVAL_MINUTES`` (Fix 5) so
        intraday orphans are caught without requiring a process restart.

        Returns:
            ReconciliationResult with pending_resolved / pending_failed counts.
        """
        result = ReconciliationResult()
        self._reconcile_pending_opens(result)

        # Fix 5: periodic orphan detection so intraday orphans don't persist
        # until the next restart.  Throttled to every 30 min to avoid API spam.
        if self._should_run_orphan_check():
            alpaca_positions = self._fetch_alpaca_positions()
            if alpaca_positions is not None:
                self._detect_orphan_positions(result, alpaca_positions)
                self._save_last_orphan_check()

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
        from shared.database import get_trades, insert_reconciliation_event, upsert_trade

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
        from shared.database import get_trades, insert_reconciliation_event, upsert_trade

        # Include both open and pending_open — pending_open trades have live orders in flight
        open_trades = get_trades(status="open", path=self.db_path) + \
                      get_trades(status="pending_open", path=self.db_path)

        # Build the full set of OCC symbols managed by open/pending_open DB trades
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

        # Fix 4: build the set of failed_open trades and their expected OCC symbols
        # so we can recover mismarked trades instead of creating unmanaged records.
        failed_trades = get_trades(status="failed_open", path=self.db_path)
        failed_trade_by_symbol: Dict[str, Dict] = {}
        for ft in failed_trades:
            ft_ticker = ft.get("ticker", "")
            ft_exp = str(ft.get("expiration", "")).split(" ")[0]
            ft_type = str(ft.get("strategy_type", ft.get("type", ""))).lower()
            if not ft_ticker or not ft_exp:
                continue
            try:
                for sym in self._expected_symbols(ft, ft_ticker, ft_exp, ft_type):
                    failed_trade_by_symbol[sym] = ft
            except Exception:
                pass

        for symbol, pos_data in alpaca_positions.items():
            asset_class = str(pos_data.get("asset_class", "")).lower()
            if "option" not in asset_class:
                continue
            if symbol in managed_symbols:
                continue

            # Fix 4: check if this orphan matches a failed_open trade — recover it
            matched_failed = failed_trade_by_symbol.get(symbol)
            if matched_failed is not None:
                trade_id = matched_failed.get("id", "?")
                logger.warning(
                    "Reconciler: RECOVERY — orphan %s matches failed_open trade %s. "
                    "Promoting failed_open → open.",
                    symbol, trade_id,
                )
                matched_failed["status"] = "open"
                matched_failed.pop("exit_reason", None)
                try:
                    upsert_trade(matched_failed, source="reconciler", path=self.db_path)
                    insert_reconciliation_event(
                        trade_id, "recovered_to_open",
                        {"reason": "orphan_matched_failed_open", "matched_symbol": symbol},
                        self.db_path,
                    )
                    result.pending_resolved += 1
                    # Remove all symbols of this trade from failed_trade_by_symbol
                    # so we don't attempt to recover the same trade twice.
                    for sym in list(failed_trade_by_symbol.keys()):
                        if failed_trade_by_symbol[sym].get("id") == trade_id:
                            del failed_trade_by_symbol[sym]
                except Exception as e:
                    logger.error(
                        "Reconciler: DB write failed for recovery of %s: %s", trade_id, e
                    )
                    result.errors.append(f"recovery_write_fail:{trade_id}")
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

    # ------------------------------------------------------------------
    # Orphan-check throttle helpers (Fix 5)
    # ------------------------------------------------------------------

    def _should_run_orphan_check(self) -> bool:
        """Return True if enough time has elapsed since the last orphan detection run."""
        from shared.database import load_scanner_state
        last_str = load_scanner_state("last_orphan_check", path=self.db_path)
        if not last_str:
            return True
        try:
            last = datetime.fromisoformat(last_str)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
            return elapsed >= _ORPHAN_CHECK_INTERVAL_MINUTES
        except (ValueError, TypeError):
            return True

    def _save_last_orphan_check(self) -> None:
        """Persist the current timestamp as the last orphan detection run time."""
        from shared.database import save_scanner_state
        try:
            save_scanner_state(
                "last_orphan_check",
                datetime.now(timezone.utc).isoformat(),
                path=self.db_path,
            )
        except Exception as e:
            logger.warning("Reconciler: could not save last_orphan_check timestamp: %s", e)

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

    def _fetch_recent_orders_by_client_id(self) -> dict:
        """Batch-fetch recent Alpaca orders and index them by client_order_id.

        get_order_by_client_id() returns 404 for MLEG (multi-leg) orders — a known
        Alpaca paper trading limitation. get_orders() returns them correctly.
        We pre-fetch all recent orders once and use that dict for all lookups,
        which also reduces per-trade API calls.
        """
        try:
            orders = self.alpaca.get_orders(status="all", limit=500)
            return {o["client_order_id"]: o for o in orders if o.get("client_order_id")}
        except Exception as e:
            logger.warning("Reconciler: could not batch-fetch orders (%s) — will use per-trade lookup", e)
            return {}

    def _reconcile_pending_opens(self, result: ReconciliationResult) -> None:
        """Resolve all pending_open trades.

        Uses a batch order fetch (handles MLEG orders that fail get_order_by_client_id).
        IC (iron condor) trades use their wing client_order_ids (Fix 1): both wings must
        be filled for the IC to become open; any terminal wing → failed_open.
        Falls back to per-trade get_order_by_client_id for orders not in the batch.
        Only marks failed_open when order is confirmed absent AND older than
        _PENDING_MAX_AGE_HOURS (avoids race conditions on just-submitted orders).
        """
        from shared.database import get_trades, insert_reconciliation_event, upsert_trade

        pending = get_trades(status="pending_open", path=self.db_path)
        if not pending:
            return

        logger.info("Reconciling %d pending_open trade(s)", len(pending))
        now = datetime.now(timezone.utc)

        # Pre-fetch all recent orders indexed by client_order_id (handles MLEG 404 issue)
        orders_by_client_id = self._fetch_recent_orders_by_client_id()

        for trade in pending:
            trade_id = trade.get("id", "?")
            client_order_id = trade.get("alpaca_client_order_id")

            # Case 1: No Alpaca order ID — order was never submitted to the broker
            if not client_order_id:
                if trade.get('dry_run'):
                    status = 'open'
                else:
                    status = 'failed_open'
                trade["status"] = status
                upsert_trade(trade, source="scanner", path=self.db_path)
                insert_reconciliation_event(
                    trade_id, status,
                    {"reason": "no_alpaca_order_id", "dry_run": bool(trade.get('dry_run'))},
                    self.db_path,
                )
                if status == 'open':
                    result.pending_resolved += 1
                    logger.info("Trade %s promoted to open (dry_run)", trade_id)
                else:
                    result.pending_failed += 1
                    logger.warning("Trade %s marked failed_open (no order ID, not dry_run)", trade_id)
                continue

            # Fix 1: IC (iron condor) trades are submitted as two MLEG orders with
            # suffixed client_order_ids ("-put" and "-call").  Reconcile them together.
            spread_type = str(trade.get("strategy_type", trade.get("type", ""))).lower()
            if "condor" in spread_type:
                self._reconcile_ic_pending(trade, orders_by_client_id, result, now)
                continue

            # Case 2: Regular spread — look up from batch first (handles MLEG 404 issue)
            order = orders_by_client_id.get(client_order_id)
            if order is None:
                order = self.alpaca.get_order_by_client_id(client_order_id)

            if order is None:
                # Fix 3: Belt-and-suspenders — check wing suffixes before age-based failure.
                # Handles legacy IC records that may not have alpaca_put/call_order_id stored.
                wing_order = (
                    orders_by_client_id.get(client_order_id + "-put")
                    or orders_by_client_id.get(client_order_id + "-call")
                )
                if wing_order is not None:
                    logger.debug(
                        "Trade %s found via IC wing suffix in batch — leaving pending_open "
                        "(will be reconciled as IC on next cycle)",
                        trade_id,
                    )
                    continue

                # Not found via either method — only fail if old enough to rule out race condition
                age_hours = self._trade_age_hours(trade, now)
                if age_hours >= _PENDING_MAX_AGE_HOURS:
                    trade["status"] = "failed_open"
                    trade["exit_reason"] = "alpaca_order_not_found"
                    upsert_trade(trade, source="reconciler", path=self.db_path)
                    insert_reconciliation_event(
                        trade_id, "failed_open",
                        {"reason": "order_not_found", "age_hours": age_hours},
                        self.db_path,
                    )
                    result.pending_failed += 1
                    logger.warning(
                        "Trade %s marked failed_open (order not found, %.1fh old)", trade_id, age_hours
                    )
                else:
                    logger.debug(
                        "Trade %s not found in Alpaca yet (%.1fh old) — leaving pending_open",
                        trade_id, age_hours,
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

    def _reconcile_ic_pending(
        self,
        trade: Dict,
        orders_by_client_id: Dict,
        result: "ReconciliationResult",
        now: datetime,
    ) -> None:
        """Reconcile a single pending_open iron condor trade.

        ICs are submitted as two MLEG orders: client_id + "-put" and client_id + "-call".
        Both wings must be filled for the IC to become open.
        Any wing in a terminal failure state → failed_open.
        If neither wing is found and the trade is old enough → failed_open.
        """
        from shared.database import insert_reconciliation_event, upsert_trade

        trade_id = trade.get("id", "?")
        client_order_id = trade.get("alpaca_client_order_id", trade_id)

        # Use stored wing IDs if available (Fix 1); derive from bare client_id as fallback
        put_cid = trade.get("alpaca_put_order_id") or (client_order_id + "-put")
        call_cid = trade.get("alpaca_call_order_id") or (client_order_id + "-call")

        put_order = orders_by_client_id.get(put_cid)
        call_order = orders_by_client_id.get(call_cid)

        # Fall back to per-trade lookup if not in batch (may still return None for MLEG)
        if put_order is None:
            put_order = self.alpaca.get_order_by_client_id(put_cid)
        if call_order is None:
            call_order = self.alpaca.get_order_by_client_id(call_cid)

        put_status = put_order.get("status", "") if put_order else None
        call_status = call_order.get("status", "") if call_order else None

        # Both wings filled → promote to open
        if put_status == "filled" and call_status == "filled":
            trade["status"] = "open"
            trade["alpaca_status"] = "filled"
            put_fill = put_order.get("filled_avg_price")
            call_fill = call_order.get("filled_avg_price")
            if put_fill and call_fill:
                try:
                    trade["alpaca_fill_price"] = float(put_fill) + float(call_fill)
                except (ValueError, TypeError):
                    pass
            upsert_trade(trade, source="scanner", path=self.db_path)
            insert_reconciliation_event(
                trade_id, "confirmed_filled",
                {"ic_put_fill": put_fill, "ic_call_fill": call_fill},
                self.db_path,
            )
            result.pending_resolved += 1
            logger.info("IC trade %s confirmed filled (put=%s call=%s)", trade_id, put_fill, call_fill)
            return

        # Any wing in terminal failure state → failed_open
        if put_status in _TERMINAL_ORDER_STATES or call_status in _TERMINAL_ORDER_STATES:
            failed_wing = "put" if put_status in _TERMINAL_ORDER_STATES else "call"
            failed_status = put_status if put_status in _TERMINAL_ORDER_STATES else call_status
            trade["status"] = "failed_open"
            trade["exit_reason"] = f"ic_{failed_wing}_alpaca_{failed_status}"
            trade["alpaca_status"] = failed_status
            upsert_trade(trade, source="reconciler", path=self.db_path)
            insert_reconciliation_event(
                trade_id, "failed_open",
                {"ic_failed_wing": failed_wing, "order_status": failed_status},
                self.db_path,
            )
            result.pending_failed += 1
            logger.warning(
                "IC trade %s marked failed_open (%s wing: %s)", trade_id, failed_wing, failed_status
            )
            return

        # Neither wing found — only fail if old enough
        if put_order is None and call_order is None:
            age_hours = self._trade_age_hours(trade, now)
            if age_hours >= _PENDING_MAX_AGE_HOURS:
                trade["status"] = "failed_open"
                trade["exit_reason"] = "ic_wings_not_found_in_alpaca"
                upsert_trade(trade, source="reconciler", path=self.db_path)
                insert_reconciliation_event(
                    trade_id, "failed_open",
                    {"reason": "ic_wings_not_found", "age_hours": age_hours},
                    self.db_path,
                )
                result.pending_failed += 1
                logger.warning(
                    "IC trade %s marked failed_open (wings not found, %.1fh old)", trade_id, age_hours
                )
            else:
                logger.debug(
                    "IC trade %s wings not found yet (%.1fh old) — leaving pending_open",
                    trade_id, age_hours,
                )
            return

        # At least one wing found but not in terminal state — still in flight
        age_hours = self._trade_age_hours(trade, now)
        logger.debug(
            "IC trade %s put_status=%s call_status=%s (%.1fh old) — leaving as pending_open",
            trade_id, put_status, call_status, age_hours,
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
