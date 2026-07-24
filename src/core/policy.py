"""Tool policy layer — per-tool gates, rate limiting, and profiles.

Phase 0: ToolPolicy, ToolProfile, and policy enforcement.
Phase 2: COMMAND_TIERS for shell command risk classification.
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

    def check(self, name: str, rate_limit: float | None) -> tuple[bool, float]:
        """Check if *name* can execute given *rate_limit* seconds between calls.

        ``rate_limit=None`` or ``0.0`` means no rate limit.
        Returns (allowed, wait_seconds).
        """
        if not rate_limit:
            return True, 0.0
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


# ---------------------------------------------------------------------------
# COMMAND_TIERS — risk classification for shell commands (Phase 2)
# ---------------------------------------------------------------------------

READONLY_COMMANDS: frozenset[str] = frozenset({
    "ls", "cat", "head", "tail", "find", "grep", "ps", "df", "du",
    "echo", "pwd", "whoami", "wc", "sort", "uniq", "cut", "tr",
    "stat", "file", "which", "type", "env", "printenv", "date",
})

NORMAL_COMMANDS: frozenset[str] = frozenset({
    "python3", "python", "pip", "pip3",
    "git",      # base git; push/push --force blocked separately
    "mkdir", "cp", "mv", "rm",  # fs ops allowed but rate-limited (file_guard blocks danger zones)
    "curl", "wget",
    "touch", "chmod", "chown",
    "tar", "gzip", "gunzip", "zip", "unzip",
    "ln", "nano",
})

DANGEROUS_COMMANDS: frozenset[str] = frozenset({
    "dd", "mkfs", "shred",
    "sudo", "su",
    "shutdown", "reboot", "halt",
    "systemctl", "service",
    "iptables", "ufw", "firewall-cmd",
    "kill", "pkill", "killall",
    "mount", "umount",
    "fdisk", "parted", "mkfs.ext4", "mkswap",
    "docker", "podman",
})

# DANGEROUS sub-commands (e.g. "git push --force")
DANGEROUS_SUBCOMMANDS: frozenset[str] = frozenset({
    "push --force", "push -f", "push --force-with-lease",
    "reset --hard", "clean -fd",
    "install",  # pip install
})

REDIRECT_TOKENS: frozenset[str] = frozenset({">", ">>", "2>", "&>"})


def classify_command(base: str, cmd: str) -> tuple[str, str]:
    """Classify a shell command into a risk tier.

    Returns (tier, reason).

    Tiers:
        READONLY  — no rate limit, no filter (ls, cat, grep, ...)
        NORMAL    — rate limited, file_guard applies (python, git, mkdir, ...)
        DANGEROUS — requires confirmation (dd, sudo, kill, ...)

    Redirects (>, >>, 2>, &>) are NOT blocked at this layer.
    They are validated by file_guard in execute_command().
    """
    cmd_lower = cmd.lower().strip()

    # Redirect detection: any command with > or >> cannot be READONLY.
    # Force NORMAL so file_guard validates the redirect target path.
    has_redirect = any(tok in cmd_lower for tok in (">", ">>"))

    # Check dangerous sub-commands (pip install, git push -f, etc.)
    for sub in DANGEROUS_SUBCOMMANDS:
        if f"{base} {sub}" in cmd_lower or cmd_lower.startswith(f"{base} {sub}"):
            return "DANGEROUS", f"'{base} {sub}' requires confirmation"

    # Check dangerous commands
    base_clean = base.split("/")[-1]
    for dangerous in DANGEROUS_COMMANDS:
        if base_clean == dangerous or base_clean.startswith(dangerous):
            return "DANGEROUS", f"Command '{base}' requires confirmation (dangerous tier)"

    # Check readonly commands
    for ro in READONLY_COMMANDS:
        if base_clean == ro:
            if has_redirect:
                return "NORMAL", ""
            return "READONLY", ""

    # Default: NORMAL
    return "NORMAL", ""
