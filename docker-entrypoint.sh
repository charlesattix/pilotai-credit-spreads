#!/bin/sh
set -e

# Ensure data directory and SQLite database exist on the persistent volume.
# This is a no-op if the DB already exists (CREATE TABLE IF NOT EXISTS).
mkdir -p "${PILOTAI_DATA_DIR:-/app/data}" /app/output /app/logs
python3 -c "from shared.database import init_db; init_db()" 2>&1 || echo "WARN: DB init failed, will retry on first access"

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
