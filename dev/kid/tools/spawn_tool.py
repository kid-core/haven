"""Spawn child task tool — delegates work to isolated sub-sessions (Phase 4).

Registers as a MEMORY-category tool (safe, lightweight delegation).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.resource_gate import resource_gate
from core.tool_decorator import tool

if TYPE_CHECKING:
    from tools.spawn_child import SpawnManager

logger = logging.getLogger(__name__)

# Module-level spawn manager — set by Router during init
_spawn_manager: SpawnManager | None = None


def set_spawn_manager(mgr: SpawnManager) -> None:
    """Inject the spawn manager (called by Router on init)."""
    global _spawn_manager
    _spawn_manager = mgr


@tool(
    category=ToolCategory.MEMORY,
    policy=ToolPolicy(timeout=300.0, rate_limit=30.0),
)
@resource_gate(auto_estimate=True)
async def spawn_child(
    task: str,
    timeout: float = 300.0,
    max_turns: int = 10,
) -> str:
    """Delegate a sub-task to an isolated child session.

    The child runs its own ReAct loop with full tool access, limited turns,
    and returns a single result.  Use for independent work that shouldn't
    pollute the main conversation context.

    Good for: summarization, code analysis, research, document updates.
    Bad for: real-time interactive tasks.

    Args:
        task:       The task description for the child session.
        timeout:    Max seconds to wait (default 5 min, max 3600).
        max_turns:  Max ReAct iterations for the child (default 10).

    Returns:
        The child's final response, or an error message.
    """
    if _spawn_manager is None:
        return "[spawn error] Sub-task delegation not configured. SpawnManager not wired."

    if max_turns == 10:  # default → auto-estimate
        from core.task_complexity import TaskComplexityEstimator

        est = TaskComplexityEstimator()
        max_turns = est.estimate_turns(task)
        # Also adjust timeout: base 30s per turn + 60s buffer
        timeout = max(timeout, max_turns * 30 + 60)

    timeout = max(10.0, min(timeout, 3600.0))
    max_turns = max(1, min(max_turns, 50))
    return await _spawn_manager.spawn(task, timeout=timeout, max_turns=max_turns)
