#!/bin/bash
# haven_start.sh — 啟動 Haven（WSL 內用）
# 用法:
#   bash /mnt/z/haven/scripts/start.sh

HAVEN_ROOT="${HAVEN_ROOT:-/mnt/z/haven}"

DIR="$HAVEN_ROOT/src"
VENV="$HAVEN_ROOT/.venv"
PIDFILE="/tmp/haven.pid"

cd "$DIR" || { echo "ERROR: cannot cd to $DIR"; exit 1; }

if [ ! -f "$VENV/bin/python" ]; then
    echo "ERROR: virtual environment not found at $VENV"
    exit 1
fi

# ── 檢查是否已在運行 ──
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Haven is already running (PID $(cat "$PIDFILE"))."
    echo "Use haven_stop.sh first or attach: bash /mnt/z/haven/scripts/attach.sh"
    exit 1
fi

# ── 清理殘留的 stale PID 檔 ──
rm -f "$PIDFILE"

# ── 退出時清理 PID 檔 ──
cleanup() {
    rm -f "$PIDFILE"
    echo ""
    echo "Haven stopped."
}
trap cleanup EXIT INT TERM

echo "Starting Haven..."
"$VENV/bin/python" main.py &
echo $! > "$PIDFILE"
echo "Haven PID: $(cat "$PIDFILE")"
wait
