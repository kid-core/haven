"""Background task tool — fire-and-forget task spawning (Phase 6).

Registers as a SYSTEM-category tool. Unlike spawn_child (which waits for a result),
background_task returns immediately with a task_id that can be queried later.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.resource_gate import resource_gate
from core.tool_decorator import tool

if TYPE_CHECKING:
    from core.task_manager import TaskContext, TaskManager

logger = logging.getLogger(__name__)

# Module-level references — injected by Router during init
_task_manager: TaskManager | None = None
_background_providers: list | None = None
_background_tool_registry = None


def set_task_manager(mgr: TaskManager) -> None:
    """Inject the TaskManager (called by Router on init)."""
    global _task_manager  # noqa: PLW0603
    _task_manager = mgr


def set_background_context(
    providers: list,
    tool_registry,
) -> None:
    """Inject provider chain and tool registry for background agents."""
    global _background_providers, _background_tool_registry  # noqa: PLW0603
    _background_providers = providers
    _background_tool_registry = tool_registry


def get_task_manager() -> TaskManager | None:
    """Return the module-level TaskManager, or None if not wired."""
    return _task_manager


@tool(
    name="background_task",
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=10.0, rate_limit=5.0),
)
@resource_gate(auto_estimate=True)
async def background_task(
    task_description: str,
    task_params: dict | None = None,
    timeout: float = 600.0,
    tools_allow: list[str] | None = None,
    max_turns: int = 20,
) -> dict:
    """Launch an autonomous background agent to accomplish a multi-step goal.

    The agent runs its own ReAct loop autonomously — it can call tools,
    analyse results, and continue working without further user input.
    Check progress with query_task / check_task_messages.

    Args:
        task_description: Natural-language goal for the agent.
        task_params: Optional parameters (reserved for future use).
        timeout: Max wall-clock seconds before auto-timeout (default 10 min).
        tools_allow: If set, restrict tool access to these tool names only.
                     Omit or pass null to allow all tools.
        max_turns: Maximum ReAct iterations (default 20).

    Returns:
        dict with status='dispatched' and task_id.
    """
    if _task_manager is None:
        return {"status": "error", "error": "TaskManager not wired. Background tasks unavailable."}

    if _background_providers is None or _background_tool_registry is None:
        return {"status": "error", "error": "Background agent context not wired. Restart Haven."}

    if max_turns == 20:  # default → auto-estimate
        from core.task_complexity import TaskComplexityEstimator

        est = TaskComplexityEstimator()
        max_turns = est.estimate_turns(task_description)
        # Also adjust timeout: base 30s per turn + 60s buffer
        timeout = max(timeout, max_turns * 30 + 60)

    from core.background_agent import BackgroundAgent

    async def _agent_runner(ctx: TaskContext | None = None) -> str:
        agent = BackgroundAgent(
            goal=task_description,
            tool_registry=_background_tool_registry,
            providers=_background_providers,
            task_context=ctx,
            tools_allow=tools_allow,
            max_turns=max_turns,
            timeout=timeout,
        )
        return await agent.run()

    async def _spawn_wrapper() -> str:
        from core.message_bus import TaskContext as MsgBusTaskContext
        ctx = MsgBusTaskContext("", _task_manager.message_bus)
        return await _agent_runner(ctx)

    tid = await _task_manager.spawn(
        _spawn_wrapper(),
        name=(task_description or "")[:80] or "background-agent",
        timeout=timeout + 60,
        metadata={
            "type": "background_agent",
            "goal": (task_description or "")[:200],
            "max_turns": max_turns,
        },
    )
    logger.info(
        "Background agent dispatched: %s → max_turns=%d timeout=%.0fs",
        tid, max_turns, timeout,
    )
    return {"status": "dispatched", "task_id": tid, "max_turns": max_turns, "timeout": timeout}
