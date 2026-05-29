#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
source /mnt/z/Core/.venv/bin/activate
echo "🏝️  Starting Haven..."
echo "     Ctrl+C to stop gracefully"
python main.py
