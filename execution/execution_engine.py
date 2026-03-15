"""
ExecutionEngine — submits approved alert opportunities as live orders to Alpaca.

Design principles:
- Write to DB FIRST in pending_open state before calling Alpaca (prevents orphans on crash)
- Deterministic client_order_id for idempotency (safe to replay on restart)
- Returns result dict; never raises — callers decide how to handle errors
- Dry-run mode when alpaca_provider is None (alert-only mode)
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from shared.database import upsert_trade, init_db, get_trade_by_id

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Submits approved opportunities as live orders to Alpaca.

    Usage::

        engine = ExecutionEngine(alpaca_provider=provider, db_path=None)
        result = engine.submit_opportunity(opp_dict)
        # result['status'] == 'submitted' | 'dry_run' | 'error'
    """

    def __init__(self, alpaca_provider, db_path: Optional[str] = None, config: Optional[Dict] = None):
        """
        Args:
            alpaca_provider: AlpacaProvider instance, or None for dry-run/alert-only mode.
            db_path: Optional override for the SQLite database path.
            config: Application config dict.  Reads ``execution.atomic_ic_execution``
                    (default False).  When True (future: requires Alpaca 4-leg OTO support),
                    iron condors will be submitted as a single atomic order instead of two
                    separate 2-leg orders.  Currently this flag only controls a log warning;
                    the two-order path is always used until Alpaca supports atomic 4-leg ICs.
        """
        self.alpaca = alpaca_provider
        self.db_path = db_path
        self.config = config or {}
        # PARTIAL #8: atomic_ic_execution flag — reserved for future Alpaca 4-leg OTO support
        self._atomic_ic = bool(
            self.config.get("execution", {}).get("atomic_ic_execution", False)
        )
        if self._atomic_ic:
            logger.warning(
                "ExecutionEngine: atomic_ic_execution=True is set but not yet supported "
                "by Alpaca. IC orders will still be submitted as two 2-leg orders. "
                "This flag will activate automatic 4-leg submission once Alpaca adds support."
            )
        init_db(db_path)

    def submit_opportunity(self, opp: Dict) -> Dict:
        """Submit a single opportunity as a live order.

        Args:
            opp: Opportunity dict from the scanner. Expected keys:
                 ticker, type (bull_put/bear_call/iron_condor), expiration,
                 short_strike, long_strike, credit, contracts.

                 For iron condors, also needs: put_short_strike, put_long_strike,
                 call_short_strike, call_long_strike.

        Returns:
            Dict with keys: status, order_id (if submitted), client_order_id, message.
        """
        ticker = opp.get("ticker", "UNK")
        spread_type = opp.get("type", opp.get("strategy_type", "unknown"))
        expiration = opp.get("expiration", "")
        short_strike = round(float(opp.get("short_strike", 0) or 0), 2)
        long_strike = round(float(opp.get("long_strike", 0) or 0), 2)
        credit = float(opp.get("credit", opp.get("credit_per_spread", 0)) or 0)
        contracts = int(opp.get("contracts", 1))

        # Build deterministic client_order_id (hash of key fields for idempotency)
        raw_id = f"{ticker}-{spread_type}-{expiration}-{short_strike}-{long_strike}"
        client_id = "cs-" + hashlib.sha256(raw_id.encode()).hexdigest()[:16]

        # Bug #3 fix: defense-in-depth duplicate check before submitting.
        # If dedup layer fails (Bug #2) the same opportunity can arrive again.
        try:
            existing = get_trade_by_id(client_id, path=self.db_path)
            if existing and existing.get("status") not in ("rejected", "cancelled"):
                logger.info(
                    "ExecutionEngine: trade %s already exists (status=%s), skipping duplicate",
                    client_id, existing.get("status"),
                )
                return {"status": "duplicate", "client_order_id": client_id,
                        "message": f"trade already exists with status={existing.get('status')}"}
        except Exception as e:
            logger.debug("ExecutionEngine: duplicate check failed (non-fatal): %s", e)

        # Write to DB FIRST in pending_open state before touching Alpaca
        trade_record = {
            "id": client_id,
            "ticker": ticker,
            "strategy_type": spread_type,
            "status": "pending_open",
            "short_strike": short_strike,
            "long_strike": long_strike,
            "expiration": str(expiration),
            "credit": credit,
            "contracts": contracts,
            "entry_date": datetime.now(timezone.utc).isoformat(),
            "alpaca_client_order_id": client_id,
        }
        # For iron condors, preserve per-wing strikes in metadata so PositionMonitor
        # can build OCC symbols for all 4 legs when pricing and closing.
        spread_lower = spread_type.lower()
        if "condor" in spread_lower:
            trade_record["put_short_strike"] = round(float(opp.get("put_short_strike", short_strike) or short_strike), 2)
            trade_record["put_long_strike"] = round(float(opp.get("put_long_strike", long_strike) or long_strike), 2)
            trade_record["call_short_strike"] = round(float(opp.get("call_short_strike", short_strike) or short_strike), 2)
            trade_record["call_long_strike"] = round(float(opp.get("call_long_strike", long_strike) or long_strike), 2)
        elif "straddle" in spread_lower or "strangle" in spread_lower:
            trade_record["call_strike"] = round(float(opp.get("call_strike", 0) or 0), 2)
            trade_record["put_strike"] = round(float(opp.get("put_strike", 0) or 0), 2)
            trade_record["is_debit"] = opp.get("is_debit", False)
        try:
            upsert_trade(trade_record, source="execution", path=self.db_path)
        except Exception as e:
            logger.error("ExecutionEngine: DB write failed for %s: %s", client_id, e)
            return {"status": "error", "message": f"DB write failed: {e}", "client_order_id": client_id}

        # Dry-run mode: no Alpaca provider configured
        if not self.alpaca:
            if "straddle" in spread_lower or "strangle" in spread_lower:
                is_debit = opp.get("is_debit", False) or credit < 0
                direction = "DEBIT" if is_debit else "CREDIT"
                event_type = opp.get("event_type", opp.get("metadata", {}).get("event_type", "unknown"))
                logger.info(
                    "ExecutionEngine [DRY RUN]: would submit %s %s x%d | "
                    "call=$%.2f put=$%.2f | %s $%.2f | event=%s (client_id=%s)",
                    ticker, spread_type, contracts,
                    round(float(opp.get("call_strike", 0) or 0), 2),
                    round(float(opp.get("put_strike", 0) or 0), 2),
                    direction, abs(credit), event_type, client_id,
                )
            else:
                logger.info(
                    "ExecutionEngine [DRY RUN]: would submit %s %s x%d @ %.2f credit (client_id=%s)",
                    ticker, spread_type, contracts, credit, client_id,
                )
            return {"status": "dry_run", "client_order_id": client_id, "message": "alpaca not configured"}

        # Market hours guard — check Alpaca clock before submitting any order
        clock = self.alpaca.get_market_clock()
        is_open = clock.get("is_open")
        if is_open is False:
            logger.warning(
                "ExecutionEngine: market is CLOSED — blocking order for %s %s (client_id=%s). "
                "next_open=%s",
                ticker, spread_type, client_id, clock.get("next_open"),
            )
            return {
                "status": "market_closed",
                "client_order_id": client_id,
                "message": f"market closed; next_open={clock.get('next_open')}",
            }
        # is_open=None means clock check failed — fail open (don't block)

        # Submit to Alpaca
        try:
            if "condor" in spread_type.lower():
                result = self._submit_iron_condor(opp, contracts, credit, client_id)
            elif "straddle" in spread_type.lower() or "strangle" in spread_type.lower():
                result = self._submit_straddle(opp, contracts, credit, client_id)
            else:
                result = self.alpaca.submit_credit_spread(
                    ticker=ticker,
                    short_strike=short_strike,
                    long_strike=long_strike,
                    expiration=str(expiration).split(" ")[0] if expiration else "",
                    spread_type=spread_type,
                    contracts=contracts,
                    limit_price=credit if credit > 0 else None,
                    client_order_id=client_id,
                )

            if result.get("status") == "submitted":
                logger.info(
                    "ExecutionEngine: submitted %s %s x%d order_id=%s",
                    ticker, spread_type, contracts, result.get("order_id"),
                )
            else:
                logger.warning(
                    "ExecutionEngine: Alpaca returned non-submitted status for %s: %s",
                    client_id, result,
                )

            result["client_order_id"] = client_id
            return result

        except Exception as e:
            logger.error("ExecutionEngine: Alpaca submission failed for %s: %s", client_id, e, exc_info=True)
            return {"status": "error", "message": str(e), "client_order_id": client_id}

    def _submit_iron_condor(self, opp: Dict, contracts: int, credit: float, client_id: str) -> Dict:
        """Submit iron condor as two separate MLEG orders (put wing + call wing).

        Alpaca supports multi-leg but iron condors may need to be submitted as
        two 2-leg spreads. Submit put side first, then call side.
        """
        ticker = opp.get("ticker", "UNK")
        expiration = str(opp.get("expiration", "")).split(" ")[0]

        put_short = round(float(opp.get("put_short_strike") or opp.get("short_strike", 0)), 2)
        put_long = round(float(opp.get("put_long_strike") or opp.get("long_strike", 0)), 2)
        call_short = round(float(opp.get("call_short_strike") or opp.get("short_strike", 0)), 2)
        call_long = round(float(opp.get("call_long_strike") or opp.get("long_strike", 0)), 2)

        # Split credit approximately 50/50 between wings
        put_credit = credit / 2 if credit > 0 else None
        call_credit = credit / 2 if credit > 0 else None

        put_result = self.alpaca.submit_credit_spread(
            ticker=ticker, short_strike=put_short, long_strike=put_long,
            expiration=expiration, spread_type="bull_put",
            contracts=contracts, limit_price=put_credit,
            client_order_id=client_id + "-put",
        )

        if put_result.get("status") != "submitted":
            logger.error(
                "ExecutionEngine: put wing failed for IC %s — skipping call wing. put_result=%s",
                client_id, put_result,
            )
            return {"status": "partial_error", "put_result": put_result, "call_result": None}

        call_result = self.alpaca.submit_credit_spread(
            ticker=ticker, short_strike=call_short, long_strike=call_long,
            expiration=expiration, spread_type="bear_call",
            contracts=contracts, limit_price=call_credit,
            client_order_id=client_id + "-call",
        )

        if call_result.get("status") != "submitted":
            # Put wing is live — attempt to cancel it to avoid a naked position
            put_order_id = put_result.get("order_id")
            logger.error(
                "ExecutionEngine: call wing failed for IC %s — attempting to cancel put wing order_id=%s. call_result=%s",
                client_id, put_order_id, call_result,
            )
            if put_order_id:
                try:
                    self.alpaca.cancel_order(put_order_id)
                    logger.info("ExecutionEngine: put wing cancel requested for order_id=%s", put_order_id)
                except Exception as cancel_err:
                    logger.error(
                        "ExecutionEngine: CRITICAL — put wing cancel FAILED for order_id=%s: %s. Manual intervention required.",
                        put_order_id, cancel_err,
                    )
            return {"status": "partial_error", "put_result": put_result, "call_result": call_result}

        return {
            "status": "submitted",
            "order_id": put_result.get("order_id"),
            "call_order_id": call_result.get("order_id"),
        }

    def _submit_straddle(self, opp: Dict, contracts: int, credit: float, client_id: str) -> Dict:
        """Submit straddle/strangle as two single-leg orders (call + put).

        For long positions (debit): buy-to-open both legs, limit_price is max per leg.
        For short positions (credit): sell-to-open both legs, limit_price is min per leg.
        Same rollback pattern as IC: if second leg fails, cancel first.
        """
        ticker = opp.get("ticker", "UNK")
        expiration = str(opp.get("expiration", "")).split(" ")[0]
        spread_type = opp.get("type", opp.get("strategy_type", "short_straddle"))
        call_strike = round(float(opp.get("call_strike", 0) or 0), 2)
        put_strike = round(float(opp.get("put_strike", 0) or 0), 2)
        is_long = spread_type.startswith("long_")
        is_debit = opp.get("is_debit", is_long)

        # Determine order sides: long=buy-to-open, short=sell-to-open
        if is_long:
            call_side, put_side = "buy", "buy"
        else:
            call_side, put_side = "sell", "sell"

        # Per-leg limit price: split total credit/debit evenly between legs.
        # For buy orders: limit_price = max we'll pay per contract.
        # For sell orders: limit_price = min we'll accept per contract.
        # abs() ensures positive regardless of credit (positive) or debit (negative).
        per_leg_limit = round(abs(credit / 2), 2) if credit else None

        direction_label = "DEBIT (buy-to-open)" if is_debit else "CREDIT (sell-to-open)"
        logger.info(
            "ExecutionEngine: submitting straddle %s | %s | call=$%.2f put=$%.2f "
            "x%d | %s | per_leg_limit=%s",
            client_id, spread_type, call_strike, put_strike,
            contracts, direction_label, per_leg_limit,
        )

        # Submit call leg
        call_result = self.alpaca.submit_single_leg(
            ticker=ticker,
            strike=call_strike,
            expiration=expiration,
            option_type="call",
            side=call_side,
            contracts=contracts,
            limit_price=per_leg_limit,
            client_order_id=client_id + "-call",
        )

        if call_result.get("status") != "submitted":
            logger.error(
                "ExecutionEngine: call leg failed for straddle %s: %s",
                client_id, call_result,
            )
            return {"status": "partial_error", "call_result": call_result, "put_result": None}

        # Submit put leg
        put_result = self.alpaca.submit_single_leg(
            ticker=ticker,
            strike=put_strike,
            expiration=expiration,
            option_type="put",
            side=put_side,
            contracts=contracts,
            limit_price=per_leg_limit,
            client_order_id=client_id + "-put",
        )

        if put_result.get("status") != "submitted":
            call_order_id = call_result.get("order_id")
            logger.error(
                "ExecutionEngine: put leg failed for straddle %s — "
                "attempting to cancel call leg order_id=%s: %s",
                client_id, call_order_id, put_result,
            )
            if call_order_id:
                try:
                    self.alpaca.cancel_order(call_order_id)
                    logger.info("ExecutionEngine: call leg cancel requested for order_id=%s", call_order_id)
                except Exception as cancel_err:
                    logger.error(
                        "ExecutionEngine: CRITICAL — call leg cancel FAILED for order_id=%s: %s. "
                        "Manual intervention required.",
                        call_order_id, cancel_err,
                    )
            return {"status": "partial_error", "call_result": call_result, "put_result": put_result}

        return {
            "status": "submitted",
            "order_id": call_result.get("order_id"),
            "put_order_id": put_result.get("order_id"),
        }
