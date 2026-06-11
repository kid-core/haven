@echo off
setlocal enabledelayedexpansion

echo Attaching to Haven monitor...
echo.

wsl -d Seed_System -u root -- bash /mnt/z/Haven/haven_tmux.sh --attach

pause
