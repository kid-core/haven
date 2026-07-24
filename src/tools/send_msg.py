"""Cross-task messaging tools — send and check messages between tasks (Phase 8).

Two tools:
- send_task_message:  send a message to another task's mailbox
- check_task_messages: read messages from own mailbox (marks as read when mark_read=True)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.categories import ToolCategory
from core.models import MessagePriority
from core.policy import ToolPolicy
from core.tool_decorator import tool

if TYPE_CHECKING:
    from core.message_bus import MessageBus

logger = logging.getLogger(__name__)

# Module-level message bus — set by Router during init
_message_bus: MessageBus | None = None


def set_message_bus(bus: MessageBus) -> None:
    """Inject the MessageBus (called by Router on init)."""
    global _message_bus  # noqa: PLW0603
    _message_bus = bus


def _bus() -> MessageBus | None:
    return _message_bus


def _msg_to_dict(msg) -> dict:
    """Serialise a TaskMessage into a JSON-safe dict."""
    return {
        "msg_id": msg.msg_id,
        "from_task": msg.from_task,
        "to_task": msg.to_task,
        "subject": msg.subject,
        "body": msg.body,
        "priority": msg.priority.value,
        "created_at": msg.created_at.isoformat(),
        "read": msg.read,
    }


@tool(
    name="send_task_message",
    category=ToolCategory.COLLAB,
    policy=ToolPolicy(timeout=5.0),
)
async def send_task_message(
    task_id: str,
    message: str,
    subject: str = "",
    priority: str = "normal",
) -> dict:
    """Send a message to a background task's mailbox.

    The target task can read it via check_task_messages or its TaskContext.

    Args:
        task_id: Target task id (12 hex chars).
        message: Message body text.
        subject: Optional subject line.
        priority: "normal" or "alert" (ALERT messages jump the queue).

    Returns:
        dict with sent status.
    """
    bus = _bus()
    if bus is None:
        return {"sent": False, "error": "MessageBus not available"}

    prio = MessagePriority.ALERT if priority.lower() == "alert" else MessagePriority.NORMAL
    ok = await bus.send(task_id, message, from_task="user", subject=subject, priority=prio)
    if not ok:
        return {"sent": False, "error": f"Task {task_id} not found or mailbox not registered"}

    return {"sent": True, "task_id": task_id, "priority": prio.value}


@tool(
    name="check_task_messages",
    category=ToolCategory.COLLAB,
    policy=ToolPolicy(timeout=5.0),
)
async def check_task_messages(
    task_id: str,
    mark_read: bool = True,
    limit: int = 10,
) -> list[dict]:
    """Check a task's mailbox for incoming messages.

    Args:
        task_id: Task id whose mailbox to check.
        mark_read: If True (default), messages are consumed (receive).
                   If False, peeks without marking read.
        limit: Max messages to return (default 10).

    Returns:
        List of message dicts, FIFO order.
    """
    bus = _bus()
    if bus is None:
        return [{"error": "MessageBus not available"}]

    if mark_read:
        msgs: list[dict] = []
        for _ in range(limit):
            msg = await bus.receive(task_id, timeout=0)
            if msg is None:
                break
            msgs.append(_msg_to_dict(msg))
        return msgs

    raw = await bus.peek(task_id, limit=limit)
    return [_msg_to_dict(m) for m in raw]
