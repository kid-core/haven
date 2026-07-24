"""Task query tools — query, cancel, and list background tasks (Phase 6).

Three tools:
- query_task:   lookup a single task's current state
- cancel_task:  cancel a running/pending task
- list_tasks:   list tasks, optionally filtered by status
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.tool_decorator import tool

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _task_to_dict(record) -> dict:
    """Serialise a TaskRecord into a JSON-safe dict."""
    return {
        "task_id": record.task_id,
        "name": record.name,
        "status": record.status.value,
        "created_at": record.created_at.isoformat(),
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
        "result": record.result,
        "error": record.error,
        "timeout": record.timeout,
        "metadata": record.metadata,
        "restored_from": record.restored_from,
    }


@tool(
    name="query_task",
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=5.0),
)
async def query_task(task_id: str) -> dict:
    """Query the current status of a background task.

    Returns task_id, status, result (if completed), error (if failed),
    and timing metadata.

    Args:
        task_id: 12-character hex task id.
    """
    from tools.background_task import get_task_manager

    tm = get_task_manager()
    if tm is None:
        return {"error": "TaskManager not available"}

    record = await tm.get_task(task_id)
    if record is None:
        return {"error": f"Task {task_id} not found", "available_tasks": "Use list_tasks to see active tasks"}

    return _task_to_dict(record)


@tool(
    name="cancel_task",
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=5.0),
)
async def cancel_task(task_id: str) -> dict:
    """Cancel a running or pending background task.

    Args:
        task_id: 12-character hex task id.
    """
    from tools.background_task import get_task_manager

    tm = get_task_manager()
    if tm is None:
        return {"error": "TaskManager not available"}

    cancelled = await tm.cancel_task(task_id)
    if not cancelled:
        # Task might not exist or already terminal
        record = await tm.get_task(task_id)
        if record is None:
            return {"error": f"Task {task_id} not found"}
        return {
            "cancelled": False,
            "task_id": task_id,
            "status": record.status.value,
            "reason": f"Task already in terminal state: {record.status.value}",
        }

    return {"cancelled": True, "task_id": task_id}


@tool(
    name="list_tasks",
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=5.0),
)
async def list_tasks(status: str | None = None, limit: int = 20) -> list[dict]:
    """List background tasks, optionally filtered by status.

    Args:
        status: Filter by status — pending, running, completed, failed, cancelled, timed_out.
        limit: Max number of tasks to return (default 20).
    """
    from core.models import TaskStatus

    from tools.background_task import get_task_manager

    tm = get_task_manager()
    if tm is None:
        return [{"error": "TaskManager not available"}]

    status_filter: TaskStatus | None = None
    if status is not None:
        try:
            status_filter = TaskStatus(status.lower())
        except ValueError:
            return [{"error": f"Invalid status: {status}. Valid: {[s.value for s in TaskStatus]}"}]

    records = await tm.list_tasks(status=status_filter, limit=min(limit, 100))
    return [_task_to_dict(r) for r in records]
