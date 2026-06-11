"""Phase 6 tests — TaskManager, background tasks, query/cancel/list."""

from __future__ import annotations

import asyncio

import pytest
from core.models import TaskStatus
from core.task_manager import TaskManager


class TestTaskManager:
    """Unit tests for TaskManager lifecycle — spawn, wait, query, cancel, timeout, concurrency, shutdown."""

    @pytest.mark.asyncio
    async def test_spawn_and_wait(self) -> None:
        """发射背景任务，wait_for 确认 COMPLETED"""
        tm = TaskManager()
        tid = await tm.spawn(asyncio.sleep(0.05), name="quick sleep")
        final = await tm.wait_for(tid, timeout=5.0)
        assert final.status == TaskStatus.COMPLETED
        assert final.name == "quick sleep"
        await tm.close()

    @pytest.mark.asyncio
    async def test_query_task(self) -> None:
        """发射后用 get_task 查询状态"""
        tm = TaskManager()
        tid = await tm.spawn(asyncio.sleep(0.2), name="test task")
        await asyncio.sleep(0.01)  # let the wrapper task acquire the semaphore
        record = await tm.get_task(tid)
        assert record is not None
        assert record.name == "test task"
        assert record.task_id == tid
        assert record.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.COMPLETED)
        await tm.wait_for(tid, timeout=5.0)
        await tm.close()

    @pytest.mark.asyncio
    async def test_list_tasks(self) -> None:
        """列举过滤：全量、按状态"""
        tm = TaskManager()
        ids: list[str] = []
        for i in range(3):
            tid = await tm.spawn(asyncio.sleep(0.05), name=f"task-{i}")
            ids.append(tid)
        for tid in ids:
            await tm.wait_for(tid, timeout=5.0)

        all_tasks = await tm.list_tasks()
        assert len(all_tasks) == 3

        completed = await tm.list_tasks(status=TaskStatus.COMPLETED)
        assert len(completed) == 3

        pending = await tm.list_tasks(status=TaskStatus.PENDING)
        assert len(pending) == 0

        await tm.close()

    @pytest.mark.asyncio
    async def test_cancel_task(self) -> None:
        """取消 RUNNING 中的任务，确认 CANCELLED"""
        tm = TaskManager()
        tid = await tm.spawn(asyncio.sleep(30), name="long task")
        await asyncio.sleep(0.1)  # let it start running
        cancelled = await tm.cancel_task(tid)
        assert cancelled is True

        await asyncio.sleep(0.1)  # let cancellation propagate
        record = await tm.get_task(tid)
        assert record is not None
        assert record.status == TaskStatus.CANCELLED

        await tm.close()

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        """逾时任务自动标记 TIMED_OUT"""
        tm = TaskManager()
        tid = await tm.spawn(asyncio.sleep(10), name="long task", timeout=0.3)
        final = await tm.wait_for(tid, timeout=5.0)
        assert final.status == TaskStatus.TIMED_OUT

        await tm.close()

    @pytest.mark.asyncio
    async def test_concurrent_limit(self) -> None:
        """Semaphore 排队行为：max=2 但 spawn 4 个，后 2 个先 PENDING"""
        tm = TaskManager(max_concurrent=2)
        ids: list[str] = []
        for i in range(4):
            tid = await tm.spawn(asyncio.sleep(0.3), name=f"task-{i}")
            ids.append(tid)

        await asyncio.sleep(0.1)  # let scheduling happen

        records = [await tm.get_task(tid) for tid in ids]
        running = sum(1 for r in records if r is not None and r.status == TaskStatus.RUNNING)
        pending = sum(1 for r in records if r is not None and r.status == TaskStatus.PENDING)
        assert running == 2, f"Expected 2 RUNNING, got {running}"
        assert pending == 2, f"Expected 2 PENDING, got {pending}"

        # Wait for all to finish
        for tid in ids:
            await tm.wait_for(tid, timeout=5.0)

        final_records = [await tm.get_task(tid) for tid in ids]
        assert all(r is not None and r.status == TaskStatus.COMPLETED for r in final_records)

        await tm.close()

    @pytest.mark.asyncio
    async def test_shutdown_cleanup(self) -> None:
        """close() 时 cancel 所有 RUNNING 中任务"""
        tm = TaskManager()
        tid = await tm.spawn(asyncio.sleep(30), name="long task")
        await asyncio.sleep(0.1)  # let it start

        record = await tm.get_task(tid)
        assert record is not None
        assert record.status == TaskStatus.RUNNING

        await tm.close()

        record = await tm.get_task(tid)
        assert record is not None
        assert record.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_failed_task(self) -> None:
        """任务抛出异常时标记 FAILED"""
        tm = TaskManager()

        async def _fail() -> None:
            raise ValueError("boom")

        tid = await tm.spawn(_fail(), name="failing task")
        final = await tm.wait_for(tid, timeout=5.0)
        assert final.status == TaskStatus.FAILED
        assert final.error is not None
        assert "boom" in final.error

        await tm.close()

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self) -> None:
        """查询不存在的 task 回传 None"""
        tm = TaskManager()
        record = await tm.get_task("deadbeef1234")
        assert record is None
        await tm.close()

    @pytest.mark.asyncio
    async def test_wait_for_nonexistent(self) -> None:
        """wait_for 不存在的 task 抛出异常"""
        from core.exceptions import TaskNotFoundError

        tm = TaskManager()
        with pytest.raises(TaskNotFoundError):
            await tm.wait_for("deadbeef1234", timeout=1.0)
        await tm.close()

    @pytest.mark.asyncio
    async def test_cleanup_old(self) -> None:
        """cleanup_old 清理已完成任务"""
        tm = TaskManager()
        tid = await tm.spawn(asyncio.sleep(0.05), name="old task")
        await tm.wait_for(tid, timeout=5.0)

        # Artificially age the record
        from datetime import timedelta

        record = await tm.get_task(tid)
        assert record is not None
        record.finished_at = record.finished_at - timedelta(hours=48)  # type: ignore[operator]

        removed = await tm.cleanup_old(max_age_hours=24)
        assert removed == 1
        assert await tm.get_task(tid) is None

        await tm.close()
