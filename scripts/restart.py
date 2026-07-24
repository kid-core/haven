#!/usr/bin/env python3
"""Restart Haven: kill old PID, wait, start new."""
import os, time, subprocess, signal

LOCK = "/mnt/z/haven/haven.lock"
HAVEN_DIR = "/mnt/z/haven/src"

# Read old PID
try:
    with open(LOCK) as f:
        old_pid = int(f.read().strip())
except (FileNotFoundError, ValueError):
    old_pid = None

# Kill old
if old_pid:
    try:
        os.kill(old_pid, signal.SIGTERM)
        print(f"Killed PID {old_pid}")
    except ProcessLookupError:
        print(f"PID {old_pid} already gone")

time.sleep(2)

# Start new
os.chdir(HAVEN_DIR)
subprocess.Popen(
    ["python3", "main.py"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
)
print("Haven restarted")
