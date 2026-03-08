"""
Write-Ahead Log (WAL) for critical trade events.

Purpose: If the primary SQLite write fails after a fill is detected, the fill
data is written to a plain-text JSON-lines file so it can be replayed on the
next startup — preventing silent position loss.

Usage::

    from shared.wal import write_wal_entry, replay_wal, clear_wal

    # On fill or close, before writing to DB:
    write_wal_entry({"type": "close_trade", "trade_id": "abc", "pnl": 75.0, ...})

    # At startup (before opening for trading):
    pending = replay_wal()   # returns list of unprocessed entries
    for entry in pending:
        process(entry)        # re-apply to DB
        clear_wal_entry(entry["_wal_id"])
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default WAL file location (same directory as the SQLite DB for simplicity)
_DEFAULT_WAL_PATH = "data/recovery.wal"

# Thread lock to prevent concurrent writes corrupting the file
_WAL_LOCK = threading.Lock()


def _wal_path(wal_path: Optional[str] = None) -> str:
    path = wal_path or os.environ.get("WAL_PATH", _DEFAULT_WAL_PATH)
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    return path


def write_wal_entry(entry: dict, wal_path: Optional[str] = None) -> None:
    """Append an entry to the WAL file.

    Each entry is a JSON object on a single line with a ``_wal_id``
    (timestamp-based) and ``_processed`` = False.

    Args:
        entry: Dict describing the event (type, trade_id, pnl, etc.)
        wal_path: Override for the WAL file path.
    """
    path = _wal_path(wal_path)
    record = {
        **entry,
        "_wal_id": datetime.now(timezone.utc).isoformat(),
        "_processed": False,
    }
    line = json.dumps(record, default=str)
    with _WAL_LOCK:
        try:
            with open(path, "a") as f:
                f.write(line + "\n")
            logger.info("WAL: wrote recovery entry for trade_id=%s", entry.get("trade_id"))
        except Exception as e:
            # If even the WAL write fails, there's nothing more we can do other than log
            logger.critical(
                "WAL: CRITICAL — could not write recovery entry for %s: %s. "
                "Manual reconciliation required.",
                entry.get("trade_id"), e,
            )


def replay_wal(wal_path: Optional[str] = None) -> List[dict]:
    """Return all unprocessed WAL entries.

    Call this at startup before opening for trading. Process each entry
    and call ``mark_wal_entry_processed`` or ``clear_wal`` when done.

    Returns:
        List of unprocessed entry dicts (with _wal_id for identification).
    """
    path = _wal_path(wal_path)
    if not os.path.exists(path):
        return []

    entries = []
    with _WAL_LOCK:
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if not record.get("_processed", True):
                            entries.append(record)
                    except json.JSONDecodeError:
                        logger.warning("WAL: could not parse line: %r", line)
        except Exception as e:
            logger.error("WAL: failed to read recovery file %s: %s", path, e)

    if entries:
        logger.warning(
            "WAL: found %d unprocessed recovery entries — replay before trading", len(entries)
        )
    return entries


def clear_wal(wal_path: Optional[str] = None) -> None:
    """Remove the WAL file entirely (call after all entries are replayed)."""
    path = _wal_path(wal_path)
    with _WAL_LOCK:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info("WAL: cleared recovery file %s", path)
        except Exception as e:
            logger.error("WAL: failed to clear %s: %s", path, e)
