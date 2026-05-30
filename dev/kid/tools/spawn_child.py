"""Sub-task delegation — spawn isolated child sessions (Phase 4).

Lightweight clone of OpenClaw's sessions_spawn for Haven.
Constraints: max 3 nesting levels, 60s timeout per child, no recursive spawning.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)

MAX_NESTING = 3
DEFAULT_TIMEOUT = 60.0
MAX_RESULT_CHARS = 4000  # truncate results to avoid context bloat


@dataclass
class ChildTask:
    """Metadata for a spawned child task."""

    task_id: str
    parent_id: str
    nesting_level: int
    task: str
    created_at: float
    timeout: float
    status: str = "pending"  # pending → running → done / error / timeout


class SpawnManager:
    """Manages child task lifecycle with nesting limits and timeouts.

    Usage::

        mgr = SpawnManager(router=main_router, parent_id="main")
        result = await mgr.spawn("Summarize the following text: ...", timeout=60)
    """

    def __init__(self, router: "Router", parent_id: str = "main", nesting_level: int = 0) -> None:
        self._router = router
        self._parent_id = parent_id
        self._nesting = nesting_level
        self._children: dict[str, ChildTask] = {}

    async def spawn(self, task: str, timeout: float = DEFAULT_TIMEOUT) -> str:
        """Execute a sub-task in an isolated context and return the result.

        Parameters
        ----------
        task:
            The natural-language task description for the child session.
        timeout:
            Max seconds to wait for the child to complete.

        Returns
        -------
        The child's final response text, or an error message on failure.
        """
        if self._nesting >= MAX_NESTING:
            return f"[spawn error] Max nesting depth ({MAX_NESTING}) exceeded. Cannot spawn child task."

        task_id = uuid.uuid4().hex[:8]
        child = ChildTask(
            task_id=task_id,
            parent_id=self._parent_id,
            nesting_level=self._nesting + 1,
            task=task,
            created_at=asyncio.get_running_loop().time(),
            timeout=timeout,
        )
        self._children[task_id] = child
        logger.info("Spawning child %s (level %d): %s", task_id, child.nesting_level, task[:80])

        try:
            child.status = "running"
            result = await asyncio.wait_for(
                self._router.process(
                    user_message=task,
                    session_id=f"child:{task_id}",
                    max_turns=5,  # children get fewer turns
                ),
                timeout=timeout,
            )
            child.status = "done"
            return result[:MAX_RESULT_CHARS]

        except asyncio.TimeoutError:
            child.status = "timeout"
            return f"[spawn error] Child task {task_id} timed out after {timeout}s."
        except Exception as exc:
            child.status = "error"
            logger.exception("Child task %s failed", task_id)
            return f"[spawn error] Child task {task_id} failed: {exc}"

    def pending_count(self) -> int:
        return sum(1 for c in self._children.values() if c.status in ("pending", "running"))

    def child_status(self, task_id: str) -> dict | None:
        child = self._children.get(task_id)
        if not child:
            return None
        return {"task_id": child.task_id, "status": child.status, "nesting": child.nesting_level,
                "task_preview": child.task[:80]}
