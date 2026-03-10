#!/bin/bash
# Credit Spread Scanner — Cron Runner
# Runs one scan cycle for each active paper trading experiment.
# Called by crontab at scheduled market hours (ET, weekdays only).
#
# Experiments:
#   exp059 — configs/paper_exp059.yaml  .env.exp059  data/pilotai_exp059.db
#   exp154 — configs/paper_exp154.yaml  .env.exp154  data/pilotai_exp154.db
#   exp305 — configs/paper_exp305.yaml  .env.exp305  data/pilotai_exp305.db

set -euo pipefail

PROJECT_DIR="/Users/charlesbot/projects/pilotai-credit-spreads"
LOG_DIR="${PROJECT_DIR}/logs"
MAX_LOG_SIZE=$((5 * 1024 * 1024))  # 5 MB

mkdir -p "$LOG_DIR"

# Skip weekends (extra safety — cron schedule is Mon-Fri but TZ edge cases exist)
DOW=$(TZ=America/New_York date +%u)  # 1=Mon, 7=Sun
if [ "$DOW" -gt 5 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Skipping scan — weekend (day=$DOW)"
  exit 0
fi

cd "$PROJECT_DIR"

_run_scan() {
  local EXP="$1"
  local CONFIG="$2"
  local ENV_FILE="$3"
  local DB="$4"
  local LOG_FILE="${LOG_DIR}/scan-cron-${EXP}.log"

  # Rotate log if too large
  if [ -f "$LOG_FILE" ] && [ "$(stat -f%z "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$MAX_LOG_SIZE" ]; then
    mv "$LOG_FILE" "${LOG_FILE}.1"
  fi

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting ${EXP} scan (ET: $(TZ=America/New_York date '+%H:%M %Z'))" >> "$LOG_FILE"

  /usr/bin/python3 main.py scan \
    --config "$CONFIG" \
    --env-file "$ENV_FILE" \
    --db "$DB" \
    >> "$LOG_FILE" 2>&1
  local EXIT_CODE=$?

  if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ${EXP} scan completed successfully" >> "$LOG_FILE"
  else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ${EXP} scan failed with exit code $EXIT_CODE" >> "$LOG_FILE"
  fi
  echo "---" >> "$LOG_FILE"
}

_run_scan "exp059" "configs/paper_exp059.yaml" ".env.exp059" "data/pilotai_exp059.db"
_run_scan "exp154" "configs/paper_exp154.yaml" ".env.exp154" "data/pilotai_exp154.db"
_run_scan "exp305" "configs/paper_exp305.yaml" ".env.exp305" "data/pilotai_exp305.db"
