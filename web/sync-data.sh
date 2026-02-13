#!/bin/bash
# Sync latest scan data into web/data/ for Railway deploys
DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$(dirname "$DIR")"
mkdir -p "$DIR/data"
cp -f "$SRC/output/alerts.json" "$DIR/data/alerts.json" 2>/dev/null
cp -f "$SRC/data/paper_trades.json" "$DIR/data/paper_trades.json" 2>/dev/null
echo "Data synced to $DIR/data/"
