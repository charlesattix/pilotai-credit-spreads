"""Shared I/O utilities used across the trading system."""

import json
import os
import tempfile
from pathlib import Path


def atomic_json_write(filepath: Path, data, *, mkdir: bool = True):
    """Write JSON atomically: write to temp file then rename.

    Args:
        filepath: Destination file path.
        data: JSON-serialisable data to write.
        mkdir: If *True* (default), create parent directories as needed.
    """
    if mkdir:
        filepath.parent.mkdir(parents=True, exist_ok=True)
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
