"""File-system guard: path whitelist / blacklist for all tool I/O.

Phase 1 of Haven shell security upgrade (2026-06-27).
Used by write_file and execute_command to enforce safe write boundaries.

Design:
  - ALLOWED_RW: paths where writes are always permitted.
  - BLOCKED:    paths where writes are always refused (even with sudo).
  - is_write_allowed(path) → bool + reason
  - extract_paths(cmd)     → list of path-like tokens in a shell command
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Tuple


# ── Whitelist: paths where writes are permitted ────────────────────────────

ALLOWED_RW: list[str] = [
    "/mnt/z/haven/",
    "/mnt/z/Trash/",
    "/tmp/haven",
]

# ── Blacklist: paths where writes are NEVER permitted ──────────────────────

BLOCKED: list[str] = [
    "/etc/",
    "/boot/",
    "/sys/",
    "/proc/",
    "/mnt/z/haven/.git/",
    "/mnt/z/Core/",
    "/mnt/z/舊系統Archive/",
    "/root/.ssh/",
    "/home/",
    "/root/",
    "/usr/",
    "/lib/",
    "/bin/",
    "/sbin/",
    "/var/",
    "/dev/",
    "/run/",
    "/mnt/c/",
    "/mnt/d/",
    "/mnt/wsl/",
    "/mnt/wslg/",
    "/mnt/z/haven/.venv/bin/",
]

# ── Paths that can be read but NOT written ─────────────────────────────────

READONLY_SYSTEM: list[str] = [
    "/mnt/z/haven/src/",
    "/mnt/z/haven/soul/",
    "/mnt/z/haven/pyproject.toml",
    "/mnt/z/haven/requirements.txt",
    "/mnt/z/haven/ruff.toml",
    "/mnt/z/haven/.gitignore",
]


def _resolve(path: str) -> str:
    """Resolve to absolute real path, normalising for comparison."""
    try:
        return os.path.realpath(os.path.abspath(path))
    except OSError:
        return os.path.abspath(path)


def _normalise(p: str) -> str:
    """Ensure path ends with / for directory prefix matching, or is a file."""
    p = p.rstrip("/")
    if os.path.isdir(p) or p.endswith("/"):
        return p + "/"
    return p


def is_write_allowed(path: str) -> Tuple[bool, str]:
    """Check whether writing to *path* is permitted.

    Returns (allowed: bool, reason: str).

    Rules (checked in order):
      1. BLOCKED     → refused immediately
      2. ALLOWED_RW  → permitted
      3. config.allowed_prefix → permitted (test fixture support)
      4. READONLY_SYSTEM → refused for write
      5. everything else → refused (default-deny)
    """
    from core.config import config

    resolved = _resolve(path)

    # 1. Blacklist check
    for blocked in BLOCKED:
        blocked_norm = _normalise(blocked)
        if resolved.startswith(blocked_norm) or resolved == blocked_norm.rstrip("/"):
            return False, f"Path '{path}' is in the blocked zone ({blocked})"

    # 2. Read-only system files (check before whitelist — these override haven blanket)
    for ro in READONLY_SYSTEM:
        ro_norm = _normalise(ro)
        if resolved.startswith(ro_norm) or resolved == ro_norm.rstrip("/"):
            return False, f"Path '{path}' is in the read-only zone ({ro}). Use /mnt/z/haven/tmp/ or /tmp/haven* for scratch files."

    # 3. Whitelist check
    for allowed in ALLOWED_RW:
        allowed_norm = _normalise(allowed)
        if resolved.startswith(allowed_norm):
            return True, ""

    # 4. Config allowed_prefix (test fixture + overrides)
    if config.allowed_prefix and resolved.startswith(config.allowed_prefix):
        return True, ""

    # 5. Default deny
    return False, f"Path '{path}' is outside the allowed write zones"


def extract_paths(cmd: str) -> list[str]:
    """Extract path-like tokens from a shell command string.

    Heuristic: split the command, keep tokens that look like paths
    (start with /, ./, ../, or ~/). Handles Windows Z:\\ paths too.

    Uses simple whitespace split first; falls back to shlex only when
    the command contains quoted arguments and no Windows backslash paths.
    """
    paths: list[str] = []
    parts = cmd.split()

    # Use shlex for quoted strings only if no Windows backslash paths present
    has_backslash_paths = any(
        len(p) >= 3 and p[0].isalpha() and p[1] == ":" and p[2] == "\\"
        for p in parts
    )
    if not has_backslash_paths:
        try:
            shlex_parts = shlex.split(cmd, posix=True)
            if len(shlex_parts) > len(parts):
                parts = shlex_parts
        except ValueError:
            pass

    for part in parts:
        if not part:
            continue

        # Absolute Linux path
        if part.startswith("/"):
            paths.append(part)

        # Relative path
        elif part.startswith("./") or part.startswith("../"):
            paths.append(part)

        # Home path
        elif part.startswith("~/"):
            paths.append(os.path.expanduser(part))

        # Windows drive letter (Z:\\...)
        elif len(part) >= 3 and part[0].isalpha() and part[1] == ":" and part[2] in ("\\", "/"):
            # Translate to Linux mount
            resolved = "/mnt/" + part[0].lower() + "/" + part[3:].replace("\\", "/")
            paths.append(resolved)

    return paths
