"""
Trade Tracker
Tracks open and closed positions, manages trade lifecycle.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
from shared.constants import DATA_DIR as _DATA_DIR, OUTPUT_DIR as _OUTPUT_DIR
from shared.database import init_db, upsert_trade, batch_upsert_trades, get_trades as db_get_trades

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

        # Ensure data dir exists and initialize database
        self.data_dir = Path(_DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        init_db()

        # Load existing data from SQLite
        self.trades = self._load_trades()
        self.positions = self._load_positions()

        logger.info("TradeTracker initialized")

    def _load_trades(self) -> List[Dict]:
        """Load historical (closed) trades from SQLite.

        Returns an empty list when the database is empty or unavailable so the
        tracker can always start cleanly (EH-PY-08).
        """
        try:
            all_trades = db_get_trades(source="tracker")
            return [t for t in all_trades if t.get("status") != "open"]
        except Exception as e:
            logger.warning(
                f"Could not load trades from database: {e}. "
                "Starting with empty trade list."
            )
            return []

    def _load_positions(self) -> List[Dict]:
        """Load open positions from SQLite.

        Returns an empty list when the database is empty or unavailable so the
        tracker can always start cleanly (EH-PY-08).
        """
        try:
            all_trades = db_get_trades(source="tracker", status="open")
            return list(all_trades)
        except Exception as e:
            logger.warning(
                f"Could not load positions from database: {e}. "
                "Starting with empty positions list."
            )
            return []

    def _save_trades(self):
        """Persist trades to SQLite (single connection for all trades)."""
        batch_upsert_trades(self.trades, source="tracker")

    def _save_positions(self):
        """Persist positions to SQLite (single connection for all positions)."""
        batch_upsert_trades(self.positions, source="tracker")

    def add_position(self, position: Dict) -> str:
        """
        Add a new position.
        
        Args:
            position: Position data
            
        Returns:
            Position ID
        """
        # Generate position ID
        position_id = f"{position['ticker']}_{position['type']}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        position['id'] = position_id
        position['position_id'] = position_id
        position['entry_date'] = datetime.now(timezone.utc).isoformat()
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

        # Create trade record (reuse position_id as the trade id for SQLite)
        trade = {
            'id': position_id,
            'position_id': position_id,
            'ticker': position['ticker'],
            'type': position['type'],
            'entry_date': position['entry_date'],
            'exit_date': datetime.now(timezone.utc).isoformat(),
            'expiration': position.get('expiration'),
            'short_strike': position['short_strike'],
            'long_strike': position['long_strike'],
            'credit': position['credit'],
            'contracts': position.get('contracts', 1),
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl': pnl,
            'status': 'closed',
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

        output_path = Path(_OUTPUT_DIR) / filename
        output_path.parent.mkdir(exist_ok=True)

        trades_df.to_csv(output_path, index=False)
        logger.info(f"Trades exported to {output_path}")
