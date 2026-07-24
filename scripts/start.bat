@echo off
echo ================================
echo   Haven Background Launcher
echo ================================
echo.
echo Haven will keep running after you close this window.
echo.
wsl bash /mnt/z/haven/scripts/tmux.sh --nodetach
echo.
echo Haven started in background.
echo Monitor:  wsl bash /mnt/z/haven/scripts/tmux.sh --attach
echo Stop:     wsl bash /mnt/z/haven/scripts/stop.sh
echo.
pause
