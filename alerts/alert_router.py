"""
Central alert routing pipeline.

Pipeline stages:
  1. Convert opportunity dicts → Alert objects
  2. Deduplicate (same ticker+direction within 30 min, persisted across restarts)
  3. Position sizing  ← moved before risk gate so risk_pct reflects real sized risk
  4. Update alert.risk_pct from sizing result (BUG #7 fix)
  5. Risk-gate check (now sees real risk_pct)
  6. Prioritize (by type priority, then score)
  7. Dispatch (Telegram + SQLite persistence)
  8. Execute (optional — submit orders to Alpaca via ExecutionEngine)
     Dedup ledger is only marked AFTER successful execution (BUG #15 fix)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.database import insert_alert, upsert_dedup_entry, load_dedup_entries, delete_old_dedup_entries
from alerts.alert_schema import Alert, AlertType
from alerts.risk_gate import RiskGate
from alerts.alert_position_sizer import AlertPositionSizer
from alerts.formatters.telegram import TelegramAlertFormatter

logger = logging.getLogger(__name__)

# Type priority order (lower index = higher priority)
_TYPE_PRIORITY = {
    AlertType.credit_spread: 0,
    AlertType.iron_condor: 1,
    AlertType.momentum_swing: 2,
    AlertType.earnings_play: 3,
    AlertType.gamma_lotto: 4,
}

# Dedup window in seconds
_DEDUP_WINDOW = 30 * 60  # 30 minutes


class AlertRouter:
    """Central pipeline: validate → dedup → risk-check → size → prioritize → dispatch → execute."""

    def __init__(
        self,
        risk_gate: RiskGate,
        position_sizer: AlertPositionSizer,
        telegram_bot,
        formatter: TelegramAlertFormatter,
        execution_engine=None,
        config: Optional[Dict] = None,
    ):
        self.risk_gate = risk_gate
        self.position_sizer = position_sizer
        self.telegram_bot = telegram_bot
        self.formatter = formatter
        self.execution_engine = execution_engine  # None = alert-only mode
        self.config = config or {}

        # In-memory dedup ledger: (ticker, direction) → last_routed_at
        # Populated from SQLite on startup so restarts don't lose dedup state (BUG #17).
        self._dedup_ledger: Dict[tuple, datetime] = {}
        self._load_dedup_from_db()

    def route_opportunities(
        self,
        opportunities: List[dict],
        account_state: dict,
        iv_rank: float = 30.0,
    ) -> List[Alert]:
        """Run the full routing pipeline.

        Args:
            opportunities: Raw opportunity dicts from the scanner.
            account_state: Account state dict for risk checks.
            iv_rank: Current IV rank (0–100) for position sizing.

        Returns:
            List of successfully dispatched Alert objects.
        """
        account_value = account_state.get("account_value", 0)
        current_portfolio_risk = sum(
            p.get("risk_pct", 0) * account_value
            for p in account_state.get("open_positions", [])
        )
        weekly_breach = self.risk_gate.weekly_loss_breach(account_state)

        # 1. Convert — only opportunities with score >= 60
        alerts: List[Alert] = []
        for opp in opportunities:
            if opp.get("score", 0) < 60:
                continue
            try:
                alert = Alert.from_opportunity(opp)
                alerts.append(alert)
            except Exception as e:
                logger.warning("Failed to convert opportunity %s: %s", opp.get("ticker"), e)

        if not alerts:
            logger.info("AlertRouter: no qualifying opportunities (score >= 60)")
            return []

        # 2. Deduplicate
        now = datetime.now(timezone.utc)
        deduped: List[Alert] = []
        for alert in alerts:
            key = (alert.ticker, alert.direction.value)
            last_routed = self._dedup_ledger.get(key)
            if last_routed and (now - last_routed).total_seconds() < _DEDUP_WINDOW:
                logger.debug("AlertRouter: dedup skip %s %s", alert.ticker, alert.direction.value)
                continue
            deduped.append(alert)

        # 3. Size FIRST — so risk gate sees the real position-sized risk_pct (BUG #7 fix).
        #    Pipeline order changed: Size → update risk_pct → Risk gate.
        for alert in deduped:
            try:
                sizing = self.position_sizer.size(
                    alert=alert,
                    account_value=account_value,
                    iv_rank=iv_rank,
                    current_portfolio_risk=current_portfolio_risk,
                    weekly_loss_breach=weekly_breach,
                )
                alert.sizing = sizing
                # Update risk_pct on the alert with the real sized value so that
                # risk gate rules 1 & 2 enforce actual exposure, not the default 2%.
                if sizing and sizing.risk_pct > 0:
                    alert.risk_pct = sizing.risk_pct
            except Exception as e:
                logger.warning("AlertRouter: sizing failed for %s: %s", alert.ticker, e)

        # 4. Risk-check (now has real risk_pct from step 3)
        approved: List[Alert] = []
        for alert in deduped:
            passed, reason = self.risk_gate.check(alert, account_state)
            if passed:
                approved.append(alert)
            else:
                logger.info("AlertRouter: rejected %s — %s", alert.ticker, reason)

        # 5. Prioritize — by type priority then score, take top 5
        approved.sort(
            key=lambda a: (_TYPE_PRIORITY.get(a.type, 99), -a.score)
        )
        top = approved[:5]

        # 6. Dispatch
        dispatched: List[Alert] = []
        for alert in top:
            try:
                msg = self.formatter.format_entry_alert(alert)
                self.telegram_bot.send_alert(msg)
            except Exception as e:
                logger.warning("AlertRouter: Telegram send failed for %s: %s", alert.ticker, e)

            try:
                insert_alert(alert.to_dict())
            except Exception as e:
                logger.warning("AlertRouter: DB persist failed for %s: %s", alert.ticker, e)

            # 7. Execute — dedup ledger is only marked AFTER successful execution (BUG #15 fix).
            #    If Alpaca rejects the order, the next scan can retry.
            execution_succeeded = True
            if self.execution_engine:
                dte_ok, dte_reason = self._validate_dte(alert)
                if not dte_ok:
                    logger.warning(
                        "AlertRouter: DTE gate blocked execution for %s — %s",
                        alert.ticker, dte_reason,
                    )
                    # DTE-blocked: mark dedup (alert was valid, DTE is deterministic)
                    self._mark_dedup(alert.ticker, alert.direction.value, now)
                    dispatched.append(alert)
                    continue
                try:
                    opp_dict = self._build_execution_dict(alert)
                    if alert.sizing:
                        opp_dict["contracts"] = alert.sizing.contracts
                    result = self.execution_engine.submit_opportunity(opp_dict)
                    exec_status = result.get("status", "unknown")
                    logger.info(
                        "AlertRouter: execution %s for %s (%s)",
                        exec_status, alert.ticker, result.get("client_order_id", ""),
                    )
                    alert.execution_result = result
                    if exec_status not in ("submitted", "accepted", "pending_new"):
                        execution_succeeded = False
                except Exception as e:
                    logger.error("AlertRouter: execution failed for %s: %s", alert.ticker, e)
                    execution_succeeded = False

            # Only mark dedup when execution actually succeeded (or no engine configured)
            if execution_succeeded:
                self._mark_dedup(alert.ticker, alert.direction.value, now)
            else:
                logger.info(
                    "AlertRouter: skipping dedup mark for %s — execution failed, will retry next scan",
                    alert.ticker,
                )

            dispatched.append(alert)

        logger.info("AlertRouter: dispatched %d alerts", len(dispatched))
        return dispatched

    # ------------------------------------------------------------------
    # Execution dict builder
    # ------------------------------------------------------------------

    def _build_execution_dict(self, alert: Alert) -> dict:
        """Build an execution-ready dict from an Alert for ExecutionEngine.

        Alert.to_dict() (via asdict()) stores expiration/strikes/credit inside
        legs[], not at the top level.  ExecutionEngine.submit_opportunity()
        reads top-level keys: expiration, short_strike, long_strike, credit,
        and type (as spread_type).  This method extracts those fields from legs
        and promotes them to the top level so execution works correctly.
        """
        d = alert.to_dict()
        legs = d.get("legs", [])

        # --- expiration: take from first leg ---
        if not d.get("expiration") and legs:
            d["expiration"] = str(legs[0].get("expiration", "")).split(" ")[0]

        # --- spread_type: map direction → bull_put / bear_call ---
        # Alert.type is "credit_spread" or "iron_condor"; execution engine needs
        # "bull_put" / "bear_call" / "iron_condor" to determine option type.
        alert_type_val = d.get("type", "")
        if "condor" not in alert_type_val:
            d["type"] = "bull_put" if alert.direction.value == "bullish" else "bear_call"

        # --- strikes: extract sell leg → short, buy leg → long ---
        sell_legs = [l for l in legs if l.get("action") == "sell"]
        buy_legs = [l for l in legs if l.get("action") == "buy"]
        if sell_legs and not d.get("short_strike"):
            d["short_strike"] = sell_legs[0].get("strike", 0)
        if buy_legs and not d.get("long_strike"):
            d["long_strike"] = buy_legs[0].get("strike", 0)

        # --- credit: entry_price is the credit received ---
        if not d.get("credit"):
            d["credit"] = d.get("entry_price", 0)

        # --- iron condor: extract per-wing strikes from legs ---
        if "condor" in alert_type_val:
            put_legs = [l for l in legs if l.get("option_type") == "put"]
            call_legs = [l for l in legs if l.get("option_type") == "call"]
            ps = next((l for l in put_legs if l.get("action") == "sell"), None)
            pb = next((l for l in put_legs if l.get("action") == "buy"), None)
            cs = next((l for l in call_legs if l.get("action") == "sell"), None)
            cb = next((l for l in call_legs if l.get("action") == "buy"), None)
            if ps:
                d["put_short_strike"] = ps["strike"]
            if pb:
                d["put_long_strike"] = pb["strike"]
            if cs:
                d["call_short_strike"] = cs["strike"]
            if cb:
                d["call_long_strike"] = cb["strike"]

        return d

    # ------------------------------------------------------------------
    # Dedup persistence helpers (BUG #17 fix)
    # ------------------------------------------------------------------

    def _load_dedup_from_db(self) -> None:
        """Load recent dedup entries from SQLite on startup."""
        try:
            db_path = os.environ.get("PILOTAI_DB_PATH")
            delete_old_dedup_entries(window_seconds=_DEDUP_WINDOW, path=db_path)
            entries = load_dedup_entries(window_seconds=_DEDUP_WINDOW, path=db_path)
            for entry in entries:
                key = (entry["ticker"], entry["direction"])
                try:
                    ts = datetime.fromisoformat(entry["last_routed_at"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    self._dedup_ledger[key] = ts
                except (ValueError, TypeError):
                    pass
            if entries:
                logger.info("AlertRouter: loaded %d dedup entries from DB", len(entries))
        except Exception as e:
            logger.warning("AlertRouter: could not load dedup entries from DB (non-fatal): %s", e)

    def _mark_dedup(self, ticker: str, direction: str, ts: datetime) -> None:
        """Mark a (ticker, direction) pair as recently routed in memory and DB."""
        key = (ticker, direction)
        self._dedup_ledger[key] = ts
        try:
            db_path = os.environ.get("PILOTAI_DB_PATH")
            upsert_dedup_entry(ticker, direction, ts.isoformat(), path=db_path)
        except Exception as e:
            logger.warning("AlertRouter: could not persist dedup entry (non-fatal): %s", e)

    # ------------------------------------------------------------------
    # DTE validation (defense-in-depth: mirrors backtester min/max DTE)
    # ------------------------------------------------------------------

    def _validate_dte(self, alert: Alert):
        """Check that the alert's expiration is within the configured DTE window.

        Returns:
            (True, "") if DTE is acceptable or no config is set.
            (False, reason) if DTE is out of range.
        """
        strategy = self.config.get("strategy", {})
        min_dte = strategy.get("min_dte")
        max_dte = strategy.get("max_dte")

        if min_dte is None and max_dte is None:
            return True, ""  # no DTE config — pass through

        if not alert.legs:
            return True, ""  # no legs to inspect — pass through

        expiration_str = str(alert.legs[0].expiration).split(" ")[0]
        try:
            from datetime import date
            exp_date = date.fromisoformat(expiration_str)
            dte = (exp_date - date.today()).days
        except (ValueError, TypeError):
            logger.warning("AlertRouter: cannot parse expiration '%s' for DTE check", expiration_str)
            return True, ""  # cannot parse — don't block

        if min_dte is not None and dte < int(min_dte):
            return False, f"DTE={dte} < min_dte={min_dte}"
        if max_dte is not None and dte > int(max_dte):
            return False, f"DTE={dte} > max_dte={max_dte}"

        return True, ""
