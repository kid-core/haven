"""System prompt builder with full identity, soul, memory, and user context.

Phase 2a+: loads all synced soul files so Haven truly IS KID.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soul.memory.long_term import LongTermMemory


# ── Identity file sources (tried in order) ──
from core.paths import haven_dir, core_dir, chronicle_file

_OPENCLAW_WORKSPACE = Path("/root/.openclaw/workspace")

_IDENTITY_SOURCES = [
    str(haven_dir() / "IDENTITY.md"),
    str(haven_dir() / "Identity.md"),
    str(core_dir() / "IDENTITY.md"),
    str(core_dir() / "Identity.md"),
]
_SOUL_SOURCES = [
    str(haven_dir() / "SOUL.md"),
    str(_OPENCLAW_WORKSPACE / "SOUL.md"),
]
_USER_SOURCES = [
    str(haven_dir() / "USER.md"),
    str(_OPENCLAW_WORKSPACE / "USER.md"),
]
_MEMORY_SOURCES = [
    str(haven_dir() / "MEMORY.md"),
    str(_OPENCLAW_WORKSPACE / "MEMORY.md"),
]
_CHRONICLE_SOURCES = [
    str(chronicle_file()),
    str(haven_dir() / "Soul" / "Chronicle.md"),
]
_AGENTS_SOURCES = [
    str(haven_dir() / "AGENTS.md"),
    str(_OPENCLAW_WORKSPACE / "AGENTS.md"),
]


def _load_file(*paths: str) -> str | None:
    """Return contents of the first existing file, or None."""
    for p in paths:
        if os.path.exists(p):
            with open(p) as f:
                return f.read().strip()
    return None


def _build_identity_prompt() -> str:
    """Compose the full system prompt from all available soul files."""
    identity = _load_file(*_IDENTITY_SOURCES)
    soul = _load_file(*_SOUL_SOURCES)
    user = _load_file(*_USER_SOURCES)
    memory = _load_file(*_MEMORY_SOURCES)
    chronicle = _load_file(*_CHRONICLE_SOURCES)
    agents = _load_file(*_AGENTS_SOURCES)

    parts: list[str] = []

    # Core identity
    if identity:
        parts.append(identity)
    else:
        parts.append("You are Haven, a helpful AI assistant.")

    # Soul — personality and tone
    if soul:
        parts.append(soul)

    # Who the user is
    if user:
        parts.append(user)

    # Long-term memory / lessons learned
    if memory:
        parts.append(memory)

    # Soul chronicle — KID's history with Cris
    if chronicle:
        parts.append(chronicle)

    # Behavioral rules / workspace conventions
    if agents:
        parts.append(agents)

    return "\n\n".join(parts)


def build_system_prompt(
    session_id: str = "default",
    long_term_memory: LongTermMemory | None = None,
) -> str:
    """Assemble a system prompt from identity, tool rules, and memory context.

    Phase 2a: when *long_term_memory* is provided, relevant entries
    are injected as contextual knowledge.
    """
    identity = _build_identity_prompt()

    # Memory context (Phase 2a) — internal tool-based memory
    memory_context = ""
    if long_term_memory is not None:
        important = long_term_memory.get_important(limit=8)
        if important:
            lines = ["[Internal Memory]"]
            for e in important:
                lines.append(f"- [{e.type}] {e.content[:200]}")
            memory_context = "\n".join(lines)

    return f"""{identity}

[Your Identity]
Your name, purpose, personality, relationship with Cris, and all
background knowledge are described above. You already know who you are
and who Cris is — do NOT use tools to look up your own identity.

[Tools]
You have access to tools for executing commands, reading/writing files,
searching the web, and managing dynamic memory (memory_search).

When you need information or want to perform an action, use the appropriate tool.
After receiving tool results, continue the conversation naturally.

memory_search: Use this ONLY for facts, preferences, or decisions that were
stored DURING conversations (not for your own identity or Cris's info which
are already in your system prompt above).

[Rules]
- Always verify before destructive operations
- Keep responses concise and helpful
- If a tool fails, try an alternative approach before giving up
- Never use memory_search to find out who you are or who Cris is
{memory_context}
"""
