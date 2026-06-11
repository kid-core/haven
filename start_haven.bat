@echo off
setlocal enabledelayedexpansion

echo Starting Haven...
echo ===========================================
echo  Close window  = Haven keeps running
echo  Ctrl+B D      = detach monitor (safe)
echo  Type 'exit'   = close monitor only
echo ===========================================
echo.

wsl -d Seed_System -u root -- bash /mnt/z/Haven/haven_tmux.sh

pause
