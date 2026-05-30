"""Spawn child task tool — delegates work to isolated sub-sessions (Phase 4).

Registers as a MEMORY-category tool (safe, lightweight delegation).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.tool_decorator import tool

if TYPE_CHECKING:
    from tools.spawn_child import SpawnManager

logger = logging.getLogger(__name__)

# Module-level spawn manager — set by Router during init
_spawn_manager: "SpawnManager | None" = None


def set_spawn_manager(mgr: "SpawnManager") -> None:
    """Inject the spawn manager (called by Router on init)."""
    global _spawn_manager
    _spawn_manager = mgr


@tool(
    category=ToolCategory.MEMORY,
    policy=ToolPolicy(timeout=65.0, rate_limit=30.0),
)
async def spawn_child(task: str, timeout: float = 60.0) -> str:
    """Delegate a sub-task to an isolated child session.

    Use this when a task can be handled independently without
    polluting the main conversation context. The child runs in
    its own session with limited turns and returns a single result.

    Good for: summarization, code analysis, research lookups.
    Bad for: multi-step interactive tasks, stateful operations.

    Args:
        task:  The task description for the child session.
        timeout: Max seconds to wait (10-120).

    Returns:
        The child's final response, or an error message.
    """
    if _spawn_manager is None:
        return "[spawn error] Sub-task delegation not configured. SpawnManager not wired."

    timeout = max(10.0, min(timeout, 120.0))
    return await _spawn_manager.spawn(task, timeout=timeout)
