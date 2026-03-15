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
    AlertType.straddle_strangle: "\U0001f7e3",          # purple circle
}

_TYPE_LABEL = {
    AlertType.credit_spread: "CREDIT SPREAD",
    AlertType.momentum_swing: "MOMENTUM SWING",
    AlertType.iron_condor: "IRON CONDOR",
    AlertType.earnings_play: "EARNINGS PLAY",
    AlertType.gamma_lotto: "GAMMA LOTTO",
    AlertType.straddle_strangle: "STRADDLE/STRANGLE",
}

# Alert types that are debit (buy-to-open) positions
_DEBIT_TYPES = {AlertType.momentum_swing, AlertType.gamma_lotto}


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
        if alert.legs:
            lines.append(f"  Exp: {alert.legs[0].expiration}")

        # Straddle-specific: show debit/credit based on direction + breakevens
        if alert.type == AlertType.straddle_strangle:
            self._format_straddle_details(alert, lines)
        elif alert.type in _DEBIT_TYPES:
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

    def _format_straddle_details(self, alert: Alert, lines: list) -> None:
        """Add straddle-specific details: debit/credit, breakevens, event, regime."""
        # Determine direction from legs or metadata
        is_debit = alert.entry_price < 0 or any(
            leg.action.lower() == "buy" for leg in alert.legs
        )

        if is_debit:
            lines.append(f"  Debit: ${abs(alert.entry_price):.2f}")
        else:
            lines.append(f"  Credit: ${alert.entry_price:.2f}")

        # Calculate breakevens from legs
        call_strike = None
        put_strike = None
        for leg in alert.legs:
            if leg.option_type.lower() == "call":
                call_strike = leg.strike
            elif leg.option_type.lower() == "put":
                put_strike = leg.strike

        if call_strike and put_strike:
            premium = abs(alert.entry_price)
            if is_debit:
                # Long straddle: breakevens at strike ± total premium
                lines.append(f"  Upper BE: ${call_strike + premium:.2f}")
                lines.append(f"  Lower BE: ${put_strike - premium:.2f}")
            else:
                # Short straddle: breakevens at strike ± total credit
                lines.append(f"  Upper BE: ${call_strike + premium:.2f}")
                lines.append(f"  Lower BE: ${put_strike - premium:.2f}")

        # Event type and regime from metadata
        metadata = getattr(alert, "metadata", {}) or {}
        event_type = metadata.get("event_type")
        regime = metadata.get("regime")
        if event_type:
            lines.append(f"  Event: {event_type.upper()}")
        if regime:
            lines.append(f"  Regime: {regime}")

    # ------------------------------------------------------------------
    # Straddle trade open notification
    # ------------------------------------------------------------------

    def format_straddle_open(self, trade: dict) -> str:
        """Format a straddle trade open notification."""
        ticker = trade.get("ticker", "?")
        spread = trade.get("type", "straddle").replace("_", " ").title()
        credit = float(trade.get("credit", 0) or 0)
        is_debit = trade.get("is_debit", False) or credit < 0
        call_strike = trade.get("call_strike", "?")
        put_strike = trade.get("put_strike", "?")
        contracts = trade.get("contracts", "?")
        dte = trade.get("dte_at_entry", "?")
        event_type = trade.get("event_type", "")

        direction = "LONG (debit)" if is_debit else "SHORT (credit)"
        emoji = "\U0001f7e3"  # purple circle

        lines = [
            f"{emoji} <b>NEW TRADE: {ticker} {spread}</b>",
            "",
            f"Direction: {direction}",
            f"Call: ${call_strike}",
            f"Put: ${put_strike}",
            f"Contracts: {contracts}",
        ]

        if is_debit:
            lines.append(f"Debit: ${abs(credit) * int(contracts or 1) * 100:.2f}")
        else:
            lines.append(f"Credit: ${credit * int(contracts or 1) * 100:.2f}")

        lines.append(f"DTE: {dte}")

        if event_type:
            lines.append(f"Event: {event_type.upper()}")

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
        lines.append("\U0001f4bc <b>PORTFOLIO:</b>")
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

    # ------------------------------------------------------------------
    # Pre-event warning
    # ------------------------------------------------------------------

    def format_event_warning(self, events: list) -> str:
        """Format a pre-event heads-up alert."""
        lines = ["\u26a0\ufe0f <b>UPCOMING ECONOMIC EVENTS</b>", ""]

        for event in events:
            event_type = event.get("event_type", "unknown").upper()
            event_date = event.get("date")
            description = event.get("description", "")
            importance = event.get("importance", 0.5)

            date_str = event_date.strftime("%Y-%m-%d %H:%M UTC") if hasattr(event_date, "strftime") else str(event_date)
            importance_label = "HIGH" if importance >= 0.85 else "MEDIUM" if importance >= 0.70 else "LOW"

            lines.append(f"\U0001f4c5 <b>{event_type}</b> — {date_str}")
            lines.append(f"  {description} ({importance_label} impact)")
            lines.append("")

        lines.append("Straddle/strangle opportunities may arise.")
        return "\n".join(lines)
