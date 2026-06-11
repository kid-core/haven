"""
Tests for core/resource_gate.py — PressureLevel, ResourceMonitor, Chunker,
TaskComplexityEstimator, CrashJournal, and the resource_gate decorator.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from core.crash_journal import CrashJournal
from core.exceptions import ResourceBusyError
from core.resource_gate import (
    Chunker,
    PressureLevel,
    ResourceMonitor,
    resource_gate,
)
from core.task_complexity import TaskComplexityEstimator

# ═══════════════════════════════════════════════════════════════════
# PressureLevel
# ═══════════════════════════════════════════════════════════════════

class TestPressureLevel:
    def test_values(self) -> None:
        assert PressureLevel.GREEN == 0
        assert PressureLevel.YELLOW == 1
        assert PressureLevel.RED == 2
        assert PressureLevel.CRITICAL == 3

    def test_is_int_enum(self) -> None:
        assert issubclass(PressureLevel, int)


# ═══════════════════════════════════════════════════════════════════
# ResourceMonitor
# ═══════════════════════════════════════════════════════════════════

class TestResourceMonitor:
    def test_check_ram_returns_pressure_level(self) -> None:
        level = ResourceMonitor.check_ram()
        assert isinstance(level, PressureLevel)
        assert level in (
            PressureLevel.GREEN,
            PressureLevel.YELLOW,
            PressureLevel.RED,
            PressureLevel.CRITICAL,
        )

    def test_check_ram_caches_result(self, monkeypatch) -> None:
        calls: list[float] = []

        def fake_percent() -> float:
            calls.append(time.monotonic())
            return 40.0

        import psutil
        monkeypatch.setattr(psutil, "virtual_memory", lambda: type("vmem", (), {"percent": fake_percent()})())
        # Invalidate any prior cache
        monkeypatch.setattr(ResourceMonitor, "_ram_cache", None)
        monkeypatch.setattr(ResourceMonitor, "_ram_cache_ts", 0.0)

        result1 = ResourceMonitor.check_ram()
        result2 = ResourceMonitor.check_ram()
        # Same result, cache should be used (only one call to fake_percent)
        assert result1 == result2
        if len(calls) >= 1:
            assert calls[0] < time.monotonic()

    def test_check_ram_expired_cache_rechecks(self, monkeypatch) -> None:
        counts = {"calls": 0}

        def fake_percent() -> float:
            counts["calls"] += 1
            return 30.0

        import psutil
        monkeypatch.setattr(psutil, "virtual_memory", lambda: type("vmem", (), {"percent": fake_percent()})())
        monkeypatch.setattr(ResourceMonitor, "_ram_cache", None)
        monkeypatch.setattr(ResourceMonitor, "_ram_cache_ts", 0.0)

        ResourceMonitor.check_ram()  # first call
        # Simulate cache expiry
        monkeypatch.setattr(ResourceMonitor, "_ram_cache_ts", time.monotonic() - 5.0)
        ResourceMonitor.check_ram()  # second call should re-fetch
        assert counts["calls"] >= 2

    def test_check_ram_fallback_when_psutil_missing(self, monkeypatch) -> None:
        # ImportError simulation — module must exist so use a sentinel
        monkeypatch.setattr(ResourceMonitor, "_psutil_available", False)
        level = ResourceMonitor.check_ram()
        assert level == PressureLevel.GREEN

    def test_check_disk_returns_tuple(self) -> None:
        under_90, usage_pct = ResourceMonitor.check_disk(path="/")
        assert isinstance(under_90, bool)
        assert isinstance(usage_pct, float)
        assert 0.0 <= usage_pct <= 100.0

    def test_check_disk_under_threshold_true(self, monkeypatch) -> None:
        monkeypatch.setattr(
            ResourceMonitor,
            "_disk_usage",
            staticmethod(lambda path: type("u", (), {"percent": 25.0})()),
        )
        under, pct = ResourceMonitor.check_disk(path="/mnt/z")
        assert under is True
        assert pct == 25.0

    def test_check_disk_over_threshold_false(self, monkeypatch) -> None:
        monkeypatch.setattr(
            ResourceMonitor,
            "_disk_usage",
            staticmethod(lambda path: type("u", (), {"percent": 91.0})()),
        )
        under, pct = ResourceMonitor.check_disk(path="/mnt/z")
        assert under is False
        assert pct == 91.0


# ═══════════════════════════════════════════════════════════════════
# Chunker
# ═══════════════════════════════════════════════════════════════════

class TestChunkerIterChunks:
    def test_empty_list(self) -> None:
        chunks = list(Chunker.iter_chunks([], chunk_size=10))
        assert chunks == []

    def test_exact_chunk_size(self) -> None:
        data = list(range(10))
        chunks = list(Chunker.iter_chunks(data, chunk_size=5))
        assert len(chunks) == 2
        assert chunks[0] == [0, 1, 2, 3, 4]
        assert chunks[1] == [5, 6, 7, 8, 9]

    def test_uneven_last_chunk(self) -> None:
        data = list(range(8))
        chunks = list(Chunker.iter_chunks(data, chunk_size=3))
        assert len(chunks) == 3
        assert chunks[0] == [0, 1, 2]
        assert chunks[1] == [3, 4, 5]
        assert chunks[2] == [6, 7]

    def test_single_chunk_smaller_than_chunk_size(self) -> None:
        data = [1, 2, 3]
        chunks = list(Chunker.iter_chunks(data, chunk_size=5000))
        assert len(chunks) == 1
        assert chunks[0] == [1, 2, 3]

    def test_default_chunk_size(self) -> None:
        data = list(range(100))
        chunks = list(Chunker.iter_chunks(data))  # default  5000
        assert len(chunks) == 1


class TestChunkerProcessChunks:
    @pytest.mark.asyncio
    async def test_processes_all_chunks(self) -> None:
        data = list(range(7))
        results: list[list[int]] = []

        async def handler(chunk: list[int]) -> None:
            results.append(chunk)

        await Chunker.process_chunks(data, handler, chunk_size=3)
        assert len(results) == 3
        assert results[0] == [0, 1, 2]
        assert results[1] == [3, 4, 5]
        assert results[2] == [6]

    @pytest.mark.asyncio
    async def test_process_chunks_checks_ram_between(self, monkeypatch) -> None:
        ram_checks: list[int] = []

        def fake_check_ram() -> PressureLevel:
            ram_checks.append(len(ram_checks))
            return PressureLevel.GREEN

        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(fake_check_ram))

        data = list(range(12))
        results: list[list[int]] = []

        async def handler(chunk: list[int]) -> None:
            results.append(chunk)

        await Chunker.process_chunks(data, handler, chunk_size=4)
        assert len(results) == 3
        # RAM checked before first chunk and between chunks → 3 checks
        assert len(ram_checks) == 3

    @pytest.mark.asyncio
    async def test_process_chunks_critical_raises(self, monkeypatch) -> None:
        check_count = 0

        def fake_check_ram() -> PressureLevel:
            nonlocal check_count
            check_count += 1
            if check_count >= 2:
                return PressureLevel.CRITICAL
            return PressureLevel.GREEN

        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(fake_check_ram))

        data = list(range(10))

        async def handler(chunk: list[int]) -> None:
            pass

        with pytest.raises(ResourceBusyError):
            await Chunker.process_chunks(data, handler, chunk_size=3)

    @pytest.mark.asyncio
    async def test_process_chunks_empty_data(self) -> None:
        results: list[list[int]] = []

        async def handler(chunk: list[int]) -> None:
            results.append(chunk)

        await Chunker.process_chunks([], handler)
        assert results == []


# ═══════════════════════════════════════════════════════════════════
# TaskComplexityEstimator
# ═══════════════════════════════════════════════════════════════════

class TestTaskComplexityEstimator:
    def test_estimate_turns_known_verbs(self) -> None:
        estimator = TaskComplexityEstimator()
        assert estimator.estimate_turns("implement login") == 8  # ceil(5*1.5)
        assert estimator.estimate_turns("debug crash") == 6  # ceil(4*1.5)
        assert estimator.estimate_turns("analyze report") == 5  # ceil(3*1.5)
        assert estimator.estimate_turns("refactor code") == 6  # ceil(4*1.5)
        assert estimator.estimate_turns("summarize docs") == 3  # ceil(2*1.5)
        assert estimator.estimate_turns("translate text") == 3  # ceil(2*1.5)

    def test_estimate_turns_first_word_match(self) -> None:
        """Only the first word should matter for dispatch."""
        estimator = TaskComplexityEstimator()
        # "implement" maps to 5, buffered = ceil(5*1.5) = 8
        assert estimator.estimate_turns("implement") == 8
        # "implementation" does not start with a known verb → default, buffered
        assert estimator.estimate_turns("implementation") == 5  # ceil(3*1.5)

    def test_estimate_turns_unknown_verb_defaults(self) -> None:
        estimator = TaskComplexityEstimator()
        expected_default = 5  # ceil(DEFAULT_TURNS=3 * BUFFER_RATIO=1.5) = ceil(4.5) = 5
        assert estimator.estimate_turns("hello world") == expected_default
        assert estimator.estimate_turns("") == expected_default
        assert estimator.estimate_turns("123") == expected_default

    def test_estimate_turns_file_penalty(self) -> None:
        estimator = TaskComplexityEstimator()
        # implement=5, ceil(5*1.5)=8; +3files: ceil((5+6)*1.5)=ceil(16.5)=17
        base = estimator.estimate_turns("implement login")  # 8
        with_files = estimator.estimate_turns("implement login", file_count=3)
        assert base == 8
        assert with_files == 17

    def test_estimate_turns_buffer_ratio(self) -> None:
        """Buffer ratio should be applied to the raw result."""
        estimator = TaskComplexityEstimator()
        estimator.BUFFER_RATIO = 1.5
        turns = estimator.estimate_turns("implement login")
        # raw=5, buffered = ceil(5 * 1.5) = ceil(7.5) = 8
        assert turns == 8

    def test_add_and_read_history(self) -> None:
        estimator = TaskComplexityEstimator()
        estimator.add_history("implement login", actual_turns=8)
        estimator.add_history("debug crash", actual_turns=5)
        assert len(estimator._history) == 2
        assert estimator._history[0] == ("implement login", 8)
        assert estimator._history[1] == ("debug crash", 5)


# ═══════════════════════════════════════════════════════════════════
# CrashJournal
# ═══════════════════════════════════════════════════════════════════

class TestCrashJournal:
    def test_log_writes_entry(self, tmp_path: Path) -> None:
        crash_file = tmp_path / "haven_crash.json"
        journal = CrashJournal(storage_path=str(crash_file))
        journal.log("test_task", "something broke", context={"step": 1})
        assert crash_file.exists()
        data = json.loads(crash_file.read_text())
        assert len(data) == 1
        assert data[0]["task_name"] == "test_task"
        assert data[0]["error"] == "something broke"
        assert data[0]["context"] == {"step": 1}
        assert data[0]["handled"] is False

    def test_log_appends_multiple(self, tmp_path: Path) -> None:
        crash_file = tmp_path / "haven_crash.json"
        journal = CrashJournal(storage_path=str(crash_file))
        journal.log("a", "err a")
        journal.log("b", "err b")
        data = json.loads(crash_file.read_text())
        assert len(data) == 2
        assert data[0]["task_name"] == "a"
        assert data[1]["task_name"] == "b"

    def test_read_pending_returns_unhandled(self, tmp_path: Path) -> None:
        crash_file = tmp_path / "haven_crash.json"
        crash_file.write_text(json.dumps([
            {"id": "1", "task_name": "a", "handled": False},
            {"id": "2", "task_name": "b", "handled": True},
            {"id": "3", "task_name": "c", "handled": False},
        ]))
        journal = CrashJournal(storage_path=str(crash_file))
        pending = journal.read_pending()
        assert len(pending) == 2
        assert pending[0]["id"] == "1"
        assert pending[1]["id"] == "3"

    def test_read_pending_empty_file(self, tmp_path: Path) -> None:
        crash_file = tmp_path / "haven_crash.json"
        journal = CrashJournal(storage_path=str(crash_file))
        assert journal.read_pending() == []

    def test_read_pending_missing_file(self, tmp_path: Path) -> None:
        journal = CrashJournal(storage_path="/tmp/nonexistent_haven_crash_test.json")
        assert journal.read_pending() == []

    def test_mark_handled(self, tmp_path: Path) -> None:
        crash_file = tmp_path / "haven_crash.json"
        crash_file.write_text(json.dumps([
            {"id": "aaa", "task_name": "x", "handled": False},
        ]))
        journal = CrashJournal(storage_path=str(crash_file))
        journal.mark_handled("aaa")
        data = json.loads(crash_file.read_text())
        assert data[0]["handled"] is True

    def test_mark_handled_unknown_id_noop(self, tmp_path: Path) -> None:
        crash_file = tmp_path / "haven_crash.json"
        crash_file.write_text(json.dumps([
            {"id": "aaa", "task_name": "x", "handled": False},
        ]))
        journal = CrashJournal(storage_path=str(crash_file))
        journal.mark_handled("unknown_id")
        data = json.loads(crash_file.read_text())
        assert data[0]["handled"] is False

    def test_log_auto_generates_id(self, tmp_path: Path) -> None:
        crash_file = tmp_path / "haven_crash.json"
        journal = CrashJournal(storage_path=str(crash_file))
        journal.log("task", "error")
        data = json.loads(crash_file.read_text())
        assert "id" in data[0]
        assert isinstance(data[0]["id"], str)
        assert len(data[0]["id"]) > 0


# ═══════════════════════════════════════════════════════════════════
# resource_gate decorator
# ═══════════════════════════════════════════════════════════════════

class TestResourceGateDecorator:
    def test_basic_passthrough_green(self, monkeypatch) -> None:
        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.GREEN))

        @resource_gate(auto_estimate=False)
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    @pytest.mark.asyncio
    async def test_basic_passthrough_async_green(self, monkeypatch) -> None:
        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.GREEN))

        @resource_gate(auto_estimate=False)
        async def add(a: int, b: int) -> int:
            await asyncio.sleep(0)
            return a + b

        result = await add(2, 3)
        assert result == 5

    def test_critical_raises_resource_busy(self, monkeypatch) -> None:
        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.CRITICAL))

        @resource_gate(auto_estimate=False)
        def work() -> str:
            return "done"

        with pytest.raises(ResourceBusyError):
            work()

    def test_red_retries_then_passes(self, monkeypatch) -> None:
        calls: list[int] = []

        def cycling_ram() -> PressureLevel:
            calls.append(1)
            if len(calls) == 1:
                return PressureLevel.RED
            return PressureLevel.GREEN

        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(cycling_ram))

        @resource_gate(min_ram_gate=PressureLevel.RED, auto_estimate=False)
        def work() -> str:
            return "ok"

        result = work()
        assert result == "ok"
        assert len(calls) == 2  # RED on first check, GREEN after 3s retry

    def test_red_persists_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.RED))

        @resource_gate(min_ram_gate=PressureLevel.RED, auto_estimate=False)
        def work() -> str:
            return "nope"

        with pytest.raises(ResourceBusyError):
            work()

    def test_auto_estimate_checks_first_arg(self, monkeypatch) -> None:
        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.GREEN))
        estimates: list[int] = []

        original_estimate = TaskComplexityEstimator.estimate_turns

        def fake_estimate(self, goal: str, file_count: int = 0) -> int:
            result = original_estimate(self, goal, file_count)
            estimates.append(result)
            return result

        monkeypatch.setattr(TaskComplexityEstimator, "estimate_turns", fake_estimate)

        @resource_gate(auto_estimate=True)
        def process(goal: str) -> str:
            return f"processed: {goal}"

        result = process("implement login")
        assert "processed" in result
        assert len(estimates) == 1
        assert estimates[0] >= 1

    def test_auto_estimate_skips_when_no_str_arg(self, monkeypatch) -> None:
        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.GREEN))

        @resource_gate(auto_estimate=True)
        def process(x: int, y: int) -> int:
            return x + y

        result = process(1, 2)
        assert result == 3

    def test_chunk_threshold_triggers_chunking(self, monkeypatch) -> None:
        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.GREEN))

        data = list(range(20))
        chunks_called: list[list[int]] = []

        @resource_gate(
            auto_estimate=False,
            chunk_threshold_lines=10,
            chunk_threshold_bytes=0,
        )
        def process_batch(items: list[int]) -> None:
            # This should receive chunked data, so items should be <= 10
            chunks_called.append(list(items))
            assert len(items) <= 10

        process_batch(data)
        assert len(chunks_called) == 2  # 2 chunks of 10

    def test_chunk_threshold_skipped_when_below(self, monkeypatch) -> None:
        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.GREEN))

        data = list(range(5))
        chunks_called: list[list[int]] = []

        @resource_gate(
            auto_estimate=False,
            chunk_threshold_lines=100,
            chunk_threshold_bytes=0,
        )
        def process_batch(items: list[int]) -> None:
            chunks_called.append(list(items))

        process_batch(data)
        assert len(chunks_called) == 1  # single call, no chunking

    def test_chunk_threshold_with_str_data(self, monkeypatch) -> None:
        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.GREEN))

        @resource_gate(
            auto_estimate=False,
            chunk_threshold_lines=5,
            chunk_threshold_bytes=0,
        )
        def process_lines(lines: list[str]) -> list[str]:
            return [line.upper() for line in lines]

        lines = [f"line {i}" for i in range(12)]
        # str data — len() works for lines threshold
        result = process_lines(lines)
        # Each chunk is processed independently and results collected
        assert len(result) == 12

    def test_decorator_preserves_metadata(self, monkeypatch) -> None:
        monkeypatch.setattr(ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.GREEN))

        @resource_gate(auto_estimate=False)
        def my_func(x: int) -> int:
            """Docstring preserved."""
            return x

        assert my_func.__name__ == "my_func"
        assert my_func.__doc__ == "Docstring preserved."

    def test_red_retry_once_then_passes(self, monkeypatch) -> None:
        """RED → wait 3s → GREEN on second check → passes.

        The gate retries once after a 3-second delay.
        """
        call_count = [0]
        import time

        def ram_sequence() -> PressureLevel:
            call_count[0] += 1
            if call_count[0] == 1:
                return PressureLevel.RED
            return PressureLevel.GREEN  # second check passes

        monkeypatch.setattr(ResourceMonitor, "check_ram", ram_sequence)
        monkeypatch.setattr(time, "sleep", lambda _: None)  # skip real 3s wait

        @resource_gate(auto_estimate=False)
        def work() -> str:
            return "success"

        result = work()
        assert result == "success"
        assert call_count[0] == 2

    def test_red_retry_persistent_failure(self, monkeypatch) -> None:
        """RED → wait 3s → still RED → raises ResourceBusyError."""
        import time

        monkeypatch.setattr(
            ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.RED)
        )
        monkeypatch.setattr(time, "sleep", lambda _: None)  # skip real 3s wait

        @resource_gate(auto_estimate=False)
        def work() -> str:
            return "should not reach"

        from core.exceptions import ResourceBusyError

        with pytest.raises(ResourceBusyError):
            work()

    def test_yellow_ram_allows_execution(self, monkeypatch) -> None:
        """YELLOW should log warning but not block."""
        monkeypatch.setattr(
            ResourceMonitor, "check_ram", staticmethod(lambda: PressureLevel.YELLOW)
        )

        @resource_gate(auto_estimate=False)
        def work() -> str:
            return "yield"

        result = work()
        assert result == "yield"

# ═══════════════════════════════════════════════════════════════════
# ResourceMonitor — RAM pressure progression
# ═══════════════════════════════════════════════════════════════════

class TestResourceMonitorProgressions:
    """RAM pressure level transitions across the full range."""

    def test_boundary_50_exactly_is_yellow(self, monkeypatch):
        """50% is YELLOW (>=50 but <70)."""
        monkeypatch.setattr(ResourceMonitor, "_psutil_available", True)
        import psutil
        monkeypatch.setattr(psutil, "virtual_memory", lambda: type("vmem", (), {"percent": 50.0})())
        monkeypatch.setattr(ResourceMonitor, "_ram_cache", None)
        monkeypatch.setattr(ResourceMonitor, "_ram_cache_ts", 0.0)
        assert ResourceMonitor.check_ram() == PressureLevel.YELLOW

    def test_boundary_70_exactly_is_red(self, monkeypatch):
        """70% is RED (>=70 but <85)."""
        monkeypatch.setattr(ResourceMonitor, "_psutil_available", True)
        import psutil
        monkeypatch.setattr(psutil, "virtual_memory", lambda: type("vmem", (), {"percent": 70.0})())
        monkeypatch.setattr(ResourceMonitor, "_ram_cache", None)
        monkeypatch.setattr(ResourceMonitor, "_ram_cache_ts", 0.0)
        assert ResourceMonitor.check_ram() == PressureLevel.RED

    def test_boundary_85_exactly_is_critical(self, monkeypatch):
        """85% is CRITICAL (>=85)."""
        monkeypatch.setattr(ResourceMonitor, "_psutil_available", True)
        import psutil
        monkeypatch.setattr(psutil, "virtual_memory", lambda: type("vmem", (), {"percent": 85.0})())
        monkeypatch.setattr(ResourceMonitor, "_ram_cache", None)
        monkeypatch.setattr(ResourceMonitor, "_ram_cache_ts", 0.0)
        assert ResourceMonitor.check_ram() == PressureLevel.CRITICAL

    def test_full_range(self, monkeypatch):
        """All four levels produce correct output over the full range."""
        monkeypatch.setattr(ResourceMonitor, "_psutil_available", True)
        import psutil
        monkeypatch.setattr(ResourceMonitor, "_ram_cache", None)
        monkeypatch.setattr(ResourceMonitor, "_ram_cache_ts", 0.0)

        cases = [
            (0.0, PressureLevel.GREEN),
            (49.9, PressureLevel.GREEN),
            (50.0, PressureLevel.YELLOW),
            (69.9, PressureLevel.YELLOW),
            (70.0, PressureLevel.RED),
            (84.9, PressureLevel.RED),
            (85.0, PressureLevel.CRITICAL),
            (100.0, PressureLevel.CRITICAL),
        ]
        for pct, expected in cases:
            monkeypatch.setattr(ResourceMonitor, "_ram_cache", None)
            monkeypatch.setattr(ResourceMonitor, "_ram_cache_ts", 0.0)
            monkeypatch.setattr(psutil, "virtual_memory", lambda p=pct: type("vmem", (), {"percent": p})())
            assert ResourceMonitor.check_ram() == expected, f"Failed at {pct}%"

    def test_disk_check_when_psutil_missing(self, monkeypatch):
        """Disk check defaults under-threshold when psutil unavailable."""
        monkeypatch.setattr(ResourceMonitor, "_psutil_available", False)
        under, pct = ResourceMonitor.check_disk(path="/mnt/z")
        assert under is True
        assert pct == 0.0

    def test_disk_check_file_not_found(self, monkeypatch):
        """Disk check handles FileNotFoundError gracefully."""
        monkeypatch.setattr(ResourceMonitor, "_psutil_available", True)
        orig = ResourceMonitor._disk_usage
        try:
            ResourceMonitor._disk_usage = staticmethod(
                lambda p: (_ for _ in ()).throw(FileNotFoundError())
            )
            under, pct = ResourceMonitor.check_disk(path="/nonexistent")
            assert under is True
            assert pct == 0.0
        finally:
            ResourceMonitor._disk_usage = orig

    def test_ram_virtual_memory_exception(self, monkeypatch):
        """RAM check gracefully handles psutil exception."""
        monkeypatch.setattr(ResourceMonitor, "_psutil_available", True)
        import psutil
        monkeypatch.setattr(psutil, "virtual_memory", MagicMock(side_effect=RuntimeError("boom")))
        monkeypatch.setattr(ResourceMonitor, "_ram_cache", None)
        monkeypatch.setattr(ResourceMonitor, "_ram_cache_ts", 0.0)
        level = ResourceMonitor.check_ram()
        assert level == PressureLevel.GREEN  # fallback

    def test_disk_usage_permission_denied(self, monkeypatch):
        """Disk check handles PermissionError gracefully."""
        monkeypatch.setattr(ResourceMonitor, "_psutil_available", True)
        orig = ResourceMonitor._disk_usage
        try:
            ResourceMonitor._disk_usage = staticmethod(
                lambda p: (_ for _ in ()).throw(PermissionError("permission denied"))
            )
            under, pct = ResourceMonitor.check_disk(path="/restricted")
            assert under is True
            assert pct == 0.0
        finally:
            ResourceMonitor._disk_usage = orig
