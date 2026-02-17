"""
Trade Tracker
Tracks open and closed positions, manages trade lifecycle.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import json
import pandas as pd
from shared.io_utils import atomic_json_write

logger = logging.getLogger(__name__)


class TradeTracker:
    """
    Track all trades and positions.
    """

    def __init__(self, config: Dict):
        """
        Initialize trade tracker.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config

        # Storage paths
        self.data_dir = Path('data')
        self.data_dir.mkdir(exist_ok=True)

        self.trades_file = self.data_dir / 'tracker_trades.json'
        self.positions_file = self.data_dir / 'positions.json'

        # Load existing data
        self.trades = self._load_trades()
        self.positions = self._load_positions()

        logger.info("TradeTracker initialized")

    def _load_trades(self) -> List[Dict]:
        """Load historical trades."""
        if self.trades_file.exists():
            with open(self.trades_file, 'r') as f:
                return json.load(f)
        return []

    def _load_positions(self) -> List[Dict]:
        """Load open positions."""
        if self.positions_file.exists():
            with open(self.positions_file, 'r') as f:
                return json.load(f)
        return []

    # Delegate to the shared utility; keep the class attribute so any code
    # referencing TradeTracker._atomic_json_write still resolves.
    _atomic_json_write = staticmethod(atomic_json_write)

    def _save_trades(self):
        """Save trades to disk."""
        atomic_json_write(self.trades_file, self.trades)

    def _save_positions(self):
        """Save positions to disk."""
        atomic_json_write(self.positions_file, self.positions)

    def add_position(self, position: Dict) -> str:
        """
        Add a new position.
        
        Args:
            position: Position data
            
        Returns:
            Position ID
        """
        # Generate position ID
        position_id = f"{position['ticker']}_{position['type']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        position['position_id'] = position_id
        position['entry_date'] = datetime.now().isoformat()
        position['status'] = 'open'

        self.positions.append(position)
        self._save_positions()

        logger.info(f"Added position: {position_id}")

        return position_id

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str,
        pnl: float
    ):
        """
        Close an existing position.
        
        Args:
            position_id: Position identifier
            exit_price: Exit price
            exit_reason: Reason for exit
            pnl: Profit/loss
        """
        # Find position
        position = None
        for i, pos in enumerate(self.positions):
            if pos['position_id'] == position_id:
                position = self.positions.pop(i)
                break

        if not position:
            logger.warning(f"Position not found: {position_id}")
            return

        # Create trade record
        trade = {
            'position_id': position_id,
            'ticker': position['ticker'],
            'type': position['type'],
            'entry_date': position['entry_date'],
            'exit_date': datetime.now().isoformat(),
            'expiration': position.get('expiration'),
            'short_strike': position['short_strike'],
            'long_strike': position['long_strike'],
            'credit': position['credit'],
            'contracts': position.get('contracts', 1),
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl': pnl,
            'return_pct': (pnl / (position.get('max_loss', 1) * 100)) * 100,
        }

        self.trades.append(trade)
        self._save_trades()
        self._save_positions()

        logger.info(f"Closed position: {position_id}, P&L: ${pnl:.2f}")

    def update_position(self, position_id: str, updates: Dict):
        """
        Update an existing position.
        
        Args:
            position_id: Position identifier
            updates: Dictionary of fields to update
        """
        for pos in self.positions:
            if pos['position_id'] == position_id:
                pos.update(updates)
                self._save_positions()
                logger.info(f"Updated position: {position_id}")
                return

        logger.warning(f"Position not found: {position_id}")

    def get_open_positions(self) -> List[Dict]:
        """
        Get all open positions.
        
        Returns:
            List of open positions
        """
        return self.positions

    def get_position(self, position_id: str) -> Optional[Dict]:
        """
        Get a specific position.
        
        Args:
            position_id: Position identifier
            
        Returns:
            Position data or None
        """
        for pos in self.positions:
            if pos['position_id'] == position_id:
                return pos
        return None

    def get_closed_trades(self) -> List[Dict]:
        """
        Get all closed trades.
        
        Returns:
            List of closed trades
        """
        return self.trades

    def get_statistics(self) -> Dict:
        """
        Calculate trading statistics.
        
        Returns:
            Dictionary with statistics
        """
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'open_positions': len(self.positions),
            }

        trades_df = pd.DataFrame(self.trades)

        total_trades = len(trades_df)
        winners = trades_df[trades_df['pnl'] > 0]
        losers = trades_df[trades_df['pnl'] < 0]

        stats = {
            'total_trades': total_trades,
            'winning_trades': len(winners),
            'losing_trades': len(losers),
            'win_rate': (len(winners) / total_trades * 100) if total_trades > 0 else 0,
            'total_pnl': trades_df['pnl'].sum(),
            'avg_pnl': trades_df['pnl'].mean(),
            'avg_win': winners['pnl'].mean() if len(winners) > 0 else 0,
            'avg_loss': losers['pnl'].mean() if len(losers) > 0 else 0,
            'best_trade': trades_df['pnl'].max() if total_trades > 0 else 0,
            'worst_trade': trades_df['pnl'].min() if total_trades > 0 else 0,
            'open_positions': len(self.positions),
        }

        return stats

    def export_to_csv(self, filename: str = 'trades_export.csv'):
        """
        Export trades to CSV.
        
        Args:
            filename: Output filename
        """
        if not self.trades:
            logger.warning("No trades to export")
            return

        trades_df = pd.DataFrame(self.trades)

        output_path = Path('output') / filename
        output_path.parent.mkdir(exist_ok=True)

        trades_df.to_csv(output_path, index=False)
        logger.info(f"Trades exported to {output_path}")
