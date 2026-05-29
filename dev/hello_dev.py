#!/usr/bin/env python3
"""KID Dev Environment - Running in Haven"""
import sys
from pathlib import Path

VENV = Path("/mnt/z/Core/.venv")
DEV = Path("/mnt/z/Haven/dev")

print("🧪 KID Dev Environment (@Haven)")
print(f"  Python : {sys.version.split()[0]}")
print(f"  Venv   : {'✅ Active' if sys.prefix == str(VENV) else '❌ Not active'}")
print(f"  Haven  : {'✅ Live from Haven' if DEV.exists() else 'Missing'}")
print(f"  Core   : Production (untouched)")
print()
print("🚀 Safe to experiment!")
