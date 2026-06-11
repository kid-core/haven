"""Pydantic v2 models for structured data exchange."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# ── Phase 7: Scheduler enums ───────────────────────────────────────


class ScheduleStatus(StrEnum):
    """Schedule lifecycle states."""

    ACTIVE = auto()
    PAUSED = auto()
    COMPLETED = auto()
    CANCELLED = auto()


class ScheduleType(StrEnum):
    """Schedule timing strategies."""

    AT = auto()        # one-shot at a specific datetime
    EVERY = auto()     # repeating interval in seconds
    CRON = auto()      # standard cron expression


# ── Phase 6: Task enums ────────────────────────────────────────────


class TaskStatus(StrEnum):
    """Background task lifecycle states."""

    PENDING = auto()       # queued, not yet started
    RUNNING = auto()       # executing
    COMPLETED = auto()     # finished normally
    FAILED = auto()        # raised an exception
    CANCELLED = auto()     # cancelled by user or shutdown
    TIMED_OUT = auto()     # exceeded its timeout


class TaskRecord(BaseModel):
    """Full record for a background task."""

    task_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = ""
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: str | None = None
    error: str | None = None
    timeout: float | None = 300.0
    metadata: dict[str, str] = Field(default_factory=dict)
    restored_from: bool = False


class Usage(BaseModel):
    """Token usage from an OpenAI-compatible API response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ProviderResponse(BaseModel):
    """Normalised response from an LLM provider."""

    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    reasoning_content: str | None = None
    usage: Usage | None = None


class ToolResult(BaseModel):
    """OpenAI-compatible tool result message."""

    role: str = "tool"
    tool_call_id: str
    content: str


# ── Phase 7: Scheduler model ───────────────────────────────────────


# ── Phase 8: Cross-task messaging ───────────────────────────────


class MessagePriority(StrEnum):
    """Message priority levels for cross-task communication."""

    NORMAL = auto()
    ALERT = auto()


class TaskMessage(BaseModel):
    """A message sent between background tasks via MessageBus."""

    msg_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    from_task: str = ""
    to_task: str
    subject: str = ""
    body: str
    priority: MessagePriority = MessagePriority.NORMAL
    created_at: datetime = Field(default_factory=datetime.now)
    read: bool = False


class ScheduleRecord(BaseModel):
    """Full record for a scheduled job."""

    schedule_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = ""
    schedule_type: ScheduleType
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    # Timing fields — exactly one is set depending on schedule_type
    at_time: datetime | None = None
    interval_seconds: float | None = None
    cron_expression: str | None = None
    # Runtime stats
    created_at: datetime = Field(default_factory=datetime.now)
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    run_count: int = 0
    max_runs: int | None = None  # None = unlimited for EVERY/CRON
    # Metadata
    metadata: dict[str, str] = Field(default_factory=dict)
