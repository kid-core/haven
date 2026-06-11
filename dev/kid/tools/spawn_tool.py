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
    policy=ToolPolicy(timeout=300.0, rate_limit=30.0, require_confirm=True),
)
@resource_gate(auto_estimate=True)
async def spawn_child(
    task: str,
    timeout: float = 300.0,
    max_turns: int = 10,
) -> str:
    """Delegate a GENUINELY COMPLEX sub-task to an isolated child session.

    ⚠️  ONLY use this when you need 3+ distinct tool calls AND reasoning
    between them.  For single operations (read, write, search, list, move),
    use the dedicated tool directly — do NOT spawn a child.

    Valid: multi-step research, code refactoring, batch file processing.
    INVALID: reading one file, searching one query, running one command.

    Args:
        task:       The complex task for the child session.
        timeout:    Max seconds to wait (default 5 min, max 3600).
        max_turns:  Max ReAct iterations for the child (default 10).

    Returns:
        The child's final response, or an error message.
    """
    if _spawn_manager is None:
        return "[spawn error] Sub-task delegation not configured. SpawnManager not wired."

    # ── Anti-trivial gate: reject obviously single-step tasks ─────
    task_lower = task.lower().strip()
    trivial_patterns = [
        ("read", "Use `read_file` directly instead of spawning a child."),
        ("ls ", "Use `execute_command ls` directly."),
        ("list files", "Use `execute_command ls` directly."),
        ("cat ", "Use `read_file` directly."),
        ("search for", "Use `web_search` directly."),
    ]
    for trigger, advice in trivial_patterns:
        if task_lower.startswith(trigger):
            return f"[spawn rejected] This looks like a single-step task. {advice}"

    if max_turns == 10:  # default → auto-estimate
        from core.task_complexity import TaskComplexityEstimator

        est = TaskComplexityEstimator()
        max_turns = est.estimate_turns(task)
        # Also adjust timeout: base 30s per turn + 60s buffer
        timeout = max(timeout, max_turns * 30 + 60)

    timeout = max(10.0, min(timeout, 3600.0))
    max_turns = max(1, min(max_turns, 50))
    return await _spawn_manager.spawn(task, timeout=timeout, max_turns=max_turns)
