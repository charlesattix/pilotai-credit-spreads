"""Application metrics — thread-safe counters and gauges (stdlib only)."""

import threading
import time
from pathlib import Path
from typing import Dict, Any

from shared.constants import DATA_DIR as _DATA_DIR
from shared.io_utils import atomic_json_write


class Metrics:
    """Thread-safe counters and gauges with periodic file dump."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._start_time = time.time()

    def inc(self, name: str, amount: int = 1) -> None:
        """Increment a counter."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def gauge(self, name: str, value: float) -> None:
        """Set a gauge value."""
        with self._lock:
            self._gauges[name] = value

    def snapshot(self) -> Dict[str, Any]:
        """Return a point-in-time copy of all metrics."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "timestamp": time.time(),
            }

    def dump_to_file(self) -> None:
        """Write current snapshot to data/metrics.json."""
        path = Path(_DATA_DIR) / "metrics.json"
        atomic_json_write(path, self.snapshot())


# Global singleton
metrics = Metrics()
