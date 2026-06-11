"""Phase 7 tests — Scheduler: at/every/cron schedules, pause/resume, persist, task triggers."""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import UTC, datetime, timedelta

import pytest
from core.exceptions import InvalidCronExpressionError, ScheduleNotFoundError
from core.models import ScheduleStatus, ScheduleType
from core.scheduler import Scheduler
from core.task_manager import TaskManager


def _rm_safe(path: str) -> None:
    """Remove *path* if it exists."""
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)


class TestScheduler:
    """Unit tests for the Scheduler lifecycle — at, every, cron, pause, resume, persist, task triggers."""

    @pytest.fixture(autouse=True)
    def _cleanup_persist(self) -> None:
        """Remove schedules.json between tests."""
        yield
        _rm_safe("/tmp/test_schedules.json")

    # ── at schedule ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_at_schedule(self) -> None:
        """一次性排程（0.1 秒后），wait_for 确认 COMPLETED"""
        tm = TaskManager()
        sched = Scheduler(task_manager=tm, storage_path="/tmp/test_schedules.json", watcher_interval=0.05)
        await sched.start()

        called = []

        async def _callback() -> None:
            called.append(1)

        sid = await sched.add_schedule(
            name="one-shot",
            schedule_type=ScheduleType.AT,
            at_time=datetime.now(UTC) + timedelta(seconds=0.1),
            callback=_callback,
        )
        await asyncio.sleep(0.3)

        record = await sched.get_schedule(sid)
        assert record is not None
        assert record.status == ScheduleStatus.COMPLETED
        assert len(called) == 1

        await sched.close()
        await tm.close()

    # ── every schedule ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_every_schedule(self) -> None:
        """间隔排程每 0.1 秒，跑 2 次后移除，确认 run_count=2"""
        tm = TaskManager()
        sched = Scheduler(task_manager=tm, storage_path="/tmp/test_schedules.json", watcher_interval=0.05)
        await sched.start()

        run_count = 0

        async def _callback() -> None:
            nonlocal run_count
            run_count += 1

        sid = await sched.add_schedule(
            name="every-test",
            schedule_type=ScheduleType.EVERY,
            interval_seconds=0.1,
            callback=_callback,
        )
        await asyncio.sleep(0.35)

        record_before = await sched.get_schedule(sid)
        assert record_before is not None
        stable = run_count

        await sched.remove_schedule(sid)
        assert stable >= 2, f"Expected at least 2 runs, got {stable}"

        record_after = await sched.get_schedule(sid)
        assert record_after is None

        await sched.close()
        await tm.close()

    # ── pause / resume ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pause_resume(self) -> None:
        """暂停后 run_count 不增加，恢复后继续"""
        tm = TaskManager()
        sched = Scheduler(task_manager=tm, storage_path="/tmp/test_schedules.json", watcher_interval=0.05)
        await sched.start()

        run_count = 0

        async def _callback() -> None:
            nonlocal run_count
            run_count += 1

        sid = await sched.add_schedule(
            name="pause-test",
            schedule_type=ScheduleType.EVERY,
            interval_seconds=0.1,
            callback=_callback,
        )
        await asyncio.sleep(0.25)
        assert run_count >= 2, f"Expected >=2 before pause, got {run_count}"

        await sched.pause_schedule(sid)
        pre_pause = run_count
        await asyncio.sleep(0.25)
        assert run_count == pre_pause, "Should not increment while paused"

        await sched.resume_schedule(sid)
        await asyncio.sleep(0.25)
        assert run_count > pre_pause, "Should increment after resume"

        await sched.remove_schedule(sid)
        await sched.close()
        await tm.close()

    # ── persist / restore ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_persist_restore(self) -> None:
        """存储 schedules.json → 新建 Scheduler 载入 → 确认记录存在"""
        path = "/tmp/test_schedules.json"

        # First scheduler
        tm1 = TaskManager()
        sched1 = Scheduler(task_manager=tm1, storage_path=path)
        await sched1.start()

        sid = await sched1.add_schedule(
            name="persist-test",
            schedule_type=ScheduleType.AT,
            at_time=datetime.now(UTC) + timedelta(weeks=52),
        )
        await sched1._persist()
        await sched1.close()
        await tm1.close()

        # Second scheduler — should restore
        tm2 = TaskManager()
        sched2 = Scheduler(task_manager=tm2, storage_path=path)
        await sched2.start()

        record = await sched2.get_schedule(sid)
        assert record is not None
        assert record.name == "persist-test"
        assert record.schedule_type == ScheduleType.AT
        assert record.status == ScheduleStatus.ACTIVE

        await sched2.close()
        await tm2.close()

    # ── cron schedule ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_cron_schedule(self) -> None:
        """使用 croniter 解析 cron 表达式，确认 next_run_at 正确"""
        tm = TaskManager()
        sched = Scheduler(task_manager=tm, storage_path="/tmp/test_schedules.json")

        # Use a specific base time for deterministic testing
        base = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)
        next_run = sched._compute_next_run("* * * * *", base=base)
        assert next_run is not None
        # Every-minute cron from 12:00 should fire at 12:01
        assert next_run == datetime(2026, 6, 4, 12, 1, 0, 0, tzinfo=UTC), (
            f"Expected 12:01:00, got {next_run}"
        )

        # Daily at 8 AM: "0 8 * * *"
        next_daily = sched._compute_next_run("0 8 * * *", base=base)
        # Base is 12:00 noon on June 4, so next 8 AM is June 5
        assert next_daily == datetime(2026, 6, 5, 8, 0, 0, 0, tzinfo=UTC), (
            f"Expected 2026-06-05 08:00:00, got {next_daily}"
        )

        await sched.close()
        await tm.close()

    # ── invalid cron ───────────────────────────────────────────────

    def test_invalid_cron(self) -> None:
        """无效表达式抛出 InvalidCronExpressionError"""
        sched = Scheduler(
            task_manager=TaskManager(),
            storage_path="/tmp/test_schedules.json",
        )
        with pytest.raises(InvalidCronExpressionError):
            sched._compute_next_run("not a cron expression")

    # ── remove schedule ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_remove_schedule(self) -> None:
        """移除后 list 不再包含"""
        tm = TaskManager()
        sched = Scheduler(task_manager=tm, storage_path="/tmp/test_schedules.json")
        await sched.start()

        sid = await sched.add_schedule(
            name="to-remove",
            schedule_type=ScheduleType.EVERY,
            interval_seconds=999,
        )
        schedules = await sched.list_schedules()
        assert any(s.schedule_id == sid for s in schedules)

        await sched.remove_schedule(sid)
        schedules = await sched.list_schedules()
        assert not any(s.schedule_id == sid for s in schedules)

        # Removing non-existent schedule should raise
        with pytest.raises(ScheduleNotFoundError):
            await sched.remove_schedule("nonexistent-id")

        await sched.close()
        await tm.close()

    # ── schedule triggers task ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_schedule_triggers_task(self) -> None:
        """排程触发后通过 TaskManager.spawn() 执行，确认 task 完成"""
        tm = TaskManager()
        sched = Scheduler(task_manager=tm, storage_path="/tmp/test_schedules.json", watcher_interval=0.05)
        await sched.start()

        sid = await sched.add_schedule(
            name="task-trigger",
            schedule_type=ScheduleType.AT,
            at_time=datetime.now(UTC) + timedelta(seconds=0.1),
            callback=lambda: asyncio.sleep(0.05),  # spawned via tm.spawn
        )
        await asyncio.sleep(0.3)

        record = await sched.get_schedule(sid)
        assert record is not None
        assert record.status == ScheduleStatus.COMPLETED
        assert record.run_count == 1

        # Verify the task was actually spawned
        tasks = await tm.list_tasks()
        assert len(tasks) >= 1, f"Expected at least 1 spawned task, got {len(tasks)}"

        await sched.close()
        await tm.close()

    # ── max_runs ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_max_runs_limits_execution(self) -> None:
        """max_runs 限制排程執行次數，達到後自動 COMPLETED"""
        tm = TaskManager()
        sched = Scheduler(
            task_manager=tm,
            storage_path="/tmp/test_schedules.json",
            watcher_interval=0.05,
        )
        await sched.start()

        run_count = 0

        async def _cb() -> None:
            nonlocal run_count
            run_count += 1

        sid = await sched.add_schedule(
            name="max-run",
            schedule_type=ScheduleType.EVERY,
            interval_seconds=0.05,
            max_runs=3,
            callback=_cb,
        )
        await asyncio.sleep(0.4)

        # Should have run at most 3 times
        record = await sched.get_schedule(sid)
        assert record is not None
        assert record.run_count <= 3
        assert record.status == ScheduleStatus.COMPLETED

        await sched.close()
        await tm.close()

    # ── list_schedules filtering ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_list_schedules(self) -> None:
        """list_schedules 回傳所有排程"""
        tm = TaskManager()
        sched = Scheduler(task_manager=tm, storage_path="/tmp/test_schedules.json")
        await sched.start()

        s1 = await sched.add_schedule(name="a", schedule_type=ScheduleType.EVERY, interval_seconds=999)
        s2 = await sched.add_schedule(name="b", schedule_type=ScheduleType.EVERY, interval_seconds=999)

        all_s = await sched.list_schedules()
        assert len(all_s) == 2
        ids = {s.schedule_id for s in all_s}
        assert s1 in ids
        assert s2 in ids

        await sched.close()
        await tm.close()

    # ── get_schedule returns None for unknown ───────────────────────

    @pytest.mark.asyncio
    async def test_get_unknown_schedule(self) -> None:
        """get_schedule on unknown id returns None"""
        tm = TaskManager()
        sched = Scheduler(task_manager=tm, storage_path="/tmp/test_schedules.json")
        record = await sched.get_schedule("nonexistent")
        assert record is None
        await sched.close()
        await tm.close()
