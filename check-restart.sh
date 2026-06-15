#!/bin/bash

set -e

BOT_DIR="/home/myllymik/chatgpt"
BOT_SCRIPT="aimo.py"
CONFIG_FILE="aimo.conf"
SESSION_NAME="chatgpt"
FORCE_RESTART=0

if [ "${1:-}" = "--force" ]; then
    FORCE_RESTART=1
fi

cd "$BOT_DIR"
mkdir -p logs

is_running() {
    pgrep -f "python3 $BOT_SCRIPT --config $CONFIG_FILE --run-discord" >/dev/null 2>&1
}

screen_session_exists() {
    screen -ls 2>/dev/null | grep -q "[.]$SESSION_NAME[[:space:]]"
}

start_bot() {
    echo "Starting Aimo v3..."
    screen -dmS "$SESSION_NAME" bash -c "
cd '$BOT_DIR'
source venv/bin/activate
python3 '$BOT_SCRIPT' --config '$CONFIG_FILE' --run-discord >> logs/bot.log 2>&1
"
}

stop_bot() {
    pkill -f "python3 $BOT_SCRIPT" || true
    screen -S "$SESSION_NAME" -X quit >/dev/null 2>&1 || true
}

if [ "$FORCE_RESTART" -eq 1 ]; then
    echo "Force restarting Aimo v3..."
    stop_bot
    sleep 2
    start_bot
    echo "Restart complete"
    exit 0
fi

if is_running && screen_session_exists; then
    echo "Aimo v3 already running with active screen session; nothing to do."
    exit 0
fi

if screen_session_exists && ! is_running; then
    echo "Screen session exists but Aimo v3 process is missing; restarting..."
    screen -S "$SESSION_NAME" -X quit >/dev/null 2>&1 || true
    sleep 2
    start_bot
    echo "Start complete"
    exit 0
fi

echo "Aimo v3 not running; starting it now..."
start_bot

echo "Start complete"
