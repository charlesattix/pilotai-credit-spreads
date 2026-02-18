"""
Performance Metrics
Calculate and display performance statistics.
"""

import logging
from pathlib import Path
from typing import Dict
import json

logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """
    Calculate and report performance metrics.
    """

    def __init__(self, config: Dict):
        """
        Initialize performance metrics calculator.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config

        logger.info("PerformanceMetrics initialized")

    def generate_report(self, backtest_results: Dict) -> str:
        """
        Generate a formatted performance report.
        
        Args:
            backtest_results: Results from backtester
            
        Returns:
            Path to generated report file
        """
        if not backtest_results:
            logger.warning("No backtest results to report")
            return ""

        # Create report directory
        report_dir = Path(self.config['backtest']['report_dir'])
        report_dir.mkdir(parents=True, exist_ok=True)

        # Generate text report
        text_report = self._generate_text_report(backtest_results)

        # Save report
        report_file = report_dir / f"backtest_report_{self._timestamp()}.txt"

        try:
            with open(report_file, 'w') as f:
                f.write(text_report)
            logger.info(f"Report generated: {report_file}")
        except OSError as e:
            logger.warning(f"Failed to write text report to {report_file}: {e}")

        # Also save JSON
        json_file = report_dir / f"backtest_results_{self._timestamp()}.json"
        try:
            with open(json_file, 'w') as f:
                json.dump(backtest_results, f, indent=2, default=str)
        except OSError as e:
            logger.warning(f"Failed to write JSON results to {json_file}: {e}")

        return str(report_file)

    def _generate_text_report(self, results: Dict) -> str:
        """
        Generate formatted text report.
        """
        lines = []
        lines.append("=" * 80)
        lines.append("CREDIT SPREAD STRATEGY - BACKTEST REPORT")
        lines.append("=" * 80)
        lines.append("")

        # Summary
        lines.append("SUMMARY")
        lines.append("-" * 80)
        lines.append(f"Total Trades: {results['total_trades']}")
        lines.append(f"Winning Trades: {results['winning_trades']}")
        lines.append(f"Losing Trades: {results['losing_trades']}")
        lines.append(f"Win Rate: {results['win_rate']:.2f}%")
        lines.append("")

        # Returns
        lines.append("RETURNS")
        lines.append("-" * 80)
        lines.append(f"Starting Capital: ${results['starting_capital']:,.2f}")
        lines.append(f"Ending Capital: ${results['ending_capital']:,.2f}")
        lines.append(f"Total P&L: ${results['total_pnl']:,.2f}")
        lines.append(f"Return: {results['return_pct']:.2f}%")
        lines.append("")

        # Trade Statistics
        lines.append("TRADE STATISTICS")
        lines.append("-" * 80)
        lines.append(f"Average Win: ${results['avg_win']:,.2f}")
        lines.append(f"Average Loss: ${results['avg_loss']:,.2f}")
        lines.append(f"Profit Factor: {results['profit_factor']:.2f}")
        lines.append("")

        # Risk Metrics
        lines.append("RISK METRICS")
        lines.append("-" * 80)
        lines.append(f"Max Drawdown: {results['max_drawdown']:.2f}%")
        lines.append(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        lines.append("")

        # Win Rate Target
        lines.append("TARGET ANALYSIS")
        lines.append("-" * 80)
        if results['win_rate'] >= 90:
            lines.append("✅ WIN RATE TARGET ACHIEVED (90%+)")
        else:
            lines.append(f"❌ Win rate {results['win_rate']:.2f}% below 90% target")
            lines.append(f"   Need {90 - results['win_rate']:.2f}% improvement")
        lines.append("")

        if results['total_pnl'] > 0:
            lines.append("✅ PROFITABLE STRATEGY")
        else:
            lines.append("❌ Strategy shows losses")

        lines.append("")
        lines.append("=" * 80)

        return "\n".join(lines)

    def _timestamp(self) -> str:
        """
        Generate timestamp string for filenames.
        """
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def print_summary(self, results: Dict):
        """
        Print summary to console.
        """
        print("\n" + "=" * 60)
        print("BACKTEST SUMMARY")
        print("=" * 60)
        print(f"Total Trades: {results['total_trades']}")
        print(f"Win Rate: {results['win_rate']:.2f}%")
        print(f"Total P&L: ${results['total_pnl']:,.2f}")
        print(f"Return: {results['return_pct']:.2f}%")
        print(f"Max Drawdown: {results['max_drawdown']:.2f}%")
        print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        print("=" * 60 + "\n")
