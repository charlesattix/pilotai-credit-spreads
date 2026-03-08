"""
Central alert routing pipeline.

Pipeline stages:
  1. Convert opportunity dicts → Alert objects
  2. Deduplicate (same ticker+direction within 30 min)
  3. Risk-gate check
  4. Position sizing
  5. Prioritize (by type priority, then score)
  6. Dispatch (Telegram + SQLite persistence)
  7. Execute (optional — submit orders to Alpaca via ExecutionEngine)
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.database import insert_alert
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
        self._dedup_ledger: Dict[tuple, datetime] = {}

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

        # 3. Risk-check
        approved: List[Alert] = []
        for alert in deduped:
            passed, reason = self.risk_gate.check(alert, account_state)
            if passed:
                approved.append(alert)
            else:
                logger.info("AlertRouter: rejected %s — %s", alert.ticker, reason)

        # 4. Size
        for alert in approved:
            try:
                sizing = self.position_sizer.size(
                    alert=alert,
                    account_value=account_value,
                    iv_rank=iv_rank,
                    current_portfolio_risk=current_portfolio_risk,
                    weekly_loss_breach=weekly_breach,
                )
                alert.sizing = sizing
            except Exception as e:
                logger.warning("AlertRouter: sizing failed for %s: %s", alert.ticker, e)

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

            # Mark dedup ledger
            self._dedup_ledger[(alert.ticker, alert.direction.value)] = now

            # Step 7: Execute — submit live order to Alpaca if engine is wired
            if self.execution_engine:
                dte_ok, dte_reason = self._validate_dte(alert)
                if not dte_ok:
                    logger.warning(
                        "AlertRouter: DTE gate blocked execution for %s — %s",
                        alert.ticker, dte_reason,
                    )
                    dispatched.append(alert)
                    continue
                try:
                    opp_dict = alert.to_dict()
                    # Inject contract count from sizing result
                    if alert.sizing:
                        opp_dict["contracts"] = alert.sizing.contracts
                    result = self.execution_engine.submit_opportunity(opp_dict)
                    exec_status = result.get("status", "unknown")
                    logger.info(
                        "AlertRouter: execution %s for %s (%s)",
                        exec_status, alert.ticker, result.get("client_order_id", ""),
                    )
                    alert.execution_result = result
                except Exception as e:
                    logger.error(
                        "AlertRouter: execution failed for %s: %s", alert.ticker, e
                    )

            dispatched.append(alert)

        logger.info("AlertRouter: dispatched %d alerts", len(dispatched))
        return dispatched

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
