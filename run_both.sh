#!/bin/bash
# run_both.sh — Launch both paper trading instances
# Instance 1: exp_059 (iron condors ON)  — default config + .env
# Instance 2: exp_036 (iron condors OFF) — config_exp036.yaml + .env.exp036

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${PROJECT_DIR}/logs"
PIDS_FILE="${PROJECT_DIR}/.pids_both"

mkdir -p "$LOG_DIR"

# ── Stop mode ─────────────────────────────────────────────────────────────────
if [ "${1:-}" = "stop" ]; then
  if [ ! -f "$PIDS_FILE" ]; then
    echo "No .pids_both file found — nothing to stop."
    exit 0
  fi
  while read -r PID; do
    if kill -0 "$PID" 2>/dev/null; then
      kill "$PID" && echo "Stopped PID $PID"
    else
      echo "PID $PID already gone"
    fi
  done < "$PIDS_FILE"
  rm -f "$PIDS_FILE"
  exit 0
fi

# ── Status mode ───────────────────────────────────────────────────────────────
if [ "${1:-}" = "status" ]; then
  if [ ! -f "$PIDS_FILE" ]; then
    echo "Not running."
    exit 0
  fi
  EXP059_PID=$(awk 'NR==1' "$PIDS_FILE")
  EXP036_PID=$(awk 'NR==2' "$PIDS_FILE")
  echo -n "exp_059 (PID $EXP059_PID): "; kill -0 "$EXP059_PID" 2>/dev/null && echo "RUNNING" || echo "DEAD"
  echo -n "exp_036 (PID $EXP036_PID): "; kill -0 "$EXP036_PID" 2>/dev/null && echo "RUNNING" || echo "DEAD"
  exit 0
fi

# ── Prevent double-launch ─────────────────────────────────────────────────────
if [ -f "$PIDS_FILE" ]; then
  EXP059_PID=$(awk 'NR==1' "$PIDS_FILE")
  EXP036_PID=$(awk 'NR==2' "$PIDS_FILE")
  if kill -0 "$EXP059_PID" 2>/dev/null || kill -0 "$EXP036_PID" 2>/dev/null; then
    echo "ERROR: Instances already running (PIDs $EXP059_PID / $EXP036_PID)."
    echo "Run './run_both.sh stop' to stop them first."
    exit 1
  fi
fi

# ── Launch mode ───────────────────────────────────────────────────────────────
cd "$PROJECT_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Launching exp_059 (IC on, config.yaml, .env)"
python3 paper_trader.py \
  >> "$LOG_DIR/paper_exp059.log" 2>&1 &
EXP059_PID=$!

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Launching exp_036 (IC off, config_exp036.yaml, .env.exp036)"
python3 paper_trader.py \
  --config config_exp036.yaml \
  --env-file .env.exp036 \
  --db data/pilotai_exp036.db \
  >> "$LOG_DIR/paper_exp036.log" 2>&1 &
EXP036_PID=$!

# Save PIDs
printf "%s\n%s\n" "$EXP059_PID" "$EXP036_PID" > "$PIDS_FILE"

echo ""
echo "Both instances started:"
echo "  exp_059 PID $EXP059_PID → logs/paper_exp059.log"
echo "  exp_036 PID $EXP036_PID → logs/paper_exp036.log"
echo ""
echo "Commands:"
echo "  ./run_both.sh stop    # stop both"
echo "  ./run_both.sh status  # check PIDs"
echo "  tail -f logs/paper_exp059.log"
echo "  tail -f logs/paper_exp036.log"
