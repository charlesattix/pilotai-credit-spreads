#!/usr/bin/env python3
"""List experiments from registry.json.

Usage:
    python scripts/list_experiments.py           # active only (default)
    python scripts/list_experiments.py --active  # active only
    python scripts/list_experiments.py --retired # retired only
    python scripts/list_experiments.py --all     # everything
"""

import json
import sys
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "experiments" / "registry.json"

RETIRED_STATUSES = {"retired"}
ACTIVE_STATUSES = {"data_collection", "backtesting", "validated", "paper_trading",
                   "deployed", "pending", "awaiting_deploy"}

STATUS_LABEL = {
    "data_collection": "data_collection",
    "backtesting":     "backtesting",
    "validated":       "validated",
    "paper_trading":   "paper_trading",
    "deployed":        "deployed",
    "pending":         "pending",
    "awaiting_deploy": "awaiting_deploy",
    "retired":         "retired",
}


def load_registry() -> dict:
    if not REGISTRY.exists():
        print(f"ERROR: registry not found at {REGISTRY}", file=sys.stderr)
        sys.exit(1)
    with open(REGISTRY) as f:
        return json.load(f)


def print_table(experiments: list[dict], title: str) -> None:
    if not experiments:
        print(f"  (no experiments)\n")
        return

    # Column widths — fit content, minimum width per header
    col_id     = max(len("ID"),         max(len(e["id"])                   for e in experiments))
    col_name   = max(len("Name"),       max(len(e["name"])                 for e in experiments))
    col_by     = max(len("Created By"), max(len(e["created_by"])           for e in experiments))
    col_status = max(len("Status"),     max(len(e["status"])               for e in experiments))
    col_config = max(len("Config"),     max(len(e.get("paper_config") or "—") for e in experiments))

    sep = (f"+-{'-' * col_id}-+-{'-' * col_name}-+-{'-' * col_by}-+"
           f"-{'-' * col_status}-+-{'-' * col_config}-+")
    header = (f"| {'ID':<{col_id}} | {'Name':<{col_name}} | {'Created By':<{col_by}} |"
              f" {'Status':<{col_status}} | {'Config':<{col_config}} |")

    print(f"\n{title}")
    print(sep)
    print(header)
    print(sep)
    for e in experiments:
        config = e.get("paper_config") or "—"
        print(f"| {e['id']:<{col_id}} | {e['name']:<{col_name}} | {e['created_by']:<{col_by}} |"
              f" {e['status']:<{col_status}} | {config:<{col_config}} |")
    print(sep)
    print(f"  {len(experiments)} experiment(s)\n")


def main() -> None:
    args = sys.argv[1:]
    if len(args) > 1 or (args and args[0] not in ("--active", "--retired", "--all")):
        print("Usage: list_experiments.py [--active|--retired|--all]")
        sys.exit(1)

    mode = args[0] if args else "--active"

    registry = load_registry()
    all_exps = list(registry["experiments"].values())

    # Sort by ID numerically where possible
    def sort_key(e):
        try:
            return int(e["id"].split("-")[1])
        except (IndexError, ValueError):
            return 0

    all_exps.sort(key=sort_key)

    active  = [e for e in all_exps if e["status"] in ACTIVE_STATUSES]
    retired = [e for e in all_exps if e["status"] in RETIRED_STATUSES]

    print(f"Experiment Registry  (schema v{registry.get('schema_version', '?')}"
          f"  |  last updated: {registry.get('last_updated', '?')})")

    if mode == "--active":
        print_table(active, "Active Experiments")
    elif mode == "--retired":
        print_table(retired, "Retired Experiments")
    else:  # --all
        print_table(active,  "Active Experiments")
        print_table(retired, "Retired Experiments")


if __name__ == "__main__":
    main()
