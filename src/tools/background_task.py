"""Background task tool — fire-and-forget task spawning (Phase 6 + Phase 1).

Phase 6: Basic background agent spawning via TaskManager.
Phase 1: Auto Resume — checkpoint on timeout, auto-respawn with retry counter.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.resource_gate import resource_gate
from core.tool_decorator import tool

if TYPE_CHECKING:
    from core.task_manager import TaskContext, TaskManager

logger = logging.getLogger(__name__)

_task_manager: TaskManager | None = None
_background_providers: list | None = None
_background_tool_registry = None
_background_estimator = None


def set_task_manager(mgr: TaskManager) -> None:
    global _task_manager
    _task_manager = mgr


def set_background_context(providers, tool_registry, complexity_estimator=None):
    global _background_providers, _background_tool_registry, _background_estimator
    _background_providers = providers
    _background_tool_registry = tool_registry
    _background_estimator = complexity_estimator


def get_task_manager() -> TaskManager | None:
    return _task_manager


def _git_diff_snapshot() -> str:
    """Return a git diff --stat snapshot for checkpoint context."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, timeout=5,
            cwd="/mnt/z/haven",
        )
        if result.stdout.strip():
            return f"\nFiles already modified (git diff --stat):\n{result.stdout.strip()}\n"
    except Exception:
        pass
    return ""


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
    max_turns: int | None = None,
    max_retries: int = 2,
) -> dict:
    """Launch an autonomous background agent to accomplish a multi-step goal.

    Phase 1 Auto Resume: on timeout, a fresh agent is spawned (up to
    max_retries times) with checkpoint context.

    Args:
        task_description: Natural-language goal for the agent.
        timeout: Max wall-clock seconds per attempt (default 10 min).
        tools_allow: Restrict tool access to these names only.
        max_turns: Max ReAct iterations, or None for auto-estimate.
        max_retries: Auto-respawn on timeout (default 2, 0=off).

    Returns:
        dict with status='dispatched' and task_id.
    """
    if _task_manager is None:
        return {"status": "error", "error": "TaskManager not wired."}
    if _background_providers is None or _background_tool_registry is None:
        return {"status": "error", "error": "Background agent context not wired."}

    if max_turns is None:
        if _background_estimator is not None:
            max_turns = _background_estimator.estimate_turns(task_description)
        else:
            from core.task_complexity import TaskComplexityEstimator
            max_turns = TaskComplexityEstimator().estimate_turns(task_description)
        timeout = max(timeout, max_turns * 30 + 60)

    from core.background_agent import BackgroundAgent
    from core.checkpoint import Checkpoint, save

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

    async def _runner_with_retry() -> str:
        """Run agent with auto-resume on timeout (Phase 1)."""
        for attempt in range(1, max_retries + 2):  # 1 initial + N retries
            retry_label = "" if attempt == 1 else f" (retry {attempt - 1}/{max_retries})"

            # On retry, build a fresh agent with checkpoint context
            if attempt > 1:
                logger.warning("Background agent timeout — retry %d/%d", attempt - 1, max_retries)
                cp = Checkpoint(
                    goal=task_description,
                    completed=[],
                    last_action="Timed out",
                    next_step="Retry with fresh agent",
                    node_id=f"bg_{abs(hash(task_description)) % 10**8}",
                    iteration=attempt - 1,
                )
                save(cp)

                augmented_task = (
                    f"[AUTO-RESUME — attempt {attempt - 1}/{max_retries}]\n\n"
                    f"Previous attempt timed out. Fresh agent taking over.\n"
                    f"Original task:\n  {task_description}\n"
                    f"{_git_diff_snapshot()}"
                    f"Check the files listed above BEFORE continuing."
                )
                from core.message_bus import TaskContext as MsgBusTaskContext
                ctx = MsgBusTaskContext("", _task_manager.message_bus)
                agent = BackgroundAgent(
                    goal=augmented_task,
                    tool_registry=_background_tool_registry,
                    providers=_background_providers,
                    task_context=ctx,
                    tools_allow=tools_allow,
                    max_turns=max_turns,
                    timeout=timeout,
                )
            else:
                from core.message_bus import TaskContext as MsgBusTaskContext
                ctx = MsgBusTaskContext("", _task_manager.message_bus)
                agent = BackgroundAgent(
                    goal=task_description,
                    tool_registry=_background_tool_registry,
                    providers=_background_providers,
                    task_context=ctx,
                    tools_allow=tools_allow,
                    max_turns=max_turns,
                    timeout=timeout,
                )

            try:
                return await asyncio.wait_for(agent.run(), timeout=timeout)
            except TimeoutError:
                if attempt > max_retries:
                    return (
                        f"[background error] Timed out after {timeout}s. "
                        f"Retries exhausted ({max_retries}/{max_retries})."
                    )
                continue

        return "[background error] Unexpected retry loop exit."

    # Total timeout = per-attempt timeout * (1 + retries) + buffer
    total_timeout = timeout * (max_retries + 1) + 120

    tid = await _task_manager.spawn(
        _runner_with_retry(),
        name=(task_description or "")[:80] or "background-agent",
        timeout=total_timeout,
        metadata={
            "type": "background_agent",
            "goal": (task_description or "")[:200],
            "max_turns": str(max_turns),
            "max_retries": str(max_retries),
            "per_attempt_timeout": str(timeout),
        },
    )
    logger.info(
        "Background agent dispatched: %s → turns=%d timeout=%.0fs/attempt retries=%d total=%.0fs",
        tid, max_turns, timeout, max_retries, total_timeout,
    )
    return {
        "status": "dispatched",
        "task_id": tid,
        "max_turns": max_turns,
        "timeout": timeout,
        "max_retries": max_retries,
        "total_timeout": total_timeout,
    }
