"""
Rich Telegram alert formatter following the MASTERPLAN format spec.

Produces HTML-formatted messages for entry alerts, exit alerts, and
daily summary reports.
"""

from alerts.alert_schema import Alert, AlertType


# Color-code emojis by alert type
_TYPE_EMOJI = {
    AlertType.credit_spread: "\U0001f7e2",    # green circle
    AlertType.momentum_swing: "\U0001f535",    # blue circle
    AlertType.iron_condor: "\U0001f7e1",       # yellow circle
    AlertType.earnings_play: "\U0001f7e0",     # orange circle
    AlertType.gamma_lotto: "\U0001f534",       # red circle
}

_TYPE_LABEL = {
    AlertType.credit_spread: "CREDIT SPREAD",
    AlertType.momentum_swing: "MOMENTUM SWING",
    AlertType.iron_condor: "IRON CONDOR",
    AlertType.earnings_play: "EARNINGS PLAY",
    AlertType.gamma_lotto: "GAMMA LOTTO",
}


class TelegramAlertFormatter:
    """Formats alerts as Telegram HTML messages per MASTERPLAN spec."""

    # ------------------------------------------------------------------
    # Entry alert
    # ------------------------------------------------------------------

    def format_entry_alert(self, alert: Alert) -> str:
        """Format a full entry alert with all 8 MASTERPLAN elements."""
        emoji = _TYPE_EMOJI.get(alert.type, "\u26aa")
        label = _TYPE_LABEL.get(alert.type, alert.type.value.upper())
        lines: list[str] = []

        # Header
        lines.append(
            f"{emoji} <b>{alert.ticker} {label}</b> "
            f"({alert.confidence.value})"
        )
        lines.append(f"Score: {alert.score:.0f}/100")
        lines.append("")

        # 1 — Direction
        lines.append(f"\U0001f9ed <b>Direction:</b> {alert.direction.value.upper()}")
        lines.append("")

        # 2 — Legs
        lines.append("\U0001f4cb <b>TRADE:</b>")
        for leg in alert.legs:
            action = leg.action.upper()
            opt = leg.option_type.upper()
            lines.append(f"  {action} ${leg.strike:.2f} {opt}")
        lines.append(f"  Exp: {alert.legs[0].expiration}")
        if alert.type in (AlertType.momentum_swing, AlertType.gamma_lotto):
            lines.append(f"  Debit: ${alert.entry_price:.2f}")
        else:
            lines.append(f"  Credit: ${alert.entry_price:.2f}")
        lines.append("")

        # 3 — Risk / reward
        lines.append("\U0001f4b0 <b>RISK / REWARD:</b>")
        lines.append(f"  Stop Loss: ${alert.stop_loss:.2f}")
        lines.append(f"  Profit Target: ${alert.profit_target:.2f}")
        lines.append(f"  Risk: {alert.risk_pct:.1%} of account")
        if alert.sizing:
            lines.append(f"  Contracts: {alert.sizing.contracts}")
            lines.append(f"  Max Loss: ${alert.sizing.max_loss:.2f}")
        lines.append("")

        # 4 — Thesis
        lines.append(f"\U0001f4a1 <b>Thesis:</b> {alert.thesis}")
        lines.append("")

        # 5 — Management
        lines.append(f"\u2699\ufe0f <b>Management:</b> {alert.management_instructions}")
        lines.append("")

        # 6 — Time sensitivity
        lines.append(
            f"\u23f0 <b>Time:</b> {alert.time_sensitivity.value.replace('_', ' ')}"
        )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Exit alert
    # ------------------------------------------------------------------

    def format_exit_alert(
        self,
        ticker: str,
        action: str,
        current_pnl: float,
        pnl_pct: float,
        reason: str,
        instructions: str,
    ) -> str:
        """Format an exit / management alert."""
        pnl_emoji = "\U0001f4c8" if current_pnl >= 0 else "\U0001f4c9"
        sign = "+" if current_pnl >= 0 else "-"

        lines: list[str] = []
        lines.append(f"{pnl_emoji} <b>{ticker} — {action.upper()}</b>")
        lines.append("")
        lines.append(
            f"P&L: {sign}${abs(current_pnl):.2f} ({sign}{abs(pnl_pct):.1f}%)"
        )
        lines.append(f"Reason: {reason}")
        lines.append("")
        lines.append(f"\u2699\ufe0f <b>Instructions:</b> {instructions}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Daily summary
    # ------------------------------------------------------------------

    def format_daily_summary(
        self,
        date: str,
        alerts_fired: int,
        closed_today: int,
        wins: int,
        losses: int,
        day_pnl: float,
        day_pnl_pct: float,
        open_positions: int,
        total_risk_pct: float,
        account_balance: float,
        pct_from_start: float,
        best: str,
        worst: str,
    ) -> str:
        """Format the end-of-day summary."""
        pnl_emoji = "\U0001f4c8" if day_pnl >= 0 else "\U0001f4c9"
        sign = "+" if day_pnl >= 0 else "-"
        start_sign = "+" if pct_from_start >= 0 else "-"

        lines: list[str] = []
        lines.append(f"\U0001f4ca <b>DAILY SUMMARY — {date}</b>")
        lines.append("")
        lines.append(
            f"{pnl_emoji} Day P&L: {sign}${abs(day_pnl):.2f} "
            f"({sign}{abs(day_pnl_pct):.1f}%)"
        )
        lines.append(f"Alerts fired: {alerts_fired}")
        lines.append(f"Closed today: {closed_today} (W:{wins} / L:{losses})")
        lines.append("")
        lines.append(f"\U0001f4bc <b>PORTFOLIO:</b>")
        lines.append(f"  Open positions: {open_positions}")
        lines.append(f"  Total risk: {total_risk_pct:.1f}%")
        lines.append(
            f"  Balance: ${account_balance:,.2f} "
            f"({start_sign}{abs(pct_from_start):.1f}%)"
        )
        lines.append("")
        lines.append(f"\U0001f3c6 Best: {best}")
        lines.append(f"\U0001f4a5 Worst: {worst}")

        return "\n".join(lines)
