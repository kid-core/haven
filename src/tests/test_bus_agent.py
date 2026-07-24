"""
Tests for core/message_bus.py + core/background_agent.py.

Covers: register/send/receive lifecycle, priority ordering, mailbox cap,
peek, cleanup, TaskContext, and BackgroundAgent construction/basic flow.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.message_bus import MessageBus, TaskContext
from core.models import MessagePriority, TaskMessage


# ═══════════════════════════════════════════════════════════════════
# MessageBus — lifecycle
# ═══════════════════════════════════════════════════════════════════

class TestMessageBusLifecycle:
    @pytest.fixture
    def bus(self) -> MessageBus:
        return MessageBus(max_mailbox=5)

    def test_register_creates_mailbox(self, bus: MessageBus):
        assert bus.mailbox_exists("task_a") is False
        bus.register("task_a")
        assert bus.mailbox_exists("task_a") is True

    def test_register_idempotent(self, bus: MessageBus):
        bus.register("task_a")
        bus.register("task_a")  # no crash
        assert bus.mailbox_exists("task_a") is True

    def test_unregister_removes_mailbox(self, bus: MessageBus):
        bus.register("task_a")
        bus.unregister("task_a")
        assert bus.mailbox_exists("task_a") is False

    def test_unregister_nonexistent_does_nothing(self, bus: MessageBus):
        bus.unregister("nobody")  # no crash

    async def test_cleanup_removes_all(self, bus: MessageBus):
        bus.register("a")
        bus.register("b")
        removed = await bus.cleanup()
        assert removed == 2
        assert bus.mailbox_exists("a") is False

    async def test_count_empty(self, bus: MessageBus):
        bus.register("task")
        assert await bus.count("task") == 0

    async def test_count_nonexistent(self, bus: MessageBus):
        assert await bus.count("ghost") == 0


# ═══════════════════════════════════════════════════════════════════
# MessageBus — send / receive
# ═══════════════════════════════════════════════════════════════════

class TestMessageBusSendReceive:
    @pytest.fixture
    def bus(self) -> MessageBus:
        return MessageBus(max_mailbox=10)

    async def test_send_receive(self, bus: MessageBus):
        bus.register("worker")
        sent = await bus.send("worker", "hello", from_task="boss")
        assert sent is True

        msg = await bus.receive("worker")
        assert msg is not None
        assert msg.body == "hello"
        assert msg.from_task == "boss"
        assert msg.to_task == "worker"
        assert msg.read is True

    async def test_send_to_nonexistent_returns_false(self, bus: MessageBus):
        sent = await bus.send("ghost", "hello")
        assert sent is False

    async def test_receive_non_registered_returns_none(self, bus: MessageBus):
        msg = await bus.receive("ghost")
        assert msg is None

    async def test_receive_timeout(self, bus: MessageBus):
        bus.register("worker")
        msg = await bus.receive("worker", timeout=0.01)
        assert msg is None

    async def test_fifo_order(self, bus: MessageBus):
        bus.register("worker")
        await bus.send("worker", "first", from_task="a")
        await bus.send("worker", "second", from_task="b")

        m1 = await bus.receive("worker")
        m2 = await bus.receive("worker")
        assert m1 is not None and m1.body == "first"
        assert m2 is not None and m2.body == "second"

    async def test_priority_alert_before_normal(self, bus: MessageBus):
        bus.register("worker")
        await bus.send("worker", "normal first", priority=MessagePriority.NORMAL)
        await bus.send("worker", "alert!", priority=MessagePriority.ALERT)

        # Alert should come out before NORMAL despite being sent second
        m1 = await bus.receive("worker")
        m2 = await bus.receive("worker")
        assert m1 is not None and m1.body == "alert!"
        assert m2 is not None and m2.body == "normal first"

    async def test_reuse_event_after_timeout(self, bus: MessageBus):
        """After a timeout, the next send should still wake the waiter."""
        bus.register("worker")

        # Timeout once with no messages
        msg = await bus.receive("worker", timeout=0.01)
        assert msg is None

        # Now send something
        await bus.send("worker", "wake up!")
        msg = await bus.receive("worker", timeout=0.01)
        assert msg is not None and msg.body == "wake up!"


# ═══════════════════════════════════════════════════════════════════
# MessageBus — mailbox cap
# ═══════════════════════════════════════════════════════════════════

class TestMailboxCap:
    async def test_overflow_drops_oldest(self):
        bus = MessageBus(max_mailbox=3)
        bus.register("worker")

        await bus.send("worker", "msg_a")
        await bus.send("worker", "msg_b")
        await bus.send("worker", "msg_c")
        await bus.send("worker", "msg_d")  # should drop "msg_a"

        assert await bus.count("worker") == 3

        m1 = await bus.receive("worker")
        m2 = await bus.receive("worker")
        m3 = await bus.receive("worker")
        assert m1 is not None and m1.body == "msg_b"  # "msg_a" was dropped
        assert m2 is not None and m2.body == "msg_c"
        assert m3 is not None and m3.body == "msg_d"
        assert await bus.count("worker") == 0


# ═══════════════════════════════════════════════════════════════════
# MessageBus — peek
# ═══════════════════════════════════════════════════════════════════

class TestPeek:
    async def test_peek_returns_without_marking_read(self):
        bus = MessageBus()
        bus.register("worker")
        await bus.send("worker", "peek me")

        msgs = await bus.peek("worker", limit=10)
        assert len(msgs) == 1
        assert msgs[0].body == "peek me"
        assert msgs[0].read is False  # not marked read

        # Message still available for receive
        msg = await bus.receive("worker")
        assert msg is not None and msg.body == "peek me"

    async def test_peek_nonexistent(self):
        bus = MessageBus()
        msgs = await bus.peek("ghost")
        assert msgs == []

    async def test_peek_limit(self):
        bus = MessageBus()
        bus.register("worker")
        for i in range(10):
            await bus.send("worker", f"msg_{i}")

        msgs = await bus.peek("worker", limit=3)
        assert len(msgs) == 3


# ═══════════════════════════════════════════════════════════════════
# TaskContext
# ═══════════════════════════════════════════════════════════════════

class TestTaskContext:
    @pytest.fixture
    def bus(self) -> MessageBus:
        bus = MessageBus()
        bus.register("parent")
        bus.register("worker")
        return bus

    async def test_send_message(self, bus: MessageBus):
        ctx = TaskContext(task_id="parent", message_bus=bus)
        sent = await ctx.send_message("worker", "do_work", subject="task")
        assert sent is True

        msg = await bus.receive("worker")
        assert msg is not None
        assert msg.body == "do_work"
        assert msg.subject == "task"

    async def test_send_progress(self, bus: MessageBus):
        ctx = TaskContext(task_id="worker", message_bus=bus)
        sent = await ctx.send_progress(0.5, "halfway")
        assert sent is True

        msg = await bus.receive("worker")
        assert msg is not None
        assert msg.subject == "__progress__"
        assert "0.50" in msg.body

    async def test_receive_message(self, bus: MessageBus):
        await bus.send("parent", "status_update", from_task="worker")
        ctx = TaskContext(task_id="parent", message_bus=bus)
        msg = await ctx.receive_message(timeout=0.5)
        assert msg is not None
        assert msg.body == "status_update"

    async def test_receive_timeout(self, bus: MessageBus):
        ctx = TaskContext(task_id="parent", message_bus=bus)
        msg = await ctx.receive_message(timeout=0.01)
        assert msg is None

    async def test_check_messages(self, bus: MessageBus):
        await bus.send("parent", "msg1", from_task="worker")
        await bus.send("parent", "msg2", from_task="worker")
        ctx = TaskContext(task_id="parent", message_bus=bus)
        msgs = await ctx.check_messages()
        assert len(msgs) == 2
        assert msgs[0].body == "msg1"
        assert msgs[1].body == "msg2"

    async def test_send_alert_converts_priority(self, bus: MessageBus):
        ctx = TaskContext(task_id="parent", message_bus=bus)
        await ctx.send_message("worker", "urgent", priority="alert")
        msg = await bus.receive("worker")
        assert msg is not None
        assert msg.priority == MessagePriority.ALERT


# ═══════════════════════════════════════════════════════════════════
# BackgroundAgent (bounded — no real provider calls)
# ═══════════════════════════════════════════════════════════════════

class TestBackgroundAgentConstruction:
    def test_initial_state(self):
        from core.background_agent import BackgroundAgent
        registry = MagicMock()
        agent = BackgroundAgent(
            goal="test goal",
            tool_registry=registry,
            providers=[],
        )
        assert agent.is_done is False
        assert agent.result is None
        assert "test goal" in agent._goal

    def test_to_dict_snapshot(self):
        from core.background_agent import BackgroundAgent
        registry = MagicMock()
        agent = BackgroundAgent(
            goal="search and summarize",
            tool_registry=registry,
            providers=[],
            max_turns=5,
        )
        d = agent.to_dict()
        assert "goal" in d
        assert "search" in d["goal"]
        assert d["max_turns"] == 5
        assert d["turns_used"] == 0  # only system prompt so far

    def test_is_done_reflects_result(self):
        from core.background_agent import BackgroundAgent
        registry = MagicMock()
        agent = BackgroundAgent(goal="x", tool_registry=registry, providers=[])
        assert agent.is_done is False
        agent._result = "done"
        agent._is_done = True
        assert agent.is_done is True
        assert agent.result == "done"

    def test_tools_allow_restricts(self):
        from core.background_agent import BackgroundAgent
        registry = MagicMock()
        agent = BackgroundAgent(
            goal="x", tool_registry=registry, providers=[],
            tools_allow=["read_file", "search_web"],
        )
        assert agent._tools_allow == {"read_file", "search_web"}

    def test_system_prompt_includes_extra(self):
        from core.background_agent import BackgroundAgent
        registry = MagicMock()
        agent = BackgroundAgent(
            goal="x", tool_registry=registry, providers=[],
            system_prompt_extra="Be careful.",
        )
        prompt = agent._system_prompt
        assert "Be careful." in prompt
        assert "autonomous" in prompt

    def test_default_max_turns(self):
        from core.background_agent import BackgroundAgent
        registry = MagicMock()
        agent = BackgroundAgent(goal="x", tool_registry=registry, providers=[])
        assert agent._max_turns == 60

    def test_custom_timeout(self):
        from core.background_agent import BackgroundAgent
        registry = MagicMock()
        agent = BackgroundAgent(goal="x", tool_registry=registry, providers=[], timeout=30.0)
        assert agent._timeout == 30.0

    def test_run_calls_run_loop(self):
        from core.background_agent import BackgroundAgent

        registry = MagicMock()
        agent = BackgroundAgent(goal="x", tool_registry=registry, providers=[])

        # Mock _run_loop to avoid real execution
        async def fake_run():
            return "simulated result"

        agent._run_loop = fake_run
        import asyncio
        result = asyncio.run(agent.run())
        assert result == "simulated result"
        assert agent.is_done is True
        assert agent.result == "simulated result"
