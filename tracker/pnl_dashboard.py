"""
P&L Dashboard
Displays profit/loss and performance metrics.
"""

import logging
from typing import Dict
from datetime import datetime, timedelta
import pandas as pd

logger = logging.getLogger(__name__)


class PnLDashboard:
    """
    Display P&L and performance dashboard.
    """

    def __init__(self, config: Dict, tracker):
        """
        Initialize P&L dashboard.
        
        Args:
            config: Configuration dictionary
            tracker: TradeTracker instance
        """
        self.config = config
        self.tracker = tracker

        logger.info("PnLDashboard initialized")

    def display_dashboard(self):
        """
        Display comprehensive dashboard.
        """
        print("\n" + "=" * 80)
        print("CREDIT SPREAD TRADING SYSTEM - P&L DASHBOARD")
        print("=" * 80)
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("")

        # Overall statistics
        self._display_overall_stats()

        # Recent performance
        self._display_recent_performance()

        # Open positions
        self._display_open_positions()

        # Top trades
        self._display_top_trades()

        print("=" * 80 + "\n")

    def _display_overall_stats(self):
        """Display overall trading statistics."""
        stats = self.tracker.get_statistics()

        print("OVERALL STATISTICS")
        print("-" * 80)
        print(f"Total Trades: {stats['total_trades']}")
        print(f"Winning Trades: {stats['winning_trades']}")
        print(f"Losing Trades: {stats['losing_trades']}")
        print(f"Win Rate: {stats['win_rate']:.2f}%")

        # Win rate indicator
        if stats['win_rate'] >= 90:
            print("  ✅ TARGET ACHIEVED (90%+)")
        elif stats['win_rate'] >= 80:
            print("  ⚠️  Close to target")
        else:
            print("  ❌ Below target")

        print("")
        print(f"Total P&L: ${stats['total_pnl']:,.2f}")
        print(f"Average P&L per Trade: ${stats['avg_pnl']:,.2f}")
        print(f"Average Win: ${stats['avg_win']:,.2f}")
        print(f"Average Loss: ${stats['avg_loss']:,.2f}")
        print(f"Best Trade: ${stats['best_trade']:,.2f}")
        print(f"Worst Trade: ${stats['worst_trade']:,.2f}")
        print("")

    def _display_recent_performance(self):
        """Display recent performance (last 30 days)."""
        trades = self.tracker.get_closed_trades()

        if not trades:
            return

        trades_df = pd.DataFrame(trades)
        trades_df['exit_date'] = pd.to_datetime(trades_df['exit_date'])

        # Filter last 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)
        recent_trades = trades_df[trades_df['exit_date'] >= thirty_days_ago]

        if recent_trades.empty:
            return

        print("RECENT PERFORMANCE (Last 30 Days)")
        print("-" * 80)
        print(f"Trades: {len(recent_trades)}")
        print(f"P&L: ${recent_trades['pnl'].sum():,.2f}")

        recent_wins = len(recent_trades[recent_trades['pnl'] > 0])
        recent_win_rate = (recent_wins / len(recent_trades) * 100) if len(recent_trades) > 0 else 0
        print(f"Win Rate: {recent_win_rate:.2f}%")
        print("")

    def _display_open_positions(self):
        """Display open positions."""
        positions = self.tracker.get_open_positions()

        print("OPEN POSITIONS")
        print("-" * 80)

        if not positions:
            print("No open positions")
            print("")
            return

        print(f"Total Open: {len(positions)}")
        print("")

        for i, pos in enumerate(positions, 1):
            print(f"{i}. {pos['ticker']} - {pos['type']}")
            print(f"   Entry: {pos['entry_date']}")
            print(f"   Strikes: ${pos['short_strike']:.2f} / ${pos['long_strike']:.2f}")
            print(f"   Credit: ${pos['credit']:.2f}")
            print(f"   Max Loss: ${pos.get('max_loss', 0):.2f}")

            if 'expiration' in pos:
                print(f"   Expiration: {pos['expiration']}")

            print("")

    def _display_top_trades(self):
        """Display best and worst trades."""
        trades = self.tracker.get_closed_trades()

        if not trades:
            return

        trades_df = pd.DataFrame(trades)

        print("TOP TRADES")
        print("-" * 80)

        # Best trade
        best_trade = trades_df.loc[trades_df['pnl'].idxmax()]
        print(f"Best Trade: {best_trade['ticker']} - ${best_trade['pnl']:.2f}")
        print(f"  Date: {best_trade['exit_date']}")
        print(f"  Type: {best_trade['type']}")
        print("")

        # Worst trade
        worst_trade = trades_df.loc[trades_df['pnl'].idxmin()]
        print(f"Worst Trade: {worst_trade['ticker']} - ${worst_trade['pnl']:.2f}")
        print(f"  Date: {worst_trade['exit_date']}")
        print(f"  Type: {worst_trade['type']}")
        print("")

    def generate_summary(self) -> Dict:
        """
        Generate summary data for external use.
        
        Returns:
            Dictionary with summary data
        """
        stats = self.tracker.get_statistics()
        positions = self.tracker.get_open_positions()

        summary = {
            'timestamp': datetime.now().isoformat(),
            'statistics': stats,
            'open_positions_count': len(positions),
            'open_positions': positions,
        }

        return summary
