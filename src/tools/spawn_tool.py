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
    category=ToolCategory.COLLAB,
    policy=ToolPolicy(timeout=300.0, rate_limit=30.0),
)
@resource_gate(auto_estimate=True)
async def spawn_child(
    task: str,
    timeout: float = 300.0,
    max_turns: int = 10,
    max_retries: int = 2,
) -> str:
    """Delegate a complex sub-task to an isolated child session.

    Use when the task requires MULTIPLE tool calls with reasoning BETWEEN
    them.  For single operations, use the dedicated tool directly.

    Phase 1 Auto Resume: on timeout, the child is automatically re-spawned
    (up to max_retries times) with checkpoint context.

    Good: multi-step research, code refactoring, batch file processing.
    Bad:  reading one file, searching one query, one command.

    Args:
        task:        The task for the child session (describe fully).
        timeout:     Max seconds (default 5 min, max 3600).
        max_turns:   Max ReAct iterations (default 10).
        max_retries: Auto-respawn attempts on timeout (default 2, 0=off).

    Returns:
        The child's final response, or an error message.
    """
    if _spawn_manager is None:
        return "[spawn error] Sub-task delegation not configured."

    # ── Soft anti-trivial gate: reject only obvious single-step words ──
    task_first = task.lower().strip().split()[0] if task.strip() else ""
    single_step_verbs = {"read", "ls", "cat", "list", "show", "display", "search", "find", "grep", "echo"}
    if task_first in single_step_verbs and len(task.split()) <= 6:
        return (
            f"[spawn skipped] This looks like a single operation ('{task_first}'). "
            f"Use the `{task_first}` tool directly instead of spawning a child."
        )

    if max_turns == 10:  # default → auto-estimate
        from core.task_complexity import TaskComplexityEstimator

        est = TaskComplexityEstimator()
        max_turns = est.estimate_turns(task)
        # Also adjust timeout: base 30s per turn + 60s buffer
        timeout = max(timeout, max_turns * 30 + 60)

    timeout = max(10.0, min(timeout, 3600.0))
    max_turns = max(1, min(max_turns, 50))
    max_retries = max(0, min(max_retries, 5))
    return await _spawn_manager.spawn(
        task, timeout=timeout, max_turns=max_turns, max_retries=max_retries,
    )
