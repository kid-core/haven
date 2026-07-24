"""Phase 8 tests — MessageBus, TaskContext, cross-task messaging."""

from __future__ import annotations

import asyncio

import pytest
from core.message_bus import MessageBus, TaskContext
from core.models import MessagePriority, TaskMessage


class TestMessageBus:
    """Unit tests for MessageBus — send, receive, priority, limits."""

    @pytest.mark.asyncio
    async def test_send_and_receive(self) -> None:
        """發送訊息 → 接收確認內容正確"""
        bus = MessageBus()
        bus.register("task_a")
        bus.register("task_b")

        ok = await bus.send("task_b", "hello from a", from_task="task_a")
        assert ok is True

        msg = await bus.receive("task_b", timeout=1.0)
        assert msg is not None
        assert msg.body == "hello from a"
        assert msg.from_task == "task_a"
        assert msg.to_task == "task_b"
        assert msg.read is True

        # No more messages
        msg2 = await bus.receive("task_b", timeout=0.1)
        assert msg2 is None

    @pytest.mark.asyncio
    async def test_mailbox_limit(self) -> None:
        """超過 100 則自動丟棄最舊的"""
        bus = MessageBus(max_mailbox=5)  # small cap for testing
        bus.register("task_x")

        for i in range(7):
            await bus.send("task_x", f"msg-{i}")

        # Should have exactly 5 messages (oldest 2 discarded)
        assert await bus.count("task_x") == 5

        # First received should be msg-2 (oldest retained)
        first = await bus.receive("task_x", timeout=1.0)
        assert first is not None
        assert first.body == "msg-2"

        # Last should be msg-6
        for _ in range(3):
            await bus.receive("task_x", timeout=0.5)
        last = await bus.receive("task_x", timeout=0.5)
        assert last is not None
        assert last.body == "msg-6"

    @pytest.mark.asyncio
    async def test_priority_alert(self) -> None:
        """ALERT 比 NORMAL 優先跳出，同級內 FIFO"""
        bus = MessageBus()
        bus.register("task_p")

        # Send NORMAL messages first
        await bus.send("task_p", "normal-1", priority=MessagePriority.NORMAL)
        await bus.send("task_p", "normal-2", priority=MessagePriority.NORMAL)

        # Send ALERT — should come before the NORMALs
        await bus.send("task_p", "alert!", priority=MessagePriority.ALERT)

        # Send another NORMAL after ALERT
        await bus.send("task_p", "normal-3", priority=MessagePriority.NORMAL)

        # Receive order: ALERT first, then NORMAL in FIFO order
        m1 = await bus.receive("task_p", timeout=1.0)
        assert m1 is not None
        assert m1.body == "alert!"
        assert m1.priority == MessagePriority.ALERT

        m2 = await bus.receive("task_p", timeout=1.0)
        assert m2 is not None
        assert m2.body == "normal-1"

        m3 = await bus.receive("task_p", timeout=1.0)
        assert m3 is not None
        assert m3.body == "normal-2"

        m4 = await bus.receive("task_p", timeout=1.0)
        assert m4 is not None
        assert m4.body == "normal-3"

        # Queue empty
        assert await bus.receive("task_p", timeout=0.1) is None

    @pytest.mark.asyncio
    async def test_send_to_nonexistent(self) -> None:
        """發送到不存在的 task_id 回傳 False"""
        bus = MessageBus()
        ok = await bus.send("ghost", "nobody here")
        assert ok is False

    @pytest.mark.asyncio
    async def test_task_progress(self) -> None:
        """模擬任務用 TaskContext.send_progress() 回報，主任務查詢"""
        bus = MessageBus()
        bus.register("parent")
        ctx = TaskContext("child", bus)

        bus.register("child")

        await ctx.send_progress(0.3, "starting")
        await ctx.send_progress(0.7, "almost done")

        msgs = await bus.peek("child")
        assert len(msgs) == 2

        # Check content via receive
        p1 = await bus.receive("child", timeout=0.5)
        assert p1 is not None
        assert "0.3" in p1.body
        assert "starting" in p1.body

        p2 = await bus.receive("child", timeout=0.5)
        assert p2 is not None
        assert "0.7" in p2.body
        assert "almost done" in p2.body

    @pytest.mark.asyncio
    async def test_task_remote_command(self) -> None:
        """發送 STOP，任務收到後自行終止"""
        bus = MessageBus()
        bus.register("worker")

        async def worker_loop(ctx: TaskContext) -> str:
            while True:
                msgs = await ctx.check_messages()
                for m in msgs:
                    if m.body == "STOP":
                        return "stopped"
                await asyncio.sleep(0.01)

        # Send STOP command
        await bus.send("worker", "STOP")
        ctx_w = TaskContext("worker", bus)
        result = await asyncio.wait_for(worker_loop(ctx_w), timeout=2.0)
        assert result == "stopped"

        # Worker mailbox should be empty after consuming STOP
        assert await bus.count("worker") == 0

    @pytest.mark.asyncio
    async def test_multiple_messages(self) -> None:
        """收發多則訊息，確認順序正確"""
        bus = MessageBus()
        bus.register("receiver")

        for i in range(10):
            await bus.send("receiver", f"msg-{i}", subject=f"subj-{i}")

        received: list[TaskMessage] = []
        for _ in range(10):
            msg = await bus.receive("receiver", timeout=1.0)
            assert msg is not None
            received.append(msg)

        bodies = [m.body for m in received]
        subjects = [m.subject for m in received]
        assert bodies == [f"msg-{i}" for i in range(10)]
        assert subjects == [f"subj-{i}" for i in range(10)]

        assert await bus.count("receiver") == 0

    @pytest.mark.asyncio
    async def test_unregister(self) -> None:
        """取消註冊後信箱消失，send 回傳 False"""
        bus = MessageBus()
        bus.register("temp")
        await bus.send("temp", "hello")
        assert await bus.count("temp") == 1

        bus.unregister("temp")
        assert bus.mailbox_exists("temp") is False

        ok = await bus.send("temp", "should fail")
        assert ok is False
        assert await bus.receive("temp", timeout=0.1) is None

    @pytest.mark.asyncio
    async def test_cleanup(self) -> None:
        """cleanup 清除所有信箱"""
        bus = MessageBus()
        for tid in ["a", "b", "c"]:
            bus.register(tid)
            await bus.send(tid, f"msg to {tid}")

        removed = await bus.cleanup()
        assert removed == 3

        for tid in ["a", "b", "c"]:
            assert bus.mailbox_exists(tid) is False

    @pytest.mark.asyncio
    async def test_context_send_message(self) -> None:
        """TaskContext.send_message 正確轉發"""
        bus = MessageBus()
        bus.register("alpha")
        bus.register("beta")

        ctx = TaskContext("alpha", bus)
        ok = await ctx.send_message("beta", "hi from alpha", subject="greeting")
        assert ok is True

        msg = await bus.receive("beta", timeout=1.0)
        assert msg is not None
        assert msg.body == "hi from alpha"
        assert msg.from_task == "alpha"
        assert msg.subject == "greeting"

    # ── Phase 5: Additional edge cases ──────────────────────────

    @pytest.mark.asyncio
    async def test_concurrent_send_receive(self) -> None:
        """多個 task 平行收發不互相干擾"""
        bus = MessageBus()
        for tid in ["a", "b", "c"]:
            bus.register(tid)

        async def ping_pong(sender: str, receiver: str, n: int) -> int:
            sent = 0
            for i in range(n):
                ok = await bus.send(receiver, f"{sender}->{receiver}#{i}")
                if ok:
                    sent += 1
            return sent

        results = await asyncio.gather(
            ping_pong("a", "b", 5),
            ping_pong("b", "c", 5),
            ping_pong("c", "a", 5),
        )
        assert sum(results) == 15

        assert await bus.count("a") == 5
        assert await bus.count("b") == 5
        assert await bus.count("c") == 5

    @pytest.mark.asyncio
    async def test_priority_lower_before_higher(self) -> None:
        """NORMAL 先到，ALERT 後到 → ALERT 插隊"""
        bus = MessageBus()
        bus.register("target")

        await bus.send("target", "normal-1")
        await bus.send("target", "normal-2")
        await bus.send("target", "alert!", priority=MessagePriority.ALERT)
        await bus.send("target", "normal-3")

        order = []
        while True:
            msg = await bus.receive("target", timeout=0.2)
            if msg is None:
                break
            order.append(msg.body)

        assert order == ["alert!", "normal-1", "normal-2", "normal-3"]

    @pytest.mark.asyncio
    async def test_priority_alert_on_empty_queue(self) -> None:
        """ALERT on empty queue → still delivered"""
        bus = MessageBus()
        bus.register("empty")

        await bus.send("empty", "urgent", priority=MessagePriority.ALERT)

        msg = await bus.receive("empty", timeout=1.0)
        assert msg is not None
        assert msg.body == "urgent"
        assert msg.priority == MessagePriority.ALERT
