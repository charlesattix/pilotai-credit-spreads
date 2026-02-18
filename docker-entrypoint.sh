#!/bin/sh
set -e
set -o pipefail 2>/dev/null || true  # pipefail not available in all sh implementations

# Verify required binaries exist
for bin in python3 node; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "ERROR: required binary '$bin' not found in PATH" >&2
        exit 1
    fi
done

# Ensure data directory exists and is writable
# The volume is mounted by Railway, so we just need to ensure subdirectories exist
DATA_DIR="${PILOTAI_DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR" /app/output /app/logs 2>/dev/null || true

# Try to initialize database - if it fails (volume not ready), that's OK,
# the API will create it on first access
if python3 -c "from shared.database import init_db; init_db()" 2>&1; then
    echo "Database initialized successfully"
else
    echo "INFO: Database will be initialized on first API access"
fi

case "$1" in
  web)
    cd /app/web
    exec node server.js
    ;;
  scheduler)
    exec python3 /app/main.py scheduler
    ;;
  scan)
    exec python3 /app/main.py scan
    ;;
  backtest)
    exec python3 /app/main.py backtest
    ;;
  all)
    # Run both the web server and the scan scheduler.
    # Web server in background, scheduler in foreground.
    # tini propagates SIGTERM to the process group, so both shut down cleanly.
    cd /app/web && node server.js &
    WEB_PID=$!
    echo "Web server started (PID $WEB_PID)"

    # Give the web server a moment to bind the port
    sleep 2

    echo "Starting scan scheduler..."
    python3 /app/main.py scheduler &
    SCHED_PID=$!

    # Wait for either process to exit, then stop the other
    wait -n $WEB_PID $SCHED_PID 2>/dev/null || true
    kill $WEB_PID $SCHED_PID 2>/dev/null || true
    wait
    ;;
  *)
    exec "$@"
    ;;
esac
