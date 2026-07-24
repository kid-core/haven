"""Core domain exceptions for the Haven system."""


class HavenError(Exception):
    """Base for all Haven errors."""


class ProviderError(HavenError):
    """LLM provider errors."""


class RouterError(HavenError):
    """Router/ReAct loop errors."""


class RegistryError(HavenError):
    """Tool registry errors."""


class TaskError(HavenError):
    """Base for background-task errors."""


class TaskNotFoundError(TaskError):
    """Requested task id does not exist."""


class TaskTimeoutError(TaskError):
    """wait_for timed out before the task completed."""


# ── Phase 7: Scheduler errors ─────────────────────────────────────


class SchedulerError(HavenError):
    """Base for scheduler errors."""


class ScheduleNotFoundError(SchedulerError):
    """Requested schedule id does not exist."""


class ScheduleConflictError(SchedulerError):
    """Schedule name or timing conflicts with an existing schedule."""


class InvalidCronExpressionError(SchedulerError):
    """The provided cron expression is not valid."""


# ── Phase: Resource Gate errors ────────────────────────────────────


class ResourceBusyError(HavenError):
    """System resource insufficient, task queued or rejected."""
