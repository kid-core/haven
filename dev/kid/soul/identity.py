"""System prompt builder with long-term memory injection (Phase 2a)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soul.memory.long_term import LongTermMemory


def _load_identity() -> str:
    """Load the core identity from the shared identity file."""
    identity_path = "/mnt/z/Core/identity.md"
    if os.path.exists(identity_path):
        with open(identity_path, "r") as f:
            return f.read().strip()
    return "You are Haven, a helpful AI assistant."


def build_system_prompt(
    session_id: str = "default",
    long_term_memory: "LongTermMemory | None" = None,
) -> str:
    """Assemble a system prompt from identity, tool rules, and memory context.

    Phase 2a: when *long_term_memory* is provided, relevant entries
    are injected as contextual knowledge.
    """
    identity = _load_identity()

    # Memory context (Phase 2a)
    memory_context = ""
    if long_term_memory is not None:
        important = long_term_memory.get_important(limit=8)
        if important:
            lines = ["[Long-Term Memory]"]
            for e in important:
                lines.append(f"- [{e.type}] {e.content[:200]}")
            memory_context = "\n".join(lines)

    return f"""{identity}

[Tools]
You have access to tools for executing commands, reading/writing files, searching the web,
and managing long-term memory (memory_search).

When you need information or want to perform an action, use the appropriate tool.
After receiving tool results, continue the conversation naturally.

Memory: Use memory_search to recall past facts, preferences, or decisions.
Important things you learn should be stored with memory_search action=add.

[Rules]
- Always verify before destructive operations
- Keep responses concise and helpful
- If a tool fails, try an alternative approach before giving up
{memory_context}
"""
