#!/bin/bash
# haven_stop.sh — 安全關閉 Haven（PID 精準擊殺）
# 用法:
#   bash /mnt/z/Haven/haven_stop.sh

PIDFILE="/tmp/haven.pid"

if [ ! -f "$PIDFILE" ]; then
    echo "Haven is not running (no PID file)."
    exit 0
fi

PID=$(cat "$PIDFILE")

if ! kill -0 "$PID" 2>/dev/null; then
    echo "PID file exists but process $PID is gone — cleaning up stale PID file."
    rm -f "$PIDFILE"
    exit 0
fi

echo "Sending graceful stop (SIGINT) to Haven PID $PID..."
kill -2 "$PID"
sleep 5

if kill -0 "$PID" 2>/dev/null; then
    echo "Still alive, sending SIGTERM..."
    kill -15 "$PID"
    sleep 5
    if kill -0 "$PID" 2>/dev/null; then
        echo "Force killing (SIGKILL)..."
        kill -9 "$PID"
        sleep 1
    fi
fi

rm -f "$PIDFILE"
echo "Haven stopped."
