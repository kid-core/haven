"""
Centralised typed configuration for Haven.

All non-secret config values are loaded once from environment variables
at module import time.  The :data:`config` singleton is the single source
of truth — import and use ``from core.config import config`` everywhere.

Secrets (API keys, tokens) stay in ``.env`` / ``os.environ`` and are read
directly — see :class:`core.http_provider.HttpProvider`'s ``api_key_env``
constructor parameter.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class HavenConfig:
    """Typed read-only configuration for all Haven subsystems.

    Every field reads from an environment variable with a sensible default.
    Because this is frozen, values cannot be mutated at runtime —
    change them by setting env vars or editing ``.env``.
    """

    # ── Model names ────────────────────────────────────────────
    primary_model: str = field(
        default_factory=lambda: os.getenv("HAVEN_PRIMARY_MODEL", "deepseek-v4-flash"),
    )
    fallback_model: str = field(
        default_factory=lambda: os.getenv(
            "HAVEN_FALLBACK_MODEL", "google/gemma-4-26b-a4b-it",
        ),
    )
    tertiary_model: str = field(
        default_factory=lambda: os.getenv("HAVEN_TERTIARY_MODEL", "seed-2-0-lite"),
    )
    embed_model: str = field(
        default_factory=lambda: os.getenv("HAVEN_EMBED_MODEL", "nomic-embed-text:latest"),
    )

    # ── Feature flags ──────────────────────────────────────────
    no_terminal: bool = field(
        default_factory=lambda: os.getenv("HAVEN_NO_TERMINAL", "").lower()
        in ("true", "1", "yes"),
    )
    use_vector: bool = field(
        default_factory=lambda: os.getenv("HAVEN_USE_VECTOR", "").lower()
        in ("true", "1", "yes"),
    )
    # allowed_prefix is a property — reads from env at call time
    # allowed_prefix, discord_token, telegram_token are @property
    # (not frozen fields) — they read env at call time so tests can
    # monkeypatch without an importlib.reload.

    @property
    def allowed_prefix(self) -> str:
        return os.getenv("HAVEN_ALLOWED_PREFIX", "/mnt/z/Haven")

    # ── Service URLs ───────────────────────────────────────────
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    )
    heartbeat_url: str = field(
        default_factory=lambda: os.getenv("HAVEN_HEARTBEAT_URL", ""),
    )

    # ── Heartbeat config ───────────────────────────────────────
    heartbeat_interval: float = field(
        default_factory=lambda: float(os.getenv("HAVEN_HEARTBEAT_INTERVAL", "30")),
    )
    heartbeat_threshold: int = field(
        default_factory=lambda: int(os.getenv("HAVEN_HEARTBEAT_THRESHOLD", "3")),
    )
    heartbeat_discord_channel: int = field(
        default_factory=lambda: int(os.getenv("HAVEN_HEARTBEAT_DISCORD_CHANNEL", "0")),
    )
    heartbeat_discord_user: int = field(
        default_factory=lambda: int(os.getenv("HAVEN_HEARTBEAT_DISCORD_USER", "0")),
    )
    heartbeat_telegram_chat: int = field(
        default_factory=lambda: int(os.getenv("HAVEN_HEARTBEAT_TELEGRAM_CHAT", "0")),
    )

    # ── Channel whitelist (no @mention required) ───────────────
    listen_channels: list[int] = field(
        default_factory=lambda: [
            int(c.strip()) for c in os.getenv("HAVEN_LISTEN_CHANNELS", "").split(",") if c.strip()
        ],
    )

    # ── Visibility ───────────────────────────────────────────
    show_tool_calls: bool = field(
        default_factory=lambda: os.getenv("HAVEN_SHOW_TOOL_CALLS", "0") == "1",
    )

    # ── Memory eviction ────────────────────────────────────────
    memory_max_entries: int = field(
        default_factory=lambda: int(os.getenv("HAVEN_MEMORY_MAX_ENTRIES", "1000")),
    )
    memory_eviction_ttl_days: int = field(
        default_factory=lambda: int(os.getenv("HAVEN_MEMORY_EVICTION_TTL_DAYS", "30")),
    )
    memory_eviction_batch: int = field(
        default_factory=lambda: int(os.getenv("HAVEN_MEMORY_EVICTION_BATCH", "50")),
    )

    # ── Transport tokens (properties — hot-reload + test monkeypatch) ──
    @property
    def discord_token(self) -> str:
        return os.getenv("HAVEN_DISCORD_TOKEN", "")

    @property
    def telegram_token(self) -> str:
        return os.getenv("HAVEN_TELEGRAM_TOKEN", "")


# Singleton — import like:  from core.config import config
config = HavenConfig()
