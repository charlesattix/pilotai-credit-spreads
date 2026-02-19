"""Shared I/O utilities used across the trading system."""

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def safe_json_read(filepath: Path, default=None):
    """Read and parse a JSON file with automatic backup recovery.

    Tries to read *filepath*.  If that fails (corrupt JSON, missing file),
    falls back to the ``.json.bak`` backup created by :func:`atomic_json_write`.
    If the backup also fails, *default* is returned.

    Args:
        filepath: Path to the JSON file.
        default: Value returned when both primary and backup reads fail.

    Returns:
        Parsed JSON data, or *default* on failure.
    """
    # 1. Try the primary file
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        pass

    # 2. Try the .bak backup
    backup_path = filepath.with_suffix(".json.bak")
    try:
        with open(backup_path, "r") as f:
            data = json.load(f)
        logger.warning(
            "Recovered JSON from backup %s (primary %s was unreadable)",
            backup_path,
            filepath,
        )
        return data
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        pass

    return default


def atomic_json_write(filepath: Path, data, *, mkdir: bool = True):
    """Write JSON atomically: write to temp file then rename.

    Before writing, a ``.json.bak`` backup of the existing file is created
    so that :func:`safe_json_read` can recover from a corrupted primary file.

    Args:
        filepath: Destination file path.
        data: JSON-serialisable data to write.
        mkdir: If *True* (default), create parent directories as needed.
    """
    if mkdir:
        filepath.parent.mkdir(parents=True, exist_ok=True)

    # Create .bak backup of existing file before writing
    if filepath.exists():
        backup_path = filepath.with_suffix(".json.bak")
        try:
            shutil.copy2(filepath, backup_path)
        except OSError:
            pass

    fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, filepath)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
