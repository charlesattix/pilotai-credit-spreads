#!/bin/bash
# run_exp154.sh — Launch/stop/status for EXP-154 paper trading instance
# Account: PA3UNOV58WGK (Charles EXP-154)
# Config:  config_exp154.yaml + .env.exp154
# DB:      data/pilotai_exp154.db

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${PROJECT_DIR}/logs"
PIDS_FILE="${PROJECT_DIR}/.pids_exp154"

mkdir -p "$LOG_DIR"

# ── Stop mode ─────────────────────────────────────────────────────────────────
if [ "${1:-}" = "stop" ]; then
  if [ ! -f "$PIDS_FILE" ]; then
    echo "Not running (no .pids_exp154 file)."
    exit 0
  fi
  PID=$(cat "$PIDS_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" && echo "Stopped exp_154 (PID $PID)"
  else
    echo "PID $PID already gone"
  fi
  rm -f "$PIDS_FILE"
  exit 0
fi

# ── Status mode ───────────────────────────────────────────────────────────────
if [ "${1:-}" = "status" ]; then
  if [ ! -f "$PIDS_FILE" ]; then
    echo "exp_154: NOT RUNNING"
    exit 0
  fi
  PID=$(cat "$PIDS_FILE")
  echo -n "exp_154 (PID $PID): "
  kill -0 "$PID" 2>/dev/null && echo "RUNNING" || echo "DEAD"
  exit 0
fi

# ── Prevent double-launch ─────────────────────────────────────────────────────
if [ -f "$PIDS_FILE" ]; then
  PID=$(cat "$PIDS_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "ERROR: exp_154 already running (PID $PID)."
    echo "Run './run_exp154.sh stop' first."
    exit 1
  fi
fi

# ── Launch mode ───────────────────────────────────────────────────────────────
cd "$PROJECT_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Launching exp_154 (IC-in-NEUTRAL, 5% risk, SL=3.5x)"
python3 main.py scheduler \
  --config config_exp154.yaml \
  --env-file .env.exp154 \
  --db data/pilotai_exp154.db \
  >> "$LOG_DIR/trading_exp154.log" 2>&1 &
EXP154_PID=$!

echo "$EXP154_PID" > "$PIDS_FILE"

echo ""
echo "exp_154 started (PID $EXP154_PID)"
echo "  Config:  config_exp154.yaml"
echo "  Env:     .env.exp154"
echo "  DB:      data/pilotai_exp154.db"
echo "  Log:     logs/trading_exp154.log"
echo ""
echo "Commands:"
echo "  ./run_exp154.sh stop    # stop instance"
echo "  ./run_exp154.sh status  # check PID"
echo "  tail -f logs/trading_exp154.log"
