"""
Alert Generator
Creates formatted alerts for credit spread opportunities.
"""

import csv
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from shared.constants import OUTPUT_DIR as _OUTPUT_DIR
from shared.database import init_db, insert_alert

logger = logging.getLogger(__name__)


class AlertGenerator:
    """
    Generate and format trade alerts in multiple formats.
    """

    def __init__(self, config: Dict):
        """
        Initialize alert generator.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.alert_config = config['alerts']
        self.min_alert_score = config.get('alerts', {}).get('min_score', 28)
        self.max_alerts = config.get('alerts', {}).get('max_alerts', 5)

        # Ensure output directory exists
        self.output_dir = Path(_OUTPUT_DIR)
        self.output_dir.mkdir(exist_ok=True)

        init_db()
        logger.info("AlertGenerator initialized")

    def generate_alerts(self, opportunities: List[Dict]) -> Dict:
        """
        Generate alerts for all opportunities.

        Args:
            opportunities: List of spread opportunities

        Returns:
            Dictionary with alert outputs
        """
        if not opportunities:
            logger.info("No opportunities to generate alerts for")
            return {}

        # Filter top opportunities by minimum score (configurable via alerts.min_score)
        top_opportunities = [
            opp for opp in opportunities
            if opp.get('score', 0) >= self.min_alert_score
        ][:self.max_alerts]

        if not top_opportunities:
            logger.info("No high-quality opportunities found")
            return {}

        alerts = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'opportunities': top_opportunities,
            'count': len(top_opportunities),
        }

        # Persist to SQLite
        for opp in top_opportunities:
            try:
                insert_alert(opp)
            except Exception as e:
                logger.warning(f"Failed to insert alert to DB: {e}")

        # Generate file outputs (text and CSV only; JSON alerts live in SQLite)
        outputs = {}

        if self.alert_config.get('output_text'):
            text_output = self._generate_text(alerts)
            outputs['text'] = text_output

        if self.alert_config.get('output_csv'):
            csv_output = self._generate_csv(alerts)
            outputs['csv'] = csv_output

        logger.info(f"Generated {len(top_opportunities)} alerts")

        return outputs

    @staticmethod
    def _safe(opp: Dict, key: str, default=0.0):
        """Return opp[key] if present, else default. Never raises KeyError."""
        return opp.get(key, default)

    def _generate_text(self, alerts: Dict) -> str:
        """
        Generate human-readable text alerts.
        """
        text_file = self.output_dir / self.alert_config['text_file']

        lines = []
        lines.append("=" * 80)
        lines.append("CREDIT SPREAD TRADING ALERTS")
        lines.append(f"Generated: {alerts['timestamp']}")
        lines.append(f"Total Opportunities: {alerts['count']}")
        lines.append("=" * 80)
        lines.append("")

        for i, opp in enumerate(alerts['opportunities'], 1):
            g = lambda key, default=0.0: self._safe(opp, key, default)  # noqa: E731

            opp_type = g('type', 'unknown')
            short_strike = g('short_strike')
            long_strike  = g('long_strike')
            credit       = g('credit')
            spread_width = g('spread_width', abs(short_strike - long_strike))

            lines.append(f"ALERT #{i} - {g('ticker', 'N/A')} {opp_type.upper()}")
            lines.append("-" * 80)

            lines.append(f"Score: {g('score'):.1f}/100")
            lines.append(f"Expiration: {g('expiration', 'N/A')} (DTE: {g('dte')})")
            lines.append("")

            lines.append("TRADE SETUP:")
            if opp_type == 'iron_condor':
                lines.append(f"  Sell ${short_strike:.2f} Put / Buy ${long_strike:.2f} Put  (Bull Put Wing)")
                lines.append(f"  Sell ${g('call_short_strike'):.2f} Call / Buy ${g('call_long_strike'):.2f} Call (Bear Call Wing)")
                lines.append(f"  Combined Credit: ${credit:.2f}")
                put_breakeven  = short_strike - credit
                call_breakeven = g('call_short_strike') + credit
                lines.append(f"  Breakevens: ${put_breakeven:.2f} / ${call_breakeven:.2f}")
            elif opp_type == 'bull_put_spread':
                lines.append(f"  Sell ${short_strike:.2f} Put")
                lines.append(f"  Buy  ${long_strike:.2f} Put")
            else:  # bear_call_spread
                lines.append(f"  Sell ${short_strike:.2f} Call")
                lines.append(f"  Buy  ${long_strike:.2f} Call")

            lines.append(f"  Spread Width: ${spread_width}")
            if opp_type != 'iron_condor':
                lines.append(f"  Credit Target: ${credit:.2f} per spread")
            lines.append("")

            lines.append("RISK/REWARD:")
            lines.append(f"  Max Profit: ${g('max_profit'):.2f} (100% of credit)")
            lines.append(f"  Profit Target: ${g('profit_target'):.2f} (50% of credit)")
            lines.append(f"  Max Loss: ${g('max_loss'):.2f}")
            lines.append(f"  Stop Loss: ${g('stop_loss'):.2f}")
            lines.append(f"  Risk/Reward: 1:{g('risk_reward'):.2f}")
            lines.append("")

            lines.append("PROBABILITIES:")
            lines.append(f"  Short Strike Delta: {g('short_delta'):.3f}")
            lines.append(f"  Probability of Profit: {g('pop'):.1f}%")
            lines.append("")

            lines.append("MARKET CONTEXT:")
            lines.append(f"  Current Price: ${g('current_price'):.2f}")
            lines.append(f"  Distance to Short Strike: ${g('distance_to_short'):.2f}")
            lines.append("")

            lines.append("=" * 80)
            lines.append("")

        text_content = "\n".join(lines)

        fd, tmp_path = tempfile.mkstemp(dir=text_file.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(text_content)
            os.replace(tmp_path, text_file)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info(f"Text alerts saved to {text_file}")

        return str(text_file)

    def _generate_csv(self, alerts: Dict) -> str:
        """
        Generate CSV formatted alerts.
        """
        csv_file = self.output_dir / self.alert_config['csv_file']

        fieldnames = [
            'timestamp', 'ticker', 'type', 'expiration', 'dte',
            'short_strike', 'long_strike', 'short_delta', 'credit',
            'max_profit', 'max_loss', 'profit_target', 'stop_loss',
            'risk_reward', 'pop', 'score', 'current_price', 'distance_to_short'
        ]

        fd, tmp_path = tempfile.mkstemp(dir=csv_file.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for opp in alerts['opportunities']:
                    row = {k: opp.get(k, '') for k in fieldnames}
                    row['timestamp'] = alerts['timestamp']
                    row['expiration'] = str(opp.get('expiration', ''))
                    writer.writerow(row)
            os.replace(tmp_path, csv_file)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info(f"CSV alerts saved to {csv_file}")

        return str(csv_file)

    def format_telegram_message(self, opportunity: Dict) -> str:
        """
        Format a single opportunity for Telegram.

        Args:
            opportunity: Spread opportunity data

        Returns:
            Formatted message string
        """
        g = lambda key, default=0.0: self._safe(opportunity, key, default)  # noqa: E731
        opp_type = g('type', 'unknown')

        msg_lines = []

        # Header with emoji
        if opp_type == 'iron_condor':
            emoji = "\U0001f7e1"  # yellow circle for neutral
        elif opp_type == 'bull_put_spread':
            emoji = "\U0001f535"
        else:
            emoji = "\U0001f534"
        msg_lines.append(f"{emoji} <b>{g('ticker', 'N/A')} {opp_type.replace('_', ' ').upper()}</b>")
        msg_lines.append(f"Score: {g('score'):.1f}/100 \u2b50")
        msg_lines.append("")

        # Trade setup
        msg_lines.append("\U0001f4cb <b>TRADE:</b>")
        if opp_type == 'iron_condor':
            msg_lines.append(f"  Sell ${g('short_strike'):.2f} Put / Buy ${g('long_strike'):.2f} Put")
            msg_lines.append(f"  Sell ${g('call_short_strike'):.2f} Call / Buy ${g('call_long_strike'):.2f} Call")
        elif opp_type == 'bull_put_spread':
            msg_lines.append(f"  Sell ${g('short_strike'):.2f} Put")
            msg_lines.append(f"  Buy  ${g('long_strike'):.2f} Put")
        else:
            msg_lines.append(f"  Sell ${g('short_strike'):.2f} Call")
            msg_lines.append(f"  Buy  ${g('long_strike'):.2f} Call")

        msg_lines.append(f"  Exp: {g('expiration', 'N/A')} ({g('dte')} DTE)")
        msg_lines.append(f"  Credit: ${g('credit'):.2f}")
        msg_lines.append("")

        # Risk/Reward
        msg_lines.append("\U0001f4b0 <b>RISK/REWARD:</b>")
        msg_lines.append(f"  Max Profit: ${g('max_profit'):.2f}")
        msg_lines.append(f"  Target (50%): ${g('profit_target'):.2f}")
        msg_lines.append(f"  Max Loss: ${g('max_loss'):.2f}")
        msg_lines.append(f"  R/R: 1:{g('risk_reward'):.2f}")
        msg_lines.append("")

        # Probabilities
        msg_lines.append("\U0001f4ca <b>PROBABILITY:</b>")
        msg_lines.append(f"  POP: {g('pop'):.1f}%")
        msg_lines.append(f"  Delta: {g('short_delta'):.3f}")

        return "\n".join(msg_lines)
