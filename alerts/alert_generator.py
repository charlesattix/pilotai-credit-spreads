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
from shared.database import init_db, insert_alert
from shared.constants import OUTPUT_DIR as _OUTPUT_DIR

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

        # Filter top opportunities (top 5 or score > 40)
        top_opportunities = [
            opp for opp in opportunities
            if opp.get('score', 0) >= 40
        ][:5]

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
            lines.append(f"ALERT #{i} - {opp['ticker']} {opp['type'].upper()}")
            lines.append("-" * 80)

            lines.append(f"Score: {opp['score']:.1f}/100")
            lines.append(f"Expiration: {opp['expiration']} (DTE: {opp['dte']})")
            lines.append("")

            lines.append("TRADE SETUP:")
            if opp['type'] == 'iron_condor':
                lines.append(f"  Sell ${opp['short_strike']:.2f} Put / Buy ${opp['long_strike']:.2f} Put  (Bull Put Wing)")
                lines.append(f"  Sell ${opp['call_short_strike']:.2f} Call / Buy ${opp['call_long_strike']:.2f} Call (Bear Call Wing)")
                lines.append(f"  Combined Credit: ${opp['credit']:.2f}")
                # Breakevens
                put_breakeven = opp['short_strike'] - opp['credit']
                call_breakeven = opp['call_short_strike'] + opp['credit']
                lines.append(f"  Breakevens: ${put_breakeven:.2f} / ${call_breakeven:.2f}")
            elif opp['type'] == 'bull_put_spread':
                lines.append(f"  Sell ${opp['short_strike']:.2f} Put")
                lines.append(f"  Buy  ${opp['long_strike']:.2f} Put")
            else:  # bear_call_spread
                lines.append(f"  Sell ${opp['short_strike']:.2f} Call")
                lines.append(f"  Buy  ${opp['long_strike']:.2f} Call")

            lines.append(f"  Spread Width: ${opp['spread_width']}")
            if opp['type'] != 'iron_condor':
                lines.append(f"  Credit Target: ${opp['credit']:.2f} per spread")
            lines.append("")

            lines.append("RISK/REWARD:")
            lines.append(f"  Max Profit: ${opp['max_profit']:.2f} (100% of credit)")
            lines.append(f"  Profit Target: ${opp['profit_target']:.2f} (50% of credit)")
            lines.append(f"  Max Loss: ${opp['max_loss']:.2f}")
            lines.append(f"  Stop Loss: ${opp['stop_loss']:.2f}")
            lines.append(f"  Risk/Reward: 1:{opp['risk_reward']:.2f}")
            lines.append("")

            lines.append("PROBABILITIES:")
            lines.append(f"  Short Strike Delta: {opp['short_delta']:.3f}")
            lines.append(f"  Probability of Profit: {opp['pop']:.1f}%")
            lines.append("")

            lines.append("MARKET CONTEXT:")
            lines.append(f"  Current Price: ${opp['current_price']:.2f}")
            lines.append(f"  Distance to Short Strike: ${opp['distance_to_short']:.2f}")
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
                    row['expiration'] = str(opp['expiration'])
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
        msg_lines = []

        # Header with emoji
        if opportunity['type'] == 'iron_condor':
            emoji = "\U0001f7e1"  # yellow circle for neutral
        elif opportunity['type'] == 'bull_put_spread':
            emoji = "\U0001f535"
        else:
            emoji = "\U0001f534"
        msg_lines.append(f"{emoji} <b>{opportunity['ticker']} {opportunity['type'].replace('_', ' ').upper()}</b>")
        msg_lines.append(f"Score: {opportunity['score']:.1f}/100 \u2b50")
        msg_lines.append("")

        # Trade setup
        msg_lines.append("\U0001f4cb <b>TRADE:</b>")
        if opportunity['type'] == 'iron_condor':
            msg_lines.append(f"  Sell ${opportunity['short_strike']:.2f} Put / Buy ${opportunity['long_strike']:.2f} Put")
            msg_lines.append(f"  Sell ${opportunity['call_short_strike']:.2f} Call / Buy ${opportunity['call_long_strike']:.2f} Call")
        elif opportunity['type'] == 'bull_put_spread':
            msg_lines.append(f"  Sell ${opportunity['short_strike']:.2f} Put")
            msg_lines.append(f"  Buy  ${opportunity['long_strike']:.2f} Put")
        else:
            msg_lines.append(f"  Sell ${opportunity['short_strike']:.2f} Call")
            msg_lines.append(f"  Buy  ${opportunity['long_strike']:.2f} Call")

        msg_lines.append(f"  Exp: {opportunity['expiration']} ({opportunity['dte']} DTE)")
        msg_lines.append(f"  Credit: ${opportunity['credit']:.2f}")
        msg_lines.append("")

        # Risk/Reward
        msg_lines.append("\U0001f4b0 <b>RISK/REWARD:</b>")
        msg_lines.append(f"  Max Profit: ${opportunity['max_profit']:.2f}")
        msg_lines.append(f"  Target (50%): ${opportunity['profit_target']:.2f}")
        msg_lines.append(f"  Max Loss: ${opportunity['max_loss']:.2f}")
        msg_lines.append(f"  R/R: 1:{opportunity['risk_reward']:.2f}")
        msg_lines.append("")

        # Probabilities
        msg_lines.append("\U0001f4ca <b>PROBABILITY:</b>")
        msg_lines.append(f"  POP: {opportunity['pop']:.1f}%")
        msg_lines.append(f"  Delta: {opportunity['short_delta']:.3f}")

        return "\n".join(msg_lines)
