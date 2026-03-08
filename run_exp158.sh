#!/bin/bash
# run_exp158.sh — Launch/stop/status for EXP-158 paper trading instance
# Account: PA3LP867WNGU (Charles EXP-158 — compound sizing A/B test)
# Config:  config_exp158.yaml + .env.exp059
# DB:      data/pilotai_exp158.db

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${PROJECT_DIR}/logs"
PIDS_FILE="${PROJECT_DIR}/.pids_exp158"

mkdir -p "$LOG_DIR"

# ── Stop mode ─────────────────────────────────────────────────────────────────
if [ "${1:-}" = "stop" ]; then
  if [ ! -f "$PIDS_FILE" ]; then
    echo "Not running (no .pids_exp158 file)."
    exit 0
  fi
  PID=$(cat "$PIDS_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" && echo "Stopped exp_158 (PID $PID)"
  else
    echo "PID $PID already gone"
  fi
  rm -f "$PIDS_FILE"
  exit 0
fi

# ── Status mode ───────────────────────────────────────────────────────────────
if [ "${1:-}" = "status" ]; then
  if [ ! -f "$PIDS_FILE" ]; then
    echo "exp_158: NOT RUNNING"
    exit 0
  fi
  PID=$(cat "$PIDS_FILE")
  echo -n "exp_158 (PID $PID): "
  kill -0 "$PID" 2>/dev/null && echo "RUNNING" || echo "DEAD"
  exit 0
fi

# ── Prevent double-launch ─────────────────────────────────────────────────────
if [ -f "$PIDS_FILE" ]; then
  PID=$(cat "$PIDS_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "ERROR: exp_158 already running (PID $PID)."
    echo "Run './run_exp158.sh stop' first."
    exit 1
  fi
fi

# ── Launch mode ───────────────────────────────────────────────────────────────
cd "$PROJECT_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Launching exp_158 (IC-in-NEUTRAL, 5%/9% compound, SL=3.5x)"
python3 main.py scheduler \
  --config config_exp158.yaml \
  --env-file .env.exp059 \
  --db data/pilotai_exp158.db \
  >> "$LOG_DIR/trading_exp158.log" 2>&1 &
EXP158_PID=$!

echo "$EXP158_PID" > "$PIDS_FILE"

echo ""
echo "exp_158 started (PID $EXP158_PID)"
echo "  Config:  config_exp158.yaml"
echo "  Env:     .env.exp059"
echo "  DB:      data/pilotai_exp158.db"
echo "  Log:     logs/trading_exp158.log"
echo ""
echo "Commands:"
echo "  ./run_exp158.sh stop    # stop instance"
echo "  ./run_exp158.sh status  # check PID"
echo "  tail -f logs/trading_exp158.log"
