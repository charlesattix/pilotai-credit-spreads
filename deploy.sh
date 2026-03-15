#!/usr/bin/env bash
# deploy.sh — PilotAI bot lifecycle manager
#
# Usage:
#   ./deploy.sh              # git pull + restart both bots
#   ./deploy.sh restart      # restart both bots (no git pull)
#   ./deploy.sh restart 400  # restart only exp400
#   ./deploy.sh restart 401  # restart only exp401
#   ./deploy.sh stop         # gracefully stop both (launchd won't restart)
#   ./deploy.sh start        # re-register and start both (after stop)
#   ./deploy.sh status       # show running status for both bots
#   ./deploy.sh logs         # tail -f both logs (Ctrl-C to exit)
#   ./deploy.sh logs 400     # tail only exp400
#   ./deploy.sh logs 401     # tail only exp401

set -e

PROJ=/Users/charlesbot/projects/pilotai-credit-spreads
LOGS=/Users/charlesbot/logs
LAUNCHD_DIR=/Users/charlesbot/Library/LaunchAgents
BOTS=(400 401)
UID_=$(id -u)

label() { echo "com.pilotai.exp${1}"; }
plist() { echo "${LAUNCHD_DIR}/com.pilotai.exp${1}.plist"; }
logfile() { echo "${LOGS}/exp${1}.log"; }

# ─── helpers ──────────────────────────────────────────────────────────────────

is_loaded() {
    launchctl list "$(label "$1")" &>/dev/null
}

is_running() {
    local pid
    pid=$(launchctl list "$(label "$1")" 2>/dev/null | awk '/PID/ {print $3}' | tr -d '";')
    [[ -n "$pid" && "$pid" != "-" && "$pid" != "0" ]]
}

print_status() {
    local bot=$1
    local lbl
    lbl=$(label "$bot")
    if ! is_loaded "$bot"; then
        printf "  exp%s  %-10s  %s\n" "$bot" "UNLOADED" "(not registered with launchd)"
        return
    fi
    local info
    info=$(launchctl list "$lbl" 2>/dev/null)
    local pid
    pid=$(echo "$info" | awk '/"PID"/ {gsub(/[^0-9]/, "", $3); print $3}')
    local last_exit
    last_exit=$(echo "$info" | awk '/"LastExitStatus"/ {gsub(/[^0-9-]/, "", $3); print $3}')
    if [[ -n "$pid" && "$pid" != "0" ]]; then
        printf "  exp%s  %-10s  pid=%s\n" "$bot" "RUNNING" "$pid"
    else
        printf "  exp%s  %-10s  last_exit=%s\n" "$bot" "STOPPED" "${last_exit:-?}"
    fi
}

do_restart() {
    local bot=$1
    local lbl
    lbl=$(label "$bot")
    if is_loaded "$bot"; then
        echo "  Restarting exp${bot} (kickstart -k)..."
        launchctl kickstart -k "gui/${UID_}/${lbl}"
    else
        echo "  exp${bot} not loaded — loading and starting..."
        launchctl load "$(plist "$bot")"
    fi
}

do_stop() {
    local bot=$1
    local lbl
    lbl=$(label "$bot")
    if is_loaded "$bot"; then
        echo "  Stopping exp${bot} (unload — will not auto-restart)..."
        launchctl unload "$(plist "$bot")"
    else
        echo "  exp${bot} already unloaded."
    fi
}

do_start() {
    local bot=$1
    if is_loaded "$bot"; then
        echo "  exp${bot} already loaded — use 'restart' to bounce it."
    else
        echo "  Loading and starting exp${bot}..."
        launchctl load "$(plist "$bot")"
    fi
}

# ─── commands ─────────────────────────────────────────────────────────────────

cmd_status() {
    echo "PilotAI bots:"
    for b in "${BOTS[@]}"; do
        print_status "$b"
    done
}

cmd_restart() {
    local target=${1:-"all"}
    if [[ "$target" == "all" ]]; then
        for b in "${BOTS[@]}"; do do_restart "$b"; done
    else
        do_restart "$target"
    fi
    sleep 2
    echo ""
    cmd_status
}

cmd_stop() {
    local target=${1:-"all"}
    if [[ "$target" == "all" ]]; then
        for b in "${BOTS[@]}"; do do_stop "$b"; done
    else
        do_stop "$target"
    fi
    cmd_status
}

cmd_start() {
    local target=${1:-"all"}
    if [[ "$target" == "all" ]]; then
        for b in "${BOTS[@]}"; do do_start "$b"; done
    else
        do_start "$target"
    fi
    sleep 2
    cmd_status
}

cmd_logs() {
    local target=${1:-"all"}
    mkdir -p "$LOGS"
    if [[ "$target" == "all" ]]; then
        echo "Tailing exp400 + exp401 logs (Ctrl-C to exit)..."
        tail -f "$(logfile 400)" "$(logfile 401)" 2>/dev/null || \
            tail -f "$(logfile 400)" 2>/dev/null || \
            echo "No log files found yet in ${LOGS}/"
    else
        echo "Tailing exp${target} log (Ctrl-C to exit)..."
        tail -f "$(logfile "$target")"
    fi
}

cmd_deploy() {
    echo "==> Pulling latest code from origin/main..."
    cd "$PROJ"
    git pull origin main
    echo ""
    echo "==> Restarting bots..."
    for b in "${BOTS[@]}"; do do_restart "$b"; done
    sleep 2
    echo ""
    cmd_status
    echo ""
    echo "==> Logs: tail -f ~/logs/exp400.log ~/logs/exp401.log"
}

# ─── dispatch ─────────────────────────────────────────────────────────────────

CMD=${1:-deploy}
ARG=${2:-all}

case "$CMD" in
    status)          cmd_status ;;
    restart)         cmd_restart "$ARG" ;;
    stop)            cmd_stop    "$ARG" ;;
    start)           cmd_start   "$ARG" ;;
    logs)            cmd_logs    "$ARG" ;;
    deploy|"")       cmd_deploy ;;
    *)
        echo "Unknown command: $CMD"
        echo "Usage: $0 {deploy|restart|stop|start|status|logs} [400|401]"
        exit 1
        ;;
esac
