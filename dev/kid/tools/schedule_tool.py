"""Schedule management tools — add, remove, list, pause, resume (Phase 7).

Provides 5 SYSTEM-category tools for the Scheduler.
Uses module-level Scheduler reference, injected by Router on init.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.categories import ToolCategory
from core.exceptions import InvalidCronExpressionError, ScheduleNotFoundError
from core.models import ScheduleStatus, ScheduleType
from core.policy import ToolPolicy
from core.tool_decorator import tool

if TYPE_CHECKING:
    from core.scheduler import Scheduler

logger = logging.getLogger(__name__)

# Module-level scheduler — set by Router during init
_scheduler: Scheduler | None = None


def set_scheduler(sched: Scheduler) -> None:
    """Inject the Scheduler (called by Router on init)."""
    global _scheduler  # noqa: PLW0603
    _scheduler = sched


def get_scheduler() -> Scheduler | None:
    """Return the module-level Scheduler, or None if not wired."""
    return _scheduler


def _record_to_dict(record) -> dict:
    """Serialise a ScheduleRecord into a JSON-safe dict."""
    return {
        "schedule_id": record.schedule_id,
        "name": record.name,
        "schedule_type": record.schedule_type.value,
        "status": record.status.value,
        "at_time": record.at_time.isoformat() if record.at_time else None,
        "interval_seconds": record.interval_seconds,
        "cron_expression": record.cron_expression,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "last_run_at": record.last_run_at.isoformat() if record.last_run_at else None,
        "next_run_at": record.next_run_at.isoformat() if record.next_run_at else None,
        "run_count": record.run_count,
        "max_runs": record.max_runs,
        "metadata": record.metadata,
    }


@tool(
    name="add_schedule",
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=10.0),
)
async def add_schedule(
    name: str,
    schedule_type: str,
    at_time: str | None = None,
    interval_seconds: float | None = None,
    cron_expression: str | None = None,
    max_runs: int | None = None,
) -> dict:
    """Create a new schedule. One-shot (at), repeating (every), or cron-based.

    Args:
        name: Human-readable label for this schedule.
        schedule_type: One of 'at', 'every', or 'cron'.
        at_time: ISO-8601 datetime for one-shot schedules (e.g. '2026-06-05T14:00:00+08:00').
        interval_seconds: Repeat interval in seconds for 'every' schedules.
        cron_expression: Standard cron expression for 'cron' schedules (e.g. '0 8 * * *').
        max_runs: Max number of runs before auto-completing (unlimited if None).

    Returns:
        dict with 'schedule_id' and 'status'.
    """
    if _scheduler is None:
        return {"error": "Scheduler not available"}

    try:
        st = ScheduleType(schedule_type.lower())
    except ValueError:
        valid = [t.value for t in ScheduleType]
        return {"error": f"Invalid schedule_type '{schedule_type}'. Valid: {valid}"}

    parsed_at: datetime | None = None
    if at_time is not None:
        try:
            parsed_at = datetime.fromisoformat(at_time)
            if parsed_at.tzinfo is None:
                parsed_at = parsed_at.replace(tzinfo=UTC)
        except ValueError as exc:
            return {"error": f"Invalid at_time: {exc}"}

    try:
        sid = await _scheduler.add_schedule(
            name=name,
            schedule_type=st,
            at_time=parsed_at,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            max_runs=max_runs,
        )
    except InvalidCronExpressionError as exc:
        return {"error": str(exc)}
    except ValueError as exc:
        return {"error": str(exc)}

    return {"status": "created", "schedule_id": sid}


@tool(
    name="remove_schedule",
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=5.0),
)
async def remove_schedule(schedule_id: str) -> dict:
    """Remove a schedule by its 12-character id.

    Args:
        schedule_id: 12-character schedule id.
    """
    if _scheduler is None:
        return {"error": "Scheduler not available"}

    try:
        await _scheduler.remove_schedule(schedule_id)
    except ScheduleNotFoundError:
        return {"error": f"Schedule {schedule_id} not found"}

    return {"status": "removed", "schedule_id": schedule_id}


@tool(
    name="list_schedules",
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=5.0),
)
async def list_schedules(status: str | None = None) -> list[dict]:
    """List all schedules, optionally filtered by status.

    Args:
        status: Filter — active, paused, completed, cancelled.
    """
    if _scheduler is None:
        return [{"error": "Scheduler not available"}]

    status_filter: ScheduleStatus | None = None
    if status is not None:
        try:
            status_filter = ScheduleStatus(status.lower())
        except ValueError:
            valid = [s.value for s in ScheduleStatus]
            return [{"error": f"Invalid status '{status}'. Valid: {valid}"}]

    records = await _scheduler.list_schedules(status=status_filter)
    return [_record_to_dict(r) for r in records]


@tool(
    name="pause_schedule",
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=5.0),
)
async def pause_schedule(schedule_id: str) -> dict:
    """Pause an active schedule without removing it.

    Args:
        schedule_id: 12-character schedule id.
    """
    if _scheduler is None:
        return {"error": "Scheduler not available"}

    try:
        await _scheduler.pause_schedule(schedule_id)
    except ScheduleNotFoundError:
        return {"error": f"Schedule {schedule_id} not found"}

    return {"status": "paused", "schedule_id": schedule_id}


@tool(
    name="resume_schedule",
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=5.0),
)
async def resume_schedule(schedule_id: str) -> dict:
    """Resume a paused schedule.

    Args:
        schedule_id: 12-character schedule id.
    """
    if _scheduler is None:
        return {"error": "Scheduler not available"}

    try:
        await _scheduler.resume_schedule(schedule_id)
    except ScheduleNotFoundError:
        return {"error": f"Schedule {schedule_id} not found"}

    return {"status": "resumed", "schedule_id": schedule_id}
