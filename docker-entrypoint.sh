#!/bin/sh
set -e

case "$1" in
  web)
    cd /app/web
    exec node server.js
    ;;
  scan)
    exec python3 /app/main.py scan
    ;;
  backtest)
    exec python3 /app/main.py backtest
    ;;
  *)
    exec "$@"
    ;;
esac
