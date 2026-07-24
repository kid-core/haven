#!/bin/bash
# haven_tmux.sh — tmux 包裝層：背景運行 + 浮動監控視窗
# 用法:
#   bash /mnt/z/haven/scripts/tmux.sh          — 啟動 + 自動 attach
#   bash /mnt/z/haven/scripts/tmux.sh --attach — 只 attach 監控
#   bash /mnt/z/haven/scripts/tmux.sh --nodetach — 啟動不 attach
#
# 設計: tmux 只是「監控鏡頭」，關閉不影響 Haven 背景行程

HAVEN_ROOT="${HAVEN_ROOT:-/mnt/z/haven}"

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

# ── 確保 pkill 可用 ──
if ! command -v pkill &>/dev/null; then
    echo "Installing psmisc..."
    apt-get install -y -qq psmisc 2>/dev/null
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

# ── 🔪 徹底清場 ──
echo "Cleaning up all stale resources..."

# 1) 殺掉所有 main.py 進程
pkill -9 -f "main.py" 2>/dev/null
sleep 1
# 二次確認
STILL=$(pgrep -f "main.py" 2>/dev/null)
if [ -n "$STILL" ]; then
    echo "Force-killing stubborn processes: $STILL"
    kill -9 $STILL 2>/dev/null
    sleep 1
fi

# 2) 殺掉舊 tmux session（可能是雙開的根源）
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Killing old tmux session '$SESSION'..."
    tmux kill-session -t "$SESSION" 2>/dev/null
    sleep 0.5
fi

# 3) 清除舊 PID 檔
rm -f "$PIDFILE"

echo "Cleanup complete. No stale Haven or tmux remain."

# ── 🔒 PID 鎖：防止雙開 ──
# 萬一有另一個 haven_tmux.sh 同時跑，先搶到 PID file 的贏
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "ERROR: Haven is already running (PID $OLD_PID). Aborting."
        exit 1
    fi
    rm -f "$PIDFILE"
fi

# ── 啟動 Haven 背景 ──
echo "Starting Haven (single instance)..."
> "$LOGFILE"  # 清空舊日誌
cd "$HAVEN_ROOT/src"
export HAVEN_NO_TERMINAL=1
"$HAVEN_ROOT/.venv/bin/python" main.py >> "$LOGFILE" 2>&1 &
PID=$!
echo $PID > "$PIDFILE"
echo "Haven PID: $PID | Log: $LOGFILE"

# ── 建立 detached tmux 監控 session ──
tmux new-session -d -s "$SESSION" \
    "echo '📡 Haven Monitor — PID $PID'; echo '══════════════════════════════'; echo '  Ctrl+B D = detach (leave running)'; echo '  exit/quit here = close monitor only'; echo '══════════════════════════════'; echo ''; tail -f $LOGFILE"

echo "Tmux session '$SESSION' started."
echo ""
if [ "$MODE" = "--nodetach" ]; then
    echo "Running in background (no attach)."
    echo "To monitor: bash $HAVEN_ROOT/scripts/tmux.sh --attach"
    echo "To stop:   bash $HAVEN_ROOT/scripts/stop.sh"
    exit 0
fi
echo "Attaching to monitor..."
sleep 1
tmux attach -t "$SESSION"
