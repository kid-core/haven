#!/bin/bash
# haven_tmux.sh — tmux 包裝層：背景運行 + 浮動監控視窗
# 用法:
#   bash /mnt/z/Haven/haven_tmux.sh          — 啟動 + 自動 attach
#   bash /mnt/z/Haven/haven_tmux.sh --attach — 只 attach 監控
#
# 設計: tmux 只是「監控鏡頭」，關閉不影響 Haven 背景行程

HAVEN_ROOT="${HAVEN_ROOT:-/mnt/z/Haven}"

SESSION="haven"
LOGFILE="/tmp/haven.log"
PIDFILE="/tmp/haven.pid"
MODE="${1:-start}"

# ── 確保 tmux 已安裝 ──
if ! command -v tmux &>/dev/null; then
    echo "Installing tmux..."
    apt-get update -qq && apt-get install -y -qq tmux 2>/dev/null
    if ! command -v tmux &>/dev/null; then
        echo "ERROR: tmux install failed. Try: sudo apt install tmux"
        exit 1
    fi
fi

# ── 純 attach 模式 ──
if [ "$MODE" = "--attach" ]; then
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        tmux attach -t "$SESSION"
    else
        echo "No tmux session found. Start Haven first."
        exit 1
    fi
    exit 0
fi

# ── 檢查 Haven 是否已在運行 ──
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Haven is already running (PID $(cat "$PIDFILE"))."
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        tmux attach -t "$SESSION"
    else
        echo "Tmux session missing — creating monitor..."
        tmux new-session -s "$SESSION" "echo '📡 Haven (PID $(cat $PIDFILE)) — live log'; echo '═══════════════════════════════════════'; tail -f $LOGFILE"
    fi
    exit 0
fi

# ── 清理 stale PID ──
rm -f "$PIDFILE"

# ── 啟動 Haven 背景 ──
echo "Starting Haven in background..."
> "$LOGFILE"  # 清空舊日誌
cd "$HAVEN_ROOT/dev/kid"
export HAVEN_NO_TERMINAL=1
"$HAVEN_ROOT/.venv/bin/python" main.py >> "$LOGFILE" 2>&1 &
PID=$!
echo $PID > "$PIDFILE"
echo "Haven PID: $PID | Log: $LOGFILE"

# ── 建立 detached tmux 監控 session ──
tmux new-session -d -s "$SESSION" \
    "echo '📡 Haven Monitor — PID $PID'; echo '═══════════════════════════════'; echo '  Ctrl+B D = detach (leave running)'; echo '  exit/quit here = close monitor only'; echo '═══════════════════════════════'; echo ''; tail -f $LOGFILE"

echo "Tmux session '$SESSION' started."
echo ""
echo "Attaching to monitor..."
sleep 1
tmux attach -t "$SESSION"
