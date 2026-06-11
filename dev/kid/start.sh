#!/bin/bash
HAVEN_ROOT="${HAVEN_ROOT:-/mnt/z/Haven}"
DIR="$HAVEN_ROOT/dev/kid"
VENV="$HAVEN_ROOT/.venv"
cd "$DIR" || { echo "ERROR: cannot cd to $DIR"; exit 1; }
if [ ! -f "$VENV/bin/python" ]; then
    echo "ERROR: venv not found at $VENV"
    exit 1
fi
echo "Starting Haven..."
exec "$VENV/bin/python" main.py
