"""Path resolution for Haven — single source of truth.

All filesystem paths are derived from HAVEN_ROOT and CORE_ROOT
environment variables. When neither is set, paths match the legacy
WSL2 layout (``/mnt/z/Haven``, ``/mnt/z/Core``) for full backward
compatibility.

Usage::

    from core.paths import haven_dir, core_env, venv_dir

    load_dotenv(str(haven_env()))
    python = venv_dir() / "bin" / "python"
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Root directories ────────────────────────────────────────────────────────

HAVEN_ROOT = Path(os.getenv("HAVEN_ROOT", "/mnt/z/Haven"))
"""Haven 的家目錄。所有 Haven 程式碼、設定、資料的根。"""

CORE_ROOT = Path(os.getenv("CORE_ROOT", "/mnt/z/Core"))
"""KID 核心目錄。通用身份、長期記憶的根。"""


def haven_dir() -> Path:
    """``$HAVEN_ROOT``"""
    return HAVEN_ROOT


def core_dir() -> Path:
    """``$CORE_ROOT``"""
    return CORE_ROOT


# ── Haven-scoped directories ────────────────────────────────────────────────

def code_dir() -> Path:
    """Haven 程式碼目錄 ``$HAVEN_ROOT/dev/kid``."""
    return haven_dir() / "dev" / "kid"


def config_dir() -> Path:
    """設定檔目錄 ``$HAVEN_ROOT/config``."""
    return haven_dir() / "config"


def data_dir() -> Path:
    """資料目錄 ``$HAVEN_ROOT/data``."""
    return haven_dir() / "data"


def session_dir() -> Path:
    """短期對話儲存 ``$HAVEN_ROOT/data/sessions``."""
    return data_dir() / "sessions"


def ltm_dir() -> Path:
    """長期記憶儲存 ``$HAVEN_ROOT/data/long_term_memory``."""
    return data_dir() / "long_term_memory"


def skills_dir() -> Path:
    """技能學習儲存 ``$HAVEN_ROOT/data/skills``."""
    return data_dir() / "skills"


def venv_dir() -> Path:
    """Python 虛擬環境 ``$HAVEN_ROOT/.venv``."""
    return haven_dir() / ".venv"


# ── Environment files ───────────────────────────────────────────────────────

def haven_env() -> Path:
    """Haven ``.env`` — 優先 ``config/.env``，fallback 到 ``HAVEN_ROOT/.env``."""
    custom = config_dir() / ".env"
    if custom.exists():
        return custom
    return haven_dir() / ".env"


def core_env() -> Path:
    """Core ``.env`` — KID 通用 credentials."""
    return core_dir() / ".env"


def openclaw_env() -> Path:
    """OpenClaw Gateway env file."""
    return Path(os.getenv("OPENCLAW_ENV", "/root/.openclaw/env"))


# ── Runtime files ───────────────────────────────────────────────────────────

def log_file() -> Path:
    """Haven 執行記錄檔."""
    return Path(os.getenv("HAVEN_LOG_FILE", "/tmp/haven.log"))


def pid_file() -> Path:
    """Haven PID file."""
    return Path(os.getenv("HAVEN_PID_FILE", "/tmp/haven.pid"))


# ── Soul / Identity files ───────────────────────────────────────────────────

def identity_file() -> Path:
    """KID 身份檔."""
    return haven_dir() / "IDENTITY.md"


def soul_file() -> Path:
    """靈魂設定檔."""
    return haven_dir() / "SOUL.md"


def user_file() -> Path:
    """使用者資訊檔."""
    return haven_dir() / "USER.md"


def memory_file() -> Path:
    """長期記憶檔."""
    return haven_dir() / "MEMORY.md"


def agents_file() -> Path:
    """行為規則檔."""
    return haven_dir() / "AGENTS.md"


def chronicle_file() -> Path:
    """靈魂編年史."""
    return core_dir() / "Soul" / "Chronicle.md"
