"""Phase 7 — Independent scheduler with at/every/cron support, persistence, and task triggers.

Design:
- Wraps a TaskManager for spawning callbacks as background tasks.
- asyncio.Lock guards the internal schedule dict.
- _watcher coroutine polls active schedules every cycle, dispatches due ones.
- croniter for cron-expression support.
- Persists to a JSON file for restore across restarts.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from croniter import croniter

from .exceptions import InvalidCronExpressionError, ScheduleNotFoundError
from .models import ScheduleRecord, ScheduleStatus, ScheduleType
from .paths import ltm_dir
from .task_manager import TaskManager

logger = logging.getLogger(__name__)

WATCHER_INTERVAL = 1.0  # seconds between scanning for due schedules
Callback = Callable[[], Awaitable[Any] | Any]
NotifyCallback = Callable[[str, dict], Awaitable[None]]


class Scheduler:
    """Independent schedule orchestrator.

    Public API: start / close / add_schedule / remove_schedule / get_schedule /
    list_schedules / pause_schedule / resume_schedule.
    """

    def __init__(
        self,
        task_manager: TaskManager,
        storage_path: str = str(ltm_dir() / "schedules.json"),
        watcher_interval: float = WATCHER_INTERVAL,
    ) -> None:
        self._tm = task_manager
        self._storage_path = Path(storage_path)
        self._watcher_interval = watcher_interval
        self._schedules: dict[str, ScheduleRecord] = {}
        self._callbacks: dict[str, Callback] = {}
        self._lock = asyncio.Lock()
        self._watcher_task: asyncio.Task[None] | None = None
        self._shutdown = False
        self._notify_handler: NotifyCallback | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Restore persisted schedules and start the watcher loop."""
        await self._restore()
        self._shutdown = False
        self._watcher_task = asyncio.ensure_future(self._watcher())

    async def close(self) -> None:
        """Graceful shutdown: cancel watcher, persist state."""
        if self._shutdown:
            return
        self._shutdown = True
        if self._watcher_task is not None and not self._watcher_task.done():
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task
        await self._persist()

    # ── Notification handler (global fallback) ─────────────────────────

    def set_notify_handler(self, handler: NotifyCallback | None) -> None:
        """Set a global notification handler for schedules without callbacks.

        Called by Router after transports are wired.
        The handler receives ``(name, metadata)``.
        """
        self._notify_handler = handler

    # ── Schedule management ────────────────────────────────────────────

    async def add_schedule(
        self,
        *,
        name: str,
        schedule_type: ScheduleType,
        at_time: datetime | None = None,
        interval_seconds: float | None = None,
        cron_expression: str | None = None,
        max_runs: int | None = None,
        callback: Callback | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Add a new schedule.  Returns the schedule_id."""
        record = ScheduleRecord(
            name=name,
            schedule_type=schedule_type,
            at_time=at_time,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            max_runs=max_runs,
            metadata=metadata or {},
        )
        now = datetime.now(UTC)

        # Compute initial next_run_at
        if schedule_type == ScheduleType.AT:
            if at_time is None:
                raise ValueError("ScheduleType.AT requires at_time")
            record.next_run_at = at_time
            if at_time <= now:
                record.status = ScheduleStatus.COMPLETED
        elif schedule_type == ScheduleType.EVERY:
            if interval_seconds is None or interval_seconds <= 0:
                raise ValueError("ScheduleType.EVERY requires positive interval_seconds")
            record.next_run_at = now + timedelta(seconds=interval_seconds)
        elif schedule_type == ScheduleType.CRON:
            if cron_expression is None:
                raise ValueError("ScheduleType.CRON requires cron_expression")
            record.next_run_at = self._compute_next_run(cron_expression, base=now)

        async with self._lock:
            self._schedules[record.schedule_id] = record
            if callback is not None:
                self._callbacks[record.schedule_id] = callback

        await self._persist()
        logger.info("Schedule added: %s (type=%s)", record.schedule_id, schedule_type.value)
        return record.schedule_id

    async def remove_schedule(self, schedule_id: str) -> None:
        """Remove a schedule by id.  Raises ScheduleNotFoundError if missing."""
        async with self._lock:
            if schedule_id not in self._schedules:
                raise ScheduleNotFoundError(f"Schedule {schedule_id} not found")
            record = self._schedules.pop(schedule_id)
            self._callbacks.pop(schedule_id, None)
            record.status = ScheduleStatus.CANCELLED
        await self._persist()

    async def get_schedule(self, schedule_id: str) -> ScheduleRecord | None:
        """Return the ScheduleRecord for *schedule_id*, or None."""
        if len(schedule_id) != 12:
            return None
        async with self._lock:
            return self._schedules.get(schedule_id)

    async def list_schedules(
        self,
        status: ScheduleStatus | None = None,
    ) -> list[ScheduleRecord]:
        """Return all schedules, optionally filtered by status."""
        async with self._lock:
            records = list(self._schedules.values())
        if status is not None:
            records = [r for r in records if r.status == status]
        return records

    async def pause_schedule(self, schedule_id: str) -> None:
        """Pause an active schedule.  Raises ScheduleNotFoundError if missing."""
        async with self._lock:
            if schedule_id not in self._schedules:
                raise ScheduleNotFoundError(f"Schedule {schedule_id} not found")
            record = self._schedules[schedule_id]
            if record.status != ScheduleStatus.ACTIVE:
                return
            record.status = ScheduleStatus.PAUSED
        await self._persist()

    async def resume_schedule(self, schedule_id: str) -> None:
        """Resume a paused schedule.  Raises ScheduleNotFoundError if missing."""
        async with self._lock:
            if schedule_id not in self._schedules:
                raise ScheduleNotFoundError(f"Schedule {schedule_id} not found")
            record = self._schedules[schedule_id]
            if record.status != ScheduleStatus.PAUSED:
                return
            record.status = ScheduleStatus.ACTIVE
            # Recompute next_run_at from now
            if record.schedule_type == ScheduleType.EVERY and record.interval_seconds:
                record.next_run_at = datetime.now(UTC) + timedelta(seconds=record.interval_seconds)
            elif record.schedule_type == ScheduleType.CRON and record.cron_expression:
                record.next_run_at = self._compute_next_run(record.cron_expression)
        await self._persist()

    # ── Cron computation ───────────────────────────────────────────────

    def _compute_next_run(
        self, expr: str, base: datetime | None = None
    ) -> datetime:
        """Return the next datetime matching *expr* after *base* (default now(UTC))."""
        try:
            cron = croniter(expr, base or datetime.now(UTC))
            return cron.get_next(datetime)
        except (ValueError, KeyError) as e:
            raise InvalidCronExpressionError(
                f"Invalid cron expression: {expr!r}"
            ) from e

    # ── Watcher loop ───────────────────────────────────────────────────

    async def _watcher(self) -> None:
        """Poll active schedules and dispatch due ones."""
        while not self._shutdown:
            try:
                await self._tick()
            except Exception:
                logger.exception("Scheduler watcher error")
            await asyncio.sleep(self._watcher_interval)

    async def _tick(self) -> None:
        """Single watcher tick — check all ACTIVE schedules for dispatch."""
        now = datetime.now(UTC)
        due: list[ScheduleRecord] = []

        async with self._lock:
            for record in self._schedules.values():
                if record.status != ScheduleStatus.ACTIVE:
                    continue
                if record.next_run_at is not None and record.next_run_at <= now:
                    due.append(record)

        for record in due:
            await self._dispatch(record)

    async def _dispatch(self, record: ScheduleRecord) -> None:
        """Execute one due schedule — spawn callback, advance timing, mark terminal."""
        now = datetime.now(UTC)

        async with self._lock:
            # Re-check under lock — could have been removed/paused while we waited
            current = self._schedules.get(record.schedule_id)
            if current is None or current.status != ScheduleStatus.ACTIVE:
                return
            current.last_run_at = now
            current.run_count += 1

        # 1) Per-schedule explicit callback
        callback = self._callbacks.get(record.schedule_id)
        if callback is not None:
            try:
                await self._tm.spawn(
                    _run_callback(callback),
                    name=f"schedule:{record.name}",
                    metadata={"schedule_id": record.schedule_id},
                )
            except Exception:
                logger.exception("Failed to spawn callback for schedule %s", record.schedule_id)

        # 2) Global notification callback (e.g. Discord DM)
        if self._notify_handler is not None:
            try:
                await self._notify_handler(record.name, dict(record.metadata))
            except Exception:
                logger.exception("Notify handler failed for schedule %s", record.schedule_id)

        # Advance timing or mark completed
        async with self._lock:
            current = self._schedules.get(record.schedule_id)
            if current is None:
                return

            if current.max_runs is not None and current.run_count >= current.max_runs:
                current.status = ScheduleStatus.COMPLETED
                logger.info("Schedule %s completed (max_runs=%d)", current.schedule_id, current.max_runs)
            elif current.schedule_type == ScheduleType.AT:
                current.status = ScheduleStatus.COMPLETED
            elif current.schedule_type == ScheduleType.EVERY and current.interval_seconds:
                current.next_run_at = now + timedelta(seconds=current.interval_seconds)
            elif current.schedule_type == ScheduleType.CRON and current.cron_expression:
                current.next_run_at = self._compute_next_run(current.cron_expression, base=now)

        await self._persist()

    # ── Persistence ────────────────────────────────────────────────────

    async def _persist(self) -> None:
        """Dump all schedules to JSON on disk."""
        async with self._lock:
            data = []
            for record in self._schedules.values():
                entry = record.model_dump(mode="json")
                data.append(entry)
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    async def _restore(self) -> None:
        """Load schedules from JSON and rehydrate into memory.

        ScheduleRecords with terminal status are skipped so they don't re-fire.
        """
        if not self._storage_path.exists():
            return
        try:
            raw = json.loads(self._storage_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to parse schedules.json — starting fresh")
            return

        now = datetime.now(UTC)
        restored = 0
        async with self._lock:
            for entry in raw:
                record = ScheduleRecord.model_validate(entry)
                if record.status in (ScheduleStatus.COMPLETED, ScheduleStatus.CANCELLED):
                    continue
                # Recompute next_run_at for intervals / cron to avoid stale timestamps
                if record.status == ScheduleStatus.PAUSED:
                    pass  # keep as-is, user must resume manually
                elif record.schedule_type == ScheduleType.EVERY and record.interval_seconds:
                    if record.next_run_at is None or record.next_run_at < now:
                        record.next_run_at = now + timedelta(seconds=record.interval_seconds)
                elif record.schedule_type == ScheduleType.CRON and record.cron_expression:
                    record.next_run_at = self._compute_next_run(record.cron_expression, base=now)
                self._schedules[record.schedule_id] = record
                restored += 1
        logger.info("Scheduler restored %d schedules from %s", restored, self._storage_path)


async def _run_callback(callback: Callback) -> Any:
    """Helper that awaits a callback if it's a coroutine, else calls it synchronously."""
    result = callback()
    if inspect.isawaitable(result):
        return await result
    return result
