"""Tool policy layer — per-tool gates, rate limiting, and profiles.

Phase 0: ToolPolicy, ToolProfile, and policy enforcement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ToolPolicy:
    """Per-tool gating configuration.

    enabled:
        If False, the tool is completely disabled (returns policy-blocked error).
    require_confirm:
        If True, tool execution must be confirmed before running.
        The router will return a confirmation request instead of executing.
    rate_limit:
        Minimum seconds between calls to the same tool.  Enforced by the registry.
        None means no rate limit.
    timeout:
        Max seconds a tool may run.  Enforced by the router via asyncio.wait_for.
        None means no timeout (or inherits from default).
    """

    enabled: bool = True
    require_confirm: bool = False
    rate_limit: float | None = None
    timeout: float | None = None


# ---------------------------------------------------------------------------
# Rate-limit tracker
# ---------------------------------------------------------------------------

@dataclass
class RateLimitTracker:
    """Tracks last execution time per tool for rate limiting."""

    _last_called: dict[str, float] = field(default_factory=dict)

    def check(self, name: str, rate_limit: float) -> tuple[bool, float]:
        """Check if *name* can execute given *rate_limit* seconds between calls.

        Returns (allowed, wait_seconds).
        """
        now = time.monotonic()
        last = self._last_called.get(name, 0.0)
        elapsed = now - last
        if elapsed < rate_limit:
            return False, round(rate_limit - elapsed, 1)
        return True, 0.0

    def record(self, name: str) -> None:
        """Mark *name* as just executed."""
        self._last_called[name] = time.monotonic()


# ---------------------------------------------------------------------------
# ToolProfile — per-session/channel visibility rules
# ---------------------------------------------------------------------------

@dataclass
class ToolProfile:
    """Per-session or per-channel tool visibility preset.

    Applied by the Router at session start to disable/enable
    specific tools beyond their own ToolPolicy.enabled setting.
    Used in Phase 2+ for session-level tool gating.

    rules:
        Dict mapping tool_name → enabled (bool).
        Tools not listed inherit their own ToolPolicy.enabled setting.
    name:
        Human-readable label for this profile (e.g. "safe", "coding").
    """

    name: str = "default"
    rules: dict[str, bool] = field(default_factory=dict)

    def is_enabled(self, tool_name: str, default: bool) -> bool:
        """Check if *tool_name* is enabled under this profile.

        Falls back to *default* (the tool's own policy.enabled) if not listed.
        """
        return self.rules.get(tool_name, default)


# ---------------------------------------------------------------------------
# Pre-built profiles
# ---------------------------------------------------------------------------

SAFE_PROFILE = ToolProfile(
    name="safe",
    rules={
        "execute_command": False,   # no shell in safe mode
        "write_file": False,        # no writes
    },
)

CODING_PROFILE = ToolProfile(
    name="coding",
    rules={
        "execute_command": True,
        "write_file": True,
        "read_file": True,
        "web_search": True,
    },
)

READONLY_PROFILE = ToolProfile(
    name="readonly",
    rules={
        "execute_command": False,
        "write_file": False,
    },
)
