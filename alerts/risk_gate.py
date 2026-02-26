"""
Risk Gate — hard-coded risk rules from the MASTERPLAN.

Every alert must pass through ``RiskGate.check()`` before dispatch.
The rules are intentionally NOT configurable; they use constants from
``shared/constants.py`` which are hard-coded per MASTERPLAN §Risk Management.
"""

import logging
from datetime import datetime, timezone

from shared.constants import (
    COOLDOWN_AFTER_STOP,
    DAILY_LOSS_LIMIT,
    MAX_CORRELATED_POSITIONS,
    MAX_RISK_PER_TRADE,
    MAX_TOTAL_EXPOSURE,
    WEEKLY_LOSS_LIMIT,
)
from alerts.alert_schema import Alert

logger = logging.getLogger(__name__)


class RiskGate:
    """Hard-coded risk gate.  No constructor config — rules come from constants."""

    def check(self, alert: Alert, account_state: dict) -> tuple:
        """Evaluate an alert against all risk rules.

        Args:
            alert: The candidate alert.
            account_state: Dict with shape::

                {
                    "account_value": float,
                    "open_positions": list[dict],
                        # each has: ticker, direction, risk_pct, entry_time
                    "daily_pnl_pct": float,
                    "weekly_pnl_pct": float,
                    "recent_stops": list[dict],
                        # each has: ticker, stopped_at (datetime)
                }

        Returns:
            ``(True, "")`` if approved.
            ``(False, reason)`` if rejected.
        """
        # 1. Per-trade risk cap
        if alert.risk_pct > MAX_RISK_PER_TRADE:
            reason = (
                f"Per-trade risk {alert.risk_pct:.2%} exceeds "
                f"max {MAX_RISK_PER_TRADE:.2%}"
            )
            logger.warning("RiskGate BLOCKED: %s", reason)
            return (False, reason)

        # 2. Total exposure (epsilon for float precision)
        open_risk = sum(
            p.get("risk_pct", 0) for p in account_state.get("open_positions", [])
        )
        if open_risk + alert.risk_pct > MAX_TOTAL_EXPOSURE + 1e-9:
            reason = (
                f"Total exposure would be {open_risk + alert.risk_pct:.2%}, "
                f"exceeds max {MAX_TOTAL_EXPOSURE:.2%}"
            )
            logger.warning("RiskGate BLOCKED: %s", reason)
            return (False, reason)

        # 3. Daily loss limit — stop all alerts for the day
        daily_pnl_pct = account_state.get("daily_pnl_pct", 0.0)
        if daily_pnl_pct < -DAILY_LOSS_LIMIT:
            reason = (
                f"Daily P&L {daily_pnl_pct:.2%} below limit "
                f"-{DAILY_LOSS_LIMIT:.2%} — no more alerts today"
            )
            logger.warning("RiskGate BLOCKED: %s", reason)
            return (False, reason)

        # 4. Weekly loss limit — flag for 50% size reduction (does not block)
        #    We set a flag on the alert but do NOT reject here.
        #    The position sizer will read this flag later.
        #    (checked externally; this method just logs)
        weekly_pnl_pct = account_state.get("weekly_pnl_pct", 0.0)
        if weekly_pnl_pct < -WEEKLY_LOSS_LIMIT:
            logger.info(
                "RiskGate FLAG: weekly P&L %s below -%s — 50%% size reduction",
                f"{weekly_pnl_pct:.2%}",
                f"{WEEKLY_LOSS_LIMIT:.2%}",
            )

        # 5. Correlated positions (same direction)
        same_direction_count = sum(
            1
            for p in account_state.get("open_positions", [])
            if p.get("direction") == alert.direction.value
        )
        if same_direction_count >= MAX_CORRELATED_POSITIONS:
            reason = (
                f"Already {same_direction_count} open {alert.direction.value} "
                f"positions (max {MAX_CORRELATED_POSITIONS})"
            )
            logger.warning("RiskGate BLOCKED: %s", reason)
            return (False, reason)

        # 6. Cooldown after stop-out on same ticker
        now = datetime.now(timezone.utc)
        for stop in account_state.get("recent_stops", []):
            if stop.get("ticker") != alert.ticker:
                continue
            stopped_at = stop.get("stopped_at")
            if isinstance(stopped_at, str):
                stopped_at = datetime.fromisoformat(stopped_at)
            if stopped_at and (now - stopped_at).total_seconds() < COOLDOWN_AFTER_STOP:
                remaining = COOLDOWN_AFTER_STOP - (now - stopped_at).total_seconds()
                reason = (
                    f"{alert.ticker} stopped out recently — "
                    f"{remaining:.0f}s remaining in cooldown"
                )
                logger.warning("RiskGate BLOCKED: %s", reason)
                return (False, reason)

        return (True, "")

    def weekly_loss_breach(self, account_state: dict) -> bool:
        """Return True if the weekly loss limit has been breached."""
        return account_state.get("weekly_pnl_pct", 0.0) < -WEEKLY_LOSS_LIMIT
