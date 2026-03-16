"""
LeaderboardManager — read/write/rank the experiment leaderboard.

Refactored from run_optimization.py:append_to_leaderboard().  The original
function continues to work unchanged; this class just wraps the same file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional


class LeaderboardManager:
    """Manage the output/leaderboard.json file.

    Usage::

        lb = LeaderboardManager()
        lb.append(entry)
        top = lb.rank(by='avg_return')[:5]
    """

    def __init__(self, path: str | Path = "output/leaderboard.json") -> None:
        self.path = Path(path)

    def load(self) -> List[dict]:
        """Load all leaderboard entries."""
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    def append(self, entry: dict) -> None:
        """Append an entry, deduplicating by run_id, then save sorted."""
        entries = self.load()
        run_id = entry.get("run_id")

        # Replace existing entry with same run_id
        entries = [e for e in entries if e.get("run_id") != run_id]
        entries.append(entry)

        # Sort: robust runs (overfit_score ≥ 0.70) first, then by avg_return
        entries.sort(
            key=lambda x: (
                (x.get("overfit_score") or 0) >= 0.70,
                x.get("summary", {}).get("avg_return", 0),
            ),
            reverse=True,
        )
        self._save(entries)

    def rank(self, by: str = "avg_return", robust_only: bool = False) -> List[dict]:
        """Return entries sorted by a summary field.

        Args:
            by:           Summary key to rank by (e.g. 'avg_return', 'worst_dd').
            robust_only:  If True, only return entries with overfit_score ≥ 0.70.
        """
        entries = self.load()
        if robust_only:
            entries = [e for e in entries if (e.get("overfit_score") or 0) >= 0.70]
        reverse = by != "worst_dd"  # lower DD is better
        return sorted(
            entries,
            key=lambda e: e.get("summary", {}).get(by, 0),
            reverse=reverse,
        )

    def get(self, run_id: str) -> Optional[dict]:
        """Return a single entry by run_id, or None if not found."""
        for entry in self.load():
            if entry.get("run_id") == run_id:
                return entry
        return None

    def _save(self, entries: List[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(entries, indent=2, default=str))
