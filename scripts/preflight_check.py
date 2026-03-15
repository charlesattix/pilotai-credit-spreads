#!/usr/bin/env python3
"""Preflight config validator — exits 1 on any missing required field.

Usage:
    python scripts/preflight_check.py configs/paper_champion.yaml
    python scripts/preflight_check.py configs/paper_exp401.yaml

Required fields:
    - db_path
    - logging (section with level and file)
    - strategy (section with min_delta and max_delta)
    - risk (section)
    - paper_mode: true
    - experiment_id
"""

import sys
from pathlib import Path

import yaml


def validate(config: dict) -> list:
    """Return list of error strings. Empty list means all checks passed."""
    errors = []

    # Top-level required fields
    if not config.get("db_path"):
        errors.append("Missing required field: db_path")

    if not config.get("experiment_id"):
        errors.append("Missing required field: experiment_id")

    if config.get("paper_mode") is not True:
        errors.append("paper_mode must be true (safety check)")

    # Logging section
    logging_cfg = config.get("logging")
    if not isinstance(logging_cfg, dict):
        errors.append("Missing required section: logging")
    else:
        if not logging_cfg.get("level"):
            errors.append("logging.level is required")
        if not logging_cfg.get("file"):
            errors.append("logging.file is required")

    # Strategy section
    strategy = config.get("strategy")
    if not isinstance(strategy, dict):
        errors.append("Missing required section: strategy")
    else:
        if "min_delta" not in strategy:
            errors.append("strategy.min_delta is required")
        if "max_delta" not in strategy:
            errors.append("strategy.max_delta is required")

    # Risk section
    if not isinstance(config.get("risk"), dict):
        errors.append("Missing required section: risk")

    return errors


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config.yaml>")
        sys.exit(1)

    config_path = Path(sys.argv[1])
    if not config_path.exists():
        print(f"FAIL: config file not found: {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    errors = validate(config)
    if errors:
        print(f"PREFLIGHT FAILED for {config_path}:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"PREFLIGHT OK: {config_path}")


if __name__ == "__main__":
    main()
