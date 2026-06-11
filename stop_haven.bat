@echo off
setlocal enabledelayedexpansion

echo Stopping Haven...
echo ========================

wsl -d Seed_System -u root bash /mnt/z/Haven/haven_stop.sh

echo.
pause
