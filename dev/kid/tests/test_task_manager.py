"""
Tests for core/task_manager.py — TaskManager background task lifecycle.

Component tests: uses asyncio to verify spawn, status transitions,
timeout, cancel, concurrency, cleanup, restore, and persistence.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.exceptions import TaskNotFoundError, TaskTimeoutError
from core.models import TaskStatus


@pytest.fixture
def tm(tmp_path: Path) -> TaskManager:
    """TaskManager with temp storage path for isolation."""
    from core.task_manager import TaskManager

    storage = str(tmp_path / "tasks.json")
    archive = str(tmp_path / "tasks_archive.json")
    return TaskManager(
        max_concurrent=5,
        storage_path=storage,
        archive_path=archive,
        auto_persist=False,
    )


async def _short() -> str:
    """A quick coroutine that returns a string."""
    await asyncio.sleep(0.001)
    return "done"


async def _long() -> None:
    """A coroutine that sleeps longer than a timeout."""
    await asyncio.sleep(100)


async def _failing() -> str:
    """A coroutine that always raises."""
    await asyncio.sleep(0.001)
    raise ValueError("Intentional failure")


# ======================================================================
# Lifecycle
# ======================================================================

class TestTaskLifecycle:
    """Task PENDING → RUNNING → COMPLETED/FAILED/TIMED_OUT/CANCELLED."""

    async def test_spawn_returns_id(self, tm):
        tid = await tm.spawn(_short(), name="hello")
        assert len(tid) == 12
        assert isinstance(tid, str)

    async def test_initial_status_pending(self, tm):
        tid = await tm.spawn(_short(), name="pending_check")
        record = await tm.get_task(tid)
        assert record is not None
        assert record.status == TaskStatus.PENDING

    async def test_spawn_and_complete(self, tm):
        tid = await tm.spawn(_short(), name="quick")
        await tm.wait_for(tid, timeout=5)
        record = await tm.get_task(tid)
        assert record is not None
        assert record.status == TaskStatus.COMPLETED

    async def test_task_result_stored(self, tm):
        tid = await tm.spawn(_short(), name="result_check")
        await tm.wait_for(tid, timeout=5)
        record = await tm.get_task(tid)
        assert record is not None
        assert record.result == "done"

    async def test_task_has_start_and_finish_times(self, tm):
        tid = await tm.spawn(_short(), name="timestamps")
        await tm.wait_for(tid, timeout=5)
        record = await tm.get_task(tid)
        assert record is not None
        assert record.started_at is not None
        assert record.finished_at is not None
        assert record.finished_at >= record.started_at

    async def test_failing_task(self, tm):
        tid = await tm.spawn(_failing(), name="fail")
        await tm.wait_for(tid, timeout=5)
        record = await tm.get_task(tid)
        assert record is not None
        assert record.status == TaskStatus.FAILED
        assert "Intentional failure" in (record.error or "")

    async def test_timeout_task(self, tm):
        tid = await tm.spawn(_long(), name="timeout", timeout=0.05)
        await tm.wait_for(tid, timeout=5)
        record = await tm.get_task(tid)
        assert record is not None
        assert record.status == TaskStatus.TIMED_OUT
        assert record.error is not None

    async def test_get_nonexistent_task(self, tm):
        record = await tm.get_task("nonexistent123")
        assert record is None


# ======================================================================
# Cancel
# ======================================================================

class TestTaskCancel:
    """Cancelling tasks mid-flight."""

    async def test_cancel_running_task(self, tm):
        tid = await tm.spawn(_long(), name="cancel_me", timeout=30)
        # Give it a moment to start running
        await asyncio.sleep(0.02)

        cancelled = await tm.cancel_task(tid)
        assert cancelled is True

        try:
            await tm.wait_for(tid, timeout=5)
        except (TaskTimeoutError, asyncio.TimeoutError):
            pass

        record = await tm.get_task(tid)
        assert record is not None
        assert record.status in (TaskStatus.CANCELLED, TaskStatus.TIMED_OUT)

    async def test_cancel_completed_task_returns_false(self, tm):
        tid = await tm.spawn(_short(), name="already_done")
        await tm.wait_for(tid, timeout=5)

        cancelled = await tm.cancel_task(tid)
        assert cancelled is False

    async def test_cancel_nonexistent_task_returns_false(self, tm):
        cancelled = await tm.cancel_task("nonexistent123")
        assert cancelled is False


# ======================================================================
# List / Query
# ======================================================================

class TestTaskQuery:
    """Listing and querying tasks."""

    async def test_list_tasks(self, tm):
        await tm.spawn(_short(), name="a")
        await tm.spawn(_short(), name="b")
        tasks = await tm.list_tasks()
        assert len(tasks) == 2

    async def test_list_tasks_filter_by_status(self, tm):
        tid1 = await tm.spawn(_short(), name="quick")
        tid2 = await tm.spawn(_short(), name="quick2")
        await tm.wait_for(tid1, timeout=5)
        await tm.wait_for(tid2, timeout=5)

        completed = await tm.list_tasks(status=TaskStatus.COMPLETED)
        assert len(completed) >= 2

        pending = await tm.list_tasks(status=TaskStatus.PENDING)
        assert len(pending) == 0

    async def test_list_tasks_limit(self, tm):
        for i in range(5):
            await tm.spawn(_short(), name=f"t{i}")
        tasks = await tm.list_tasks(limit=3)
        assert len(tasks) == 3

    async def test_list_tasks_ordered_by_created_at(self, tm):
        ids = []
        for i in range(3):
            tid = await tm.spawn(_short(), name=f"t{i}")
            ids.append(tid)
            await asyncio.sleep(0.01)

        tasks = await tm.list_tasks()
        assert tasks[0].task_id == ids[2]


# ======================================================================
# Concurrency
# ======================================================================

class TestTaskConcurrency:
    """Semaphore-controlled parallelism."""

    async def test_max_concurrent_respected(self, tm):
        """At most max_concurrent tasks run simultaneously."""
        started = set()
        barrier = asyncio.Event()

        async def wait_at_barrier(idx: int) -> None:
            started.add(idx)
            await barrier.wait()

        # Spawn more tasks than max_concurrent
        for i in range(7):
            await tm.spawn(wait_at_barrier(i), name=f"barrier_{i}", timeout=5)

        await asyncio.sleep(0.1)
        # With max_concurrent=5, at most 5 should have started
        assert len(started) <= 5

        barrier.set()
        await asyncio.sleep(0.1)


# ======================================================================
# Cleanup
# ======================================================================

class TestTaskCleanup:
    """Cleanup of old terminal tasks."""

    async def test_cleanup_old_tasks(self, tm):
        tid = await tm.spawn(_short(), name="old")
        await tm.wait_for(tid, timeout=5)

        # Use a cutoff that's far in the future to trigger cleanup
        removed = await tm.cleanup_old(max_age_hours=0)
        assert removed >= 1

    async def test_cleanup_preserves_recent(self, tm):
        tid = await tm.spawn(_short(), name="recent")
        await tm.wait_for(tid, timeout=5)

        removed = await tm.cleanup_old(max_age_hours=24)
        assert removed == 0

    async def test_cleanup_skips_running(self, tm):
        tid = await tm.spawn(_long(), name="running", timeout=30)
        await asyncio.sleep(0.02)

        removed = await tm.cleanup_old(max_age_hours=0)
        assert removed == 0

        await tm.cancel_task(tid)


# ======================================================================
# Wait for
# ======================================================================

class TestTaskWait:
    """Blocking wait for task completion."""

    async def test_wait_for_completion(self, tm):
        tid = await tm.spawn(_short(), name="wait_test")
        record = await tm.wait_for(tid, timeout=5)
        assert record.status == TaskStatus.COMPLETED

    async def test_wait_for_nonexistent_raises(self, tm):
        with pytest.raises(TaskNotFoundError):
            await tm.wait_for("nonexistent123", timeout=1)


# ======================================================================
# Shutdown
# ======================================================================

class TestTaskShutdown:
    """Graceful shutdown behaviour."""

    async def test_close_cancels_running(self, tm):
        tid = await tm.spawn(_long(), name="doomed", timeout=30)
        await asyncio.sleep(0.02)

        await tm.close()

        record = await tm.get_task(tid)
        assert record is not None
        assert record.status in (TaskStatus.CANCELLED, TaskStatus.TIMED_OUT)

    async def test_spawn_after_close_raises(self, tm):
        await tm.close()
        with pytest.raises(RuntimeError, match="shut down"):
            await tm.spawn(_short())

    async def test_close_idempotent(self, tm):
        await tm.close()
        await tm.close()  # second close should not crash


# ======================================================================
# Validation
# ======================================================================

class TestTaskValidation:
    """Input validation edge cases."""

    async def test_get_task_invalid_id_returns_none(self, tm):
        for bad_id in ["", "short", "too_long_task_id_here"]:
            record = await tm.get_task(bad_id)
            assert record is None
