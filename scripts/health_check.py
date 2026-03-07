#!/usr/bin/env python3
"""Health check script for the paper trading scheduler.

Reads data/heartbeat.json (written by the scheduler after each scan) and
reports the system's health status.

Exit codes:
    0  — healthy   (heartbeat fresh, PID alive)
    1  — unhealthy (stale/missing heartbeat, PID dead)
    2  — degraded  (heartbeat fresh but last scan had errors)

Usage:
    python scripts/health_check.py               # human-readable output
    python scripts/health_check.py --json         # machine-readable JSON
    python scripts/health_check.py --max-age 60   # custom staleness threshold (minutes)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from project root without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.constants import DATA_DIR  # noqa: E402

HEARTBEAT_PATH = Path(DATA_DIR) / "heartbeat.json"
DEFAULT_MAX_AGE_MINUTES = 45

STATUS_HEALTHY = "healthy"
STATUS_UNHEALTHY = "unhealthy"
STATUS_DEGRADED = "degraded"

EXIT_CODES = {
    STATUS_HEALTHY: 0,
    STATUS_UNHEALTHY: 1,
    STATUS_DEGRADED: 2,
}


def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def check_health(max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES) -> dict:
    """Read heartbeat and determine health status.

    Returns a dict with keys: status, message, heartbeat (or None).
    """
    if not HEARTBEAT_PATH.exists():
        return {
            "status": STATUS_UNHEALTHY,
            "message": f"Heartbeat file not found: {HEARTBEAT_PATH}",
            "heartbeat": None,
        }

    try:
        with open(HEARTBEAT_PATH) as f:
            heartbeat = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {
            "status": STATUS_UNHEALTHY,
            "message": f"Cannot read heartbeat: {e}",
            "heartbeat": None,
        }

    # Check age
    last_utc_str = heartbeat.get("last_scan_utc", "")
    try:
        last_utc = datetime.strptime(last_utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        age_minutes = (datetime.now(timezone.utc) - last_utc).total_seconds() / 60
    except (ValueError, TypeError):
        return {
            "status": STATUS_UNHEALTHY,
            "message": f"Cannot parse heartbeat timestamp: {last_utc_str}",
            "heartbeat": heartbeat,
        }

    # Check PID
    pid = heartbeat.get("pid")
    pid_alive = _pid_alive(pid) if isinstance(pid, int) else False

    if age_minutes > max_age_minutes:
        return {
            "status": STATUS_UNHEALTHY,
            "message": (
                f"Heartbeat stale: {age_minutes:.0f}min old "
                f"(threshold: {max_age_minutes}min), "
                f"PID {pid} {'alive' if pid_alive else 'dead'}"
            ),
            "heartbeat": heartbeat,
        }

    if not pid_alive:
        return {
            "status": STATUS_UNHEALTHY,
            "message": f"PID {pid} is not running (heartbeat {age_minutes:.0f}min old)",
            "heartbeat": heartbeat,
        }

    if heartbeat.get("had_error"):
        return {
            "status": STATUS_DEGRADED,
            "message": (
                f"Last scan had errors ({heartbeat.get('last_slot_type', '?')} "
                f"at {heartbeat.get('last_scan_time', '?')})"
            ),
            "heartbeat": heartbeat,
        }

    return {
        "status": STATUS_HEALTHY,
        "message": (
            f"OK — last scan {age_minutes:.0f}min ago "
            f"({heartbeat.get('last_slot_type', '?')} at "
            f"{heartbeat.get('last_scan_time', '?')}), "
            f"scan_count={heartbeat.get('scan_count', 0)}"
        ),
        "heartbeat": heartbeat,
    }


def main():
    parser = argparse.ArgumentParser(description="Check scheduler health")
    parser.add_argument(
        "--max-age",
        type=int,
        default=DEFAULT_MAX_AGE_MINUTES,
        help=f"Max heartbeat age in minutes (default: {DEFAULT_MAX_AGE_MINUTES})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )
    args = parser.parse_args()

    result = check_health(max_age_minutes=args.max_age)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        status = result["status"].upper()
        print(f"[{status}] {result['message']}")

    sys.exit(EXIT_CODES[result["status"]])


if __name__ == "__main__":
    main()
