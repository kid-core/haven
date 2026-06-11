"""
Tests for core/models.py — Pydantic models used throughout Haven.

Unit tests: no external dependencies, no mocking.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError

from core.models import (
    MessagePriority,
    ProviderResponse,
    ScheduleRecord,
    ScheduleStatus,
    ScheduleType,
    TaskMessage,
    TaskRecord,
    TaskStatus,
    ToolResult,
)


class TestProviderResponse:
    """ProviderResponse — normalised LLM response."""

    def test_content_only(self):
        resp = ProviderResponse(content="Hello")
        assert resp.content == "Hello"
        assert resp.tool_calls is None

    def test_tool_calls_only(self):
        calls = [{"id": "call_1", "function": {"name": "read_file"}}]
        resp = ProviderResponse(tool_calls=calls)
        assert resp.tool_calls == calls
        assert resp.content is None

    def test_content_and_tool_calls_mutual(self):
        """Both can be set (model decides); consumer should check content first."""
        resp = ProviderResponse(content="thinking...", tool_calls=None)
        assert resp.content == "thinking..."

    def test_reasoning_content(self):
        resp = ProviderResponse(content="Answer", reasoning_content="Step 1...")
        assert resp.reasoning_content == "Step 1..."

    def test_all_none_default(self):
        resp = ProviderResponse()
        assert resp.content is None
        assert resp.tool_calls is None
        assert resp.reasoning_content is None

    def test_empty_content_is_valid(self):
        resp = ProviderResponse(content="")
        assert resp.content == ""


class TestTaskStatus:
    """TaskStatus enum — lifecycle states."""

    def test_pending_is_default(self):
        rec = TaskRecord(name="test")
        assert rec.status == TaskStatus.PENDING

    def test_values_are_strings(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.CANCELLED.value == "cancelled"
        assert TaskStatus.TIMED_OUT.value == "timed_out"


class TestTaskRecord:
    """TaskRecord — background task persistence."""

    def test_auto_generates_task_id(self):
        rec = TaskRecord(name="my_task")
        assert len(rec.task_id) == 12
        assert isinstance(rec.task_id, str)

    def test_unique_ids(self):
        ids = {TaskRecord().task_id for _ in range(100)}
        assert len(ids) == 100

    def test_default_timeout(self):
        rec = TaskRecord()
        assert rec.timeout == 300.0

    def test_default_restored(self):
        rec = TaskRecord()
        assert rec.restored_from is False

    def test_custom_fields(self):
        rec = TaskRecord(
            name="build",
            timeout=60.0,
            metadata={"branch": "main"},
        )
        assert rec.name == "build"
        assert rec.timeout == 60.0
        assert rec.metadata == {"branch": "main"}

    def test_timestamps_auto_on_create(self):
        rec = TaskRecord()
        assert isinstance(rec.created_at, datetime)

    def test_serialises_to_dict(self):
        rec = TaskRecord(name="test", status=TaskStatus.RUNNING)
        d = rec.model_dump()
        assert d["name"] == "test"
        assert d["status"] == "running"


class TestToolResult:
    """ToolResult — OpenAI-compatible tool response."""

    def test_default_role(self):
        tr = ToolResult(tool_call_id="call_1", content="done")
        assert tr.role == "tool"

    def test_fields(self):
        tr = ToolResult(tool_call_id="call_1", content="file content")
        assert tr.tool_call_id == "call_1"
        assert tr.content == "file content"

    def test_serialises_correctly(self):
        tr = ToolResult(tool_call_id="call_x", content="ok")
        d = tr.model_dump()
        assert d["role"] == "tool"
        assert d["tool_call_id"] == "call_x"


class TestScheduleRecord:
    """ScheduleRecord — persisted schedule metadata."""

    def test_auto_generates_id(self):
        rec = ScheduleRecord(
            name="daily",
            schedule_type=ScheduleType.CRON,
            cron_expression="0 6 * * *",
        )
        assert len(rec.schedule_id) == 12

    def test_default_active(self):
        rec = ScheduleRecord(name="test", schedule_type=ScheduleType.AT)
        assert rec.status == ScheduleStatus.ACTIVE

    def test_cron_schedule(self):
        rec = ScheduleRecord(
            name="daily",
            schedule_type=ScheduleType.CRON,
            cron_expression="0 6 * * *",
            max_runs=None,
        )
        assert rec.cron_expression == "0 6 * * *"
        assert rec.max_runs is None

    def test_at_schedule(self):
        dt = datetime(2026, 12, 31, 23, 59)
        rec = ScheduleRecord(
            name="new_year",
            schedule_type=ScheduleType.AT,
            at_time=dt,
        )
        assert rec.at_time == dt

    def test_every_schedule(self):
        rec = ScheduleRecord(
            name="checker",
            schedule_type=ScheduleType.EVERY,
            interval_seconds=300.0,
        )
        assert rec.interval_seconds == 300.0

    def test_run_count_starts_at_zero(self):
        rec = ScheduleRecord(name="test", schedule_type=ScheduleType.AT)
        assert rec.run_count == 0

    def test_schedule_status_enum(self):
        assert ScheduleStatus.ACTIVE.value == "active"
        assert ScheduleStatus.PAUSED.value == "paused"
        assert ScheduleStatus.COMPLETED.value == "completed"
        assert ScheduleStatus.CANCELLED.value == "cancelled"

    def test_schedule_type_enum(self):
        assert ScheduleType.AT.value == "at"
        assert ScheduleType.EVERY.value == "every"
        assert ScheduleType.CRON.value == "cron"

    def test_max_runs_limits_repetition(self):
        rec = ScheduleRecord(
            name="limited",
            schedule_type=ScheduleType.EVERY,
            interval_seconds=60,
            max_runs=5,
        )
        assert rec.max_runs == 5


class TestMessagePriority:
    """MessagePriority enum."""

    def test_values(self):
        assert MessagePriority.NORMAL.value == "normal"
        assert MessagePriority.ALERT.value == "alert"


class TestTaskMessage:
    """TaskMessage — cross-task communication."""

    def test_default_not_read(self):
        msg = TaskMessage(to_task="t2", body="hi")
        assert msg.read is False

    def test_default_priority(self):
        msg = TaskMessage(to_task="t2", body="hi")
        assert msg.priority == MessagePriority.NORMAL

    def test_auto_generates_id(self):
        msg = TaskMessage(to_task="t2", body="hi")
        assert len(msg.msg_id) == 12
