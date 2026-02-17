#!/bin/bash
# Credit Spread Scanner — Cron Runner
# Called by crontab at scheduled market hours (ET, weekdays only)

set -euo pipefail

PROJECT_DIR="/Users/charlesbot/projects/pilotai-credit-spreads"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/scan-cron.log"
MAX_LOG_SIZE=$((5 * 1024 * 1024))  # 5 MB

mkdir -p "$LOG_DIR"

# Rotate log if too large
if [ -f "$LOG_FILE" ] && [ "$(stat -f%z "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$MAX_LOG_SIZE" ]; then
  mv "$LOG_FILE" "${LOG_FILE}.1"
fi

# Skip weekends (extra safety — cron schedule is Mon-Fri but TZ edge cases exist)
DOW=$(TZ=America/New_York date +%u)  # 1=Mon, 7=Sun
if [ "$DOW" -gt 5 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Skipping scan — weekend (day=$DOW)" >> "$LOG_FILE"
  exit 0
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting scan (ET: $(TZ=America/New_York date '+%H:%M %Z'))" >> "$LOG_FILE"

cd "$PROJECT_DIR"

/usr/bin/python3 main.py scan >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Scan completed successfully" >> "$LOG_FILE"
else
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Scan failed with exit code $EXIT_CODE" >> "$LOG_FILE"
fi

echo "---" >> "$LOG_FILE"
