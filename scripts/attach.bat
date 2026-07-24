@echo off
echo Attaching to Haven monitor...
echo Press Ctrl+B then D to detach (Haven keeps running).
echo.
wsl bash /mnt/z/haven/scripts/tmux.sh --attach
pause
