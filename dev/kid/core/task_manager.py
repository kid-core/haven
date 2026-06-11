"""Background task lifecycle manager — spawn, query, cancel, timeout, cleanup.

Phase 6: independent component, not embedded in Router.
In-memory only; persistence deferred to Phase 9.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .exceptions import TaskNotFoundError, TaskTimeoutError
from .models import TaskRecord, TaskStatus
from .paths import ltm_dir

logger = logging.getLogger(__name__)


class TaskManager:
    """Background task lifecycle manager.

    Features:
    - Semaphore-controlled concurrency (max_concurrent).
    - Per-task timeout with automatic TIMED_OUT marking.
    - Graceful shutdown via close() cancels all running tasks.
    - Non-blocking spawn — returns task_id immediately.
    """

    def __init__(
        self,
        max_concurrent: int = 5,
        storage_path: str = str(ltm_dir() / "tasks.json"),
        archive_path: str | None = str(ltm_dir() / "tasks_archive.json"),
        auto_persist: bool = True,
    ) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._futures: dict[str, asyncio.Task[None]] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()
        self._shutdown = False
        self._storage_path = Path(storage_path)
        self._archive_path = Path(archive_path) if archive_path else None
        self._auto_persist = auto_persist
        from .message_bus import MessageBus

        self.message_bus = MessageBus(max_mailbox=100)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    async def spawn(
        self,
        coro: Awaitable[Any],
        *,
        name: str = "",
        timeout: float | None = 300.0,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Launch *coro* as a background task.  Returns the task_id immediately.

        The coroutine is wrapped so that status transitions (PENDING →
        RUNNING → COMPLETED / FAILED / TIMED_OUT / CANCELLED) are tracked
        automatically, and the semaphore is released on exit.
        """
        if self._shutdown:
            raise RuntimeError("TaskManager is shut down — cannot spawn new tasks")

        record = TaskRecord(
            name=name,
            timeout=timeout,
            metadata=metadata or {},
        )
        tid = record.task_id
        event = asyncio.Event()

        async with self._lock:
            self._tasks[tid] = record
            self._events[tid] = event

        async def _wrapper() -> None:
            async with self._semaphore:
                if self._shutdown:
                    async with self._lock:
                        record.status = TaskStatus.CANCELLED
                        record.finished_at = datetime.now(UTC)
                    event.set()
                    return

                async with self._lock:
                    record.status = TaskStatus.RUNNING
                    record.started_at = datetime.now(UTC)

                try:
                    result = await asyncio.wait_for(coro, timeout=timeout)
                    async with self._lock:
                        record.status = TaskStatus.COMPLETED
                        record.result = str(result)[:2000]
                        record.finished_at = datetime.now(UTC)
                except TimeoutError:
                    async with self._lock:
                        record.status = TaskStatus.TIMED_OUT
                        record.error = f"Task timed out after {timeout}s"
                        record.finished_at = datetime.now(UTC)
                except asyncio.CancelledError:
                    async with self._lock:
                        if record.status == TaskStatus.RUNNING:
                            record.status = TaskStatus.CANCELLED
                            record.finished_at = datetime.now(UTC)
                    raise
                except Exception as exc:
                    async with self._lock:
                        record.status = TaskStatus.FAILED
                        record.error = f"{type(exc).__name__}: {exc}"
                        record.finished_at = datetime.now(UTC)
                finally:
                    async with self._lock:
                        self._futures.pop(tid, None)
                    event.set()
                    if self._auto_persist:
                        await self._persist()

        future = asyncio.ensure_future(_wrapper())
        async with self._lock:
            self._futures[tid] = future

        return tid

    async def get_task(self, task_id: str) -> TaskRecord | None:
        """Return the TaskRecord for *task_id*, or None if not found."""
        if len(task_id) != 12:
            return None
        async with self._lock:
            return self._tasks.get(task_id)

    async def list_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 20,
    ) -> list[TaskRecord]:
        """List tasks, optionally filtered by status, ordered by created_at descending."""
        async with self._lock:
            records = list(self._tasks.values())
        if status is not None:
            records = [r for r in records if r.status == status]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel *task_id*.  Returns True if the task was found and cancelled."""
        async with self._lock:
            record = self._tasks.get(task_id)
            future = self._futures.get(task_id)
            if record is None:
                return False
            if record.status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.TIMED_OUT,
            ):
                return False

        # Cancel the underlying asyncio task (CancelledError will be caught in _wrapper)
        if future is not None and not future.done():
            future.cancel()
        return True

    async def wait_for(
        self, task_id: str, timeout: float = 30.0
    ) -> TaskRecord:
        """Block until *task_id* reaches a terminal state. Raises on non-existence or timeout."""
        async with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(f"Task {task_id} not found")
            event = self._events[task_id]

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            raise TaskTimeoutError(
                f"Task {task_id} did not complete within {timeout}s"
            ) from None

        async with self._lock:
            record = self._tasks.get(task_id)
        if record is None:
            raise TaskNotFoundError(f"Task {task_id} disappeared")
        return record

    async def cleanup_old(self, max_age_hours: float = 24) -> int:
        """Remove terminal tasks older than *max_age_hours*. Returns number removed."""
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        removed = 0
        stale_records: list[TaskRecord] = []
        async with self._lock:
            stale_ids: list[str] = []
            for tid, record in self._tasks.items():
                if record.status in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    TaskStatus.TIMED_OUT,
                ):
                    finished = record.finished_at
                    if finished is not None and finished < cutoff:
                        stale_ids.append(tid)
                        stale_records.append(record)
            for tid in stale_ids:
                self._tasks.pop(tid, None)
                self._events.pop(tid, None)
                removed += 1
        # Archive before discarding
        if stale_records and self._archive_path:
            await self._archive(stale_records)
        return removed

    async def close(self) -> None:
        """Graceful shutdown: persist then cancel all running/pending tasks."""
        if self._shutdown:
            return
        self._shutdown = True

        # Persist current state before cancelling
        await self._persist()

        async with self._lock:
            futures = list(self._futures.items())

        for tid, future in futures:
            if not future.done():
                future.cancel()
                logger.debug("TaskManager shutdown: cancelled %s", tid)

        # Wait briefly for cancellations to propagate
        if futures:
            await asyncio.gather(*(f for _, f in futures), return_exceptions=True)

    # ------------------------------------------------------------------
    # Phase 9: Persistence (tasks.json)
    # ------------------------------------------------------------------

    async def _persist(self) -> None:
        """Dump all non-trivial task records to JSON on disk.

        Skips PENDING tasks that have never started (no side effects yet).
        """
        async with self._lock:
            data = []
            for record in self._tasks.values():
                if record.status == TaskStatus.PENDING and record.started_at is None:
                    continue
                entry = record.model_dump(mode="json")
                entry.pop("coroutine_ref", None)
                data.append(entry)
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )

    async def _restore(self) -> dict[str, int]:
        """Load tasks from JSON and rehydrate.

        Terminal tasks (COMPLETED / FAILED / CANCELLED / TIMED_OUT) are
        kept as-is for query purposes.

        Non-terminal tasks (RUNNING / PENDING) cannot be truly resumed
        (asyncio coroutines are not serialisable).  They are marked as
        FAILED with restored_from=True so the caller can detect the
        interruption.
        """
        if not self._storage_path.exists():
            return {"restored": 0, "interrupted": 0}

        try:
            raw = json.loads(self._storage_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to parse %s — starting fresh", self._storage_path)
            return {"restored": 0, "interrupted": 0}

        restored = 0
        interrupted = 0
        async with self._lock:
            for entry in raw:
                try:
                    record = TaskRecord.model_validate(entry)
                except Exception:
                    continue
                tid = record.task_id
                if record.status in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    TaskStatus.TIMED_OUT,
                ):
                    self._tasks[tid] = record
                    restored += 1
                else:
                    # Non-terminal → mark interrupted
                    record.status = TaskStatus.FAILED
                    record.error = "Task interrupted by Haven restart"
                    record.restored_from = True
                    record.finished_at = record.finished_at or datetime.now(UTC)
                    self._tasks[tid] = record
                    restored += 1
                    interrupted += 1

        logger.info(
            "TaskManager restored %d records (%d interrupted)",
            restored,
            interrupted,
        )
        return {"restored": restored, "interrupted": interrupted}

    async def _archive(self, records: list[TaskRecord]) -> None:
        """Append *records* to the archive JSON file.  Caps at 1000 entries."""
        if not self._archive_path:
            return
        existing: list[dict] = []
        if self._archive_path.exists():
            try:
                existing = json.loads(self._archive_path.read_text())
            except (json.JSONDecodeError, OSError):
                existing = []
        for r in records:
            existing.append(r.model_dump(mode="json"))
        if len(existing) > 1000:
            existing = existing[-1000:]
        self._archive_path.parent.mkdir(parents=True, exist_ok=True)
        self._archive_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False)
        )
