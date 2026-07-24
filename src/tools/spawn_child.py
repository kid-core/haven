"""Sub-task delegation — spawn isolated child sessions (Phase 4 + Phase 1).

Phase 4: Basic spawn with nesting limits and timeout.
Phase 1: Auto Resume — checkpoint on timeout, auto-respawn with retry counter.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)

MAX_NESTING = 3
DEFAULT_TIMEOUT = 60.0
MAX_RESULT_CHARS = 4000
DEFAULT_MAX_RETRIES = 2


def _build_checkpoint_task(original_task: str, retry: int, max_retries: int) -> str:
    """Build a checkpoint-augmented task string for the retry agent.

    Includes a git diff snapshot so the fresh agent can verify
    what was actually changed before continuing.
    """
    import subprocess

    diff_snapshot = ""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, timeout=5,
            cwd="/mnt/z/haven",
        )
        if result.stdout.strip():
            diff_snapshot = f"\nFiles already modified (git diff --stat):\n{result.stdout.strip()}\n"
    except Exception:
        pass

    return (
        f"[AUTO-RESUME — attempt {retry}/{max_retries}]\n\n"
        f"Previous attempt timed out. You are a fresh agent taking over.\n"
        f"Original task:\n  {original_task}\n"
        f"{diff_snapshot}"
        f"Important: check the files listed above BEFORE continuing.\n"
        f"Focus on completing the task, not redoing work."
    )


@dataclass
class ChildTask:
    """Metadata for a spawned child task."""

    task_id: str
    parent_id: str
    nesting_level: int
    task: str
    created_at: float
    timeout: float
    status: str = "pending"
    retry_count: int = 0


class SpawnManager:
    """Manages child task lifecycle with nesting limits, timeout, and auto-resume.

    Usage::

        mgr = SpawnManager(router=main_router, parent_id="main")
        result = await mgr.spawn("Summarize the following text: ...", timeout=60)
    """

    def __init__(self, router: Router, parent_id: str = "main", nesting_level: int = 0) -> None:
        self._router = router
        self._parent_id = parent_id
        self._nesting = nesting_level
        self._children: dict[str, ChildTask] = {}

    async def spawn(
        self,
        task: str,
        timeout: float = DEFAULT_TIMEOUT,
        max_turns: int = 10,
        max_retries: int = DEFAULT_MAX_RETRIES,
        _retry_count: int = 0,
    ) -> str:
        """Execute a sub-task with auto-resume on timeout.

        Phase 1: on timeout, writes checkpoint context and respawns
        a fresh child (up to max_retries times).

        Parameters
        ----------
        task:
            Natural-language task description.
        timeout:
            Max seconds per attempt.
        max_turns:
            Max ReAct iterations per attempt.
        max_retries:
            Max auto-respawn attempts (0 = no retry).
        _retry_count:
            Internal counter — do not set.

        Returns
        -------
        Child response text, or error message.
        """
        if self._nesting >= MAX_NESTING:
            return f"[spawn error] Max nesting depth ({MAX_NESTING}) exceeded."

        task_id = uuid.uuid4().hex[:8]
        child = ChildTask(
            task_id=task_id,
            parent_id=self._parent_id,
            nesting_level=self._nesting + 1,
            task=task,
            created_at=asyncio.get_running_loop().time(),
            timeout=timeout,
            retry_count=_retry_count,
        )
        self._children[task_id] = child
        logger.info(
            "Spawning child %s (level=%d turns=%d timeout=%.0fs retry=%d/%d)",
            task_id, child.nesting_level, max_turns, timeout,
            _retry_count, max_retries,
        )

        try:
            child.status = "running"
            result = await asyncio.wait_for(
                self._router.process(
                    user_message=task,
                    session_id=f"child:{task_id}",
                    max_turns=max_turns,
                ),
                timeout=timeout,
            )
            child.status = "done"
            return result[:MAX_RESULT_CHARS]

        except TimeoutError:
            if _retry_count < max_retries:
                logger.warning(
                    "Child %s timeout (%.0fs) — retry %d/%d",
                    task_id, timeout, _retry_count + 1, max_retries,
                )
                new_task = _build_checkpoint_task(task, _retry_count + 1, max_retries)
                return await self.spawn(
                    task=new_task,
                    timeout=timeout,
                    max_turns=max_turns,
                    max_retries=max_retries,
                    _retry_count=_retry_count + 1,
                )

            child.status = "timeout_blocked"
            return (
                f"[spawn error] Timed out after {timeout}s. "
                f"Retries exhausted ({max_retries}/{max_retries})."
            )

        except Exception as exc:
            child.status = "error"
            logger.exception("Child %s failed", task_id)
            return f"[spawn error] Child {task_id} failed: {exc}"

    def pending_count(self) -> int:
        return sum(1 for c in self._children.values() if c.status in ("pending", "running"))

    def child_status(self, task_id: str) -> dict | None:
        child = self._children.get(task_id)
        if not child:
            return None
        return {
            "task_id": child.task_id,
            "status": child.status,
            "nesting": child.nesting_level,
            "retry_count": child.retry_count,
            "task_preview": child.task[:80],
        }
