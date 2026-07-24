"""Cross-task message bus with priority queues — Phase 8.

Each registered task_id gets an ordered list (sorted by priority then FIFO).
Overflow drops the oldest entry.  Wakeup via asyncio.Event.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .models import MessagePriority, TaskMessage

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Task-level send helpers ─────────────────────────────────────


class TaskContext:
    """Lightweight context for a running task to interact with the message bus."""

    def __init__(self, task_id: str, message_bus: MessageBus) -> None:
        self.task_id = task_id
        self._bus = message_bus

    async def send_message(
        self,
        to_task: str,
        body: str,
        *,
        subject: str = "",
        priority: str = "normal",
    ) -> bool:
        prio = (
            MessagePriority.ALERT
            if priority.lower() == "alert"
            else MessagePriority.NORMAL
        )
        return await self._bus.send(
            to_task,
            body,
            from_task=self.task_id,
            subject=subject,
            priority=prio,
        )

    async def send_progress(self, progress: float, status: str) -> bool:
        body = f"PROGRESS {progress:.2f} {status}"
        return await self._bus.send(
            self.task_id,
            body,
            from_task=self.task_id,
            subject="__progress__",
        )

    async def receive_message(self, timeout: float | None = None) -> TaskMessage | None:
        return await self._bus.receive(self.task_id, timeout=timeout)

    async def check_messages(self) -> list[TaskMessage]:
        msgs: list[TaskMessage] = []
        while True:
            msg = await self._bus.receive(self.task_id, timeout=0)
            if msg is None:
                break
            msgs.append(msg)
        return msgs


# ── MessageBus ──────────────────────────────────────────────────


class MessageBus:
    """In-memory cross-task message bus.

    Each registered task_id gets an ordered mailbox (capped at max_mailbox).
    Messages are ordered by priority (ALERT=0 before NORMAL=1), then FIFO
    within the same priority via a monotonic counter.
    """

    def __init__(self, max_mailbox: int = 100) -> None:
        self._mailboxes: dict[str, list[tuple[int, int, TaskMessage]]] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._counters: dict[str, int] = {}
        self._max_mailbox = max_mailbox
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────

    def register(self, task_id: str) -> None:
        """Create a mailbox for *task_id*.  Idempotent."""
        if task_id not in self._mailboxes:
            self._mailboxes[task_id] = []
            self._events[task_id] = asyncio.Event()
            self._counters[task_id] = 0

    def unregister(self, task_id: str) -> None:
        """Remove the mailbox for *task_id*.  Messages are discarded."""
        self._mailboxes.pop(task_id, None)
        self._events.pop(task_id, None)
        self._counters.pop(task_id, None)

    def mailbox_exists(self, task_id: str) -> bool:
        """Return True if *task_id* has a registered mailbox."""
        return task_id in self._mailboxes

    async def cleanup(self) -> int:
        """Remove all mailboxes.  Returns the number removed."""
        async with self._lock:
            removed = len(self._mailboxes)
            self._mailboxes.clear()
            self._events.clear()
            self._counters.clear()
        return removed

    # ── Send ──────────────────────────────────────────────────────

    async def send(
        self,
        to_task: str,
        body: str,
        *,
        from_task: str = "",
        subject: str = "",
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> bool:
        """Enqueue a message for *to_task*.  Returns False if mailbox missing."""
        if to_task not in self._mailboxes:
            logger.debug("MessageBus.send: no mailbox for %s", to_task)
            return False

        msg = TaskMessage(
            from_task=from_task,
            to_task=to_task,
            subject=subject,
            body=body,
            priority=priority,
            created_at=datetime.now(UTC),
        )
        prio = 0 if priority == MessagePriority.ALERT else 1

        async with self._lock:
            mbox = self._mailboxes[to_task]
            counter = self._counters[to_task]
            self._counters[to_task] = counter + 1
            mbox.append((prio, counter, msg))

            # Enforce mailbox cap — discard oldest (lowest index)
            while len(mbox) > self._max_mailbox:
                mbox.pop(0)

        # Wake any waiter
        self._events[to_task].set()
        return True

    # ── Receive ───────────────────────────────────────────────────

    async def receive(
        self, task_id: str, timeout: float | None = None
    ) -> TaskMessage | None:
        """Dequeue the next message (ALERT before NORMAL, then FIFO).

        Blocks up to *timeout* seconds.  Marks the message as read.
        Returns None on timeout or if mailbox doesn't exist.
        """
        mbox = self._mailboxes.get(task_id)
        if mbox is None:
            return None
        event = self._events[task_id]

        # Wait until there's something in the mailbox
        while True:
            async with self._lock:
                if len(mbox) > 0:
                    break
            if timeout is not None and timeout <= 0:
                return None
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            except TimeoutError:
                return None

        async with self._lock:
            if len(mbox) == 0:
                return None
            # Find best entry: min (prio, counter)
            best_idx = 0
            best_entry = mbox[0]
            for i, entry in enumerate(mbox):
                if entry[0] < best_entry[0] or (
                    entry[0] == best_entry[0] and entry[1] < best_entry[1]
                ):
                    best_entry = entry
                    best_idx = i
            del mbox[best_idx]
            _, _, msg = best_entry
            msg.read = True

        # Keep event set if more messages remain
        if len(mbox) > 0:
            event.set()
        return msg

    # ── Peek / Count ──────────────────────────────────────────────

    async def peek(self, task_id: str, limit: int = 10) -> list[TaskMessage]:
        """Return up to *limit* messages without marking them read.

        Sorted by priority then FIFO (same order as receive).
        """
        mbox = self._mailboxes.get(task_id)
        if mbox is None:
            return []

        async with self._lock:
            sorted_entries = sorted(mbox, key=lambda e: (e[0], e[1]))
            return [entry[2] for entry in sorted_entries[:limit]]

    async def count(self, task_id: str) -> int:
        """Return the number of messages in the mailbox."""
        mbox = self._mailboxes.get(task_id)
        if mbox is None:
            return 0
        async with self._lock:
            return len(mbox)
