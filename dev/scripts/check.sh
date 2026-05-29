#!/bin/bash
# Run code quality checks for Haven
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

echo "🔍 Running tests..."
source /mnt/z/Core/.venv/bin/activate
python -m pytest kid/tests/ -v --tb=short

echo ""
echo "📊 Cyclomatic complexity..."
python -m radon cc kid/ -s --min C || echo "⚠️  Some files exceed C grade complexity"

echo ""
echo "✅ Check complete."
