#!/bin/bash
# run_exp036.sh — Launch/stop/status for EXP-036 paper trading instance
# Account: PA3D6UPXF5F2 (Charles EXP-036 — control group, simple MA200)
# Config:  config_exp036.yaml + .env.exp036
# DB:      data/pilotai_exp036.db

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${PROJECT_DIR}/logs"
PIDS_FILE="${PROJECT_DIR}/.pids_exp036"

mkdir -p "$LOG_DIR"

# ── Stop mode ─────────────────────────────────────────────────────────────────
if [ "${1:-}" = "stop" ]; then
  if [ ! -f "$PIDS_FILE" ]; then
    echo "Not running (no .pids_exp036 file)."
    exit 0
  fi
  PID=$(cat "$PIDS_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" && echo "Stopped exp_036 (PID $PID)"
  else
    echo "PID $PID already gone"
  fi
  rm -f "$PIDS_FILE"
  exit 0
fi

# ── Status mode ───────────────────────────────────────────────────────────────
if [ "${1:-}" = "status" ]; then
  if [ ! -f "$PIDS_FILE" ]; then
    echo "exp_036: NOT RUNNING"
    exit 0
  fi
  PID=$(cat "$PIDS_FILE")
  echo -n "exp_036 (PID $PID): "
  kill -0 "$PID" 2>/dev/null && echo "RUNNING" || echo "DEAD"
  exit 0
fi

# ── Prevent double-launch ─────────────────────────────────────────────────────
if [ -f "$PIDS_FILE" ]; then
  PID=$(cat "$PIDS_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "ERROR: exp_036 already running (PID $PID)."
    echo "Run './run_exp036.sh stop' first."
    exit 1
  fi
fi

# ── Launch mode ───────────────────────────────────────────────────────────────
cd "$PROJECT_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Launching exp_036 (control: directional-only, 5% flat, MA200)"
python3 main.py scheduler \
  --config config_exp036.yaml \
  --env-file .env.exp036 \
  --db data/pilotai_exp036.db \
  >> "$LOG_DIR/trading_exp036.log" 2>&1 &
EXP036_PID=$!

echo "$EXP036_PID" > "$PIDS_FILE"

echo ""
echo "exp_036 started (PID $EXP036_PID)"
echo "  Config:  config_exp036.yaml"
echo "  Env:     .env.exp036"
echo "  DB:      data/pilotai_exp036.db"
echo "  Log:     logs/trading_exp036.log"
echo ""
echo "Commands:"
echo "  ./run_exp036.sh stop    # stop instance"
echo "  ./run_exp036.sh status  # check PID"
echo "  tail -f logs/trading_exp036.log"
