"""P4d tests — GoalManager, CommandHandler, and Transport integration."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.goal_manager import Goal, GoalManager, _progress_bar


# ── Progress bar helper ──────────────────────────────────────────────────────

class TestProgressBar:
    def test_zero(self):
        assert _progress_bar(0.0) == "░░░░░░░░░░ 0%"

    def test_half(self):
        bar = _progress_bar(0.5)
        assert "50%" in bar
        assert bar.count("█") == 5
        assert bar.count("░") == 5

    def test_full(self):
        bar = _progress_bar(1.0)
        assert "100%" in bar
        assert "░" not in bar

    def test_clamped(self):
        assert _progress_bar(1.5) == _progress_bar(1.0)
        assert _progress_bar(-0.5) == _progress_bar(0.0)


# ── Goal dataclass ───────────────────────────────────────────────────────────

class TestGoal:
    def test_construction(self):
        g = Goal(id="abc", title="Test")
        assert g.status == "active"
        assert g.progress == 0.0
        assert g.tags == []

    def test_roundtrip(self):
        g = Goal(
            id="g1", title="Write tests", description="Cover P4d",
            status="active", created_at=123456.0, progress=0.3,
            tags=["testing"],
        )
        d = g.to_dict()
        g2 = Goal.from_dict(d)
        assert g2.id == "g1"
        assert g2.title == "Write tests"
        assert g2.description == "Cover P4d"
        assert g2.progress == 0.3
        assert g2.tags == ["testing"]

    def test_from_dict_minimal(self):
        g = Goal.from_dict({"id": "x", "title": "minimal"})
        assert g.description == ""
        assert g.status == "active"
        assert g.progress == 0.0


# ── GoalManager CRUD ─────────────────────────────────────────────────────────

@pytest.fixture
def gm():
    with tempfile.TemporaryDirectory() as td:
        yield GoalManager(storage_path=Path(td) / "goals.json")


class TestGoalManagerCRUD:
    def test_create(self, gm):
        g = gm.create("Learn Rust")
        assert g.title == "Learn Rust"
        assert g.status == "active"
        assert g.id
        assert len(gm) == 1

    def test_create_with_description(self, gm):
        g = gm.create("Learn Rust", "Focus on async")
        assert g.description == "Focus on async"

    def test_complete(self, gm):
        g = gm.create("Done task")
        gm.complete(g.id)
        fetched = gm.get(g.id)
        assert fetched is not None
        assert fetched.status == "completed"
        assert fetched.progress == 1.0

    def test_cancel(self, gm):
        g = gm.create("Nope")
        gm.cancel(g.id)
        assert gm.get(g.id).status == "cancelled"

    def test_complete_nonexistent(self, gm):
        assert gm.complete("ghost") is None

    def test_list_active(self, gm):
        gm.create("A")
        gm.create("B")
        g = gm.create("C")
        gm.complete(g.id)
        active = gm.list_active()
        assert len(active) == 2

    def test_list_all(self, gm):
        gm.create("A")
        gm.create("B")
        assert len(gm.list_all()) == 2

    def test_update_progress(self, gm):
        g = gm.create("Progress")
        gm.update_progress(g.id, 0.75)
        assert gm.get(g.id).progress == 0.75

    def test_update_progress_clamped(self, gm):
        g = gm.create("Clamp")
        gm.update_progress(g.id, 2.0)
        assert gm.get(g.id).progress == 1.0
        gm.update_progress(g.id, -1.0)
        assert gm.get(g.id).progress == 0.0


# ── GoalManager persistence ──────────────────────────────────────────────────

class TestGoalManagerPersistence:
    def test_survives_reload(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "goals.json"
            gm1 = GoalManager(storage_path=path)
            gm1.create("Persist me")
            gm1.create("Me too")

            gm2 = GoalManager(storage_path=path)
            assert len(gm2) == 2
            active = gm2.list_active()
            assert len(active) == 2


# ── GoalManager context injection ────────────────────────────────────────────

class TestGoalInjection:
    def test_empty_returns_empty(self, gm):
        assert gm.inject_into_context() == ""

    def test_active_goals_injected(self, gm):
        gm.create("Goal 1", "First thing")
        gm.create("Goal 2")
        ctx = gm.inject_into_context()
        assert "[Active Goals]" in ctx
        assert "Goal 1" in ctx
        assert "Goal 2" in ctx

    def test_completed_goals_not_injected(self, gm):
        g = gm.create("Done")
        gm.complete(g.id)
        ctx = gm.inject_into_context()
        assert ctx == "" or "Done" not in ctx


# ── GoalManager status_report ────────────────────────────────────────────────

class TestGoalStatusReport:
    def test_empty_report(self, gm):
        r = gm.status_report()
        assert "Active: 0" in r

    def test_report_with_goals(self, gm):
        gm.create("Active goal")
        g = gm.create("Done goal")
        gm.complete(g.id)
        r = gm.status_report()
        assert "Active: 1" in r
        assert "Completed: 1" in r
        assert "Active goal" in r


# ── CommandHandler dispatch ──────────────────────────────────────────────────

@pytest.fixture
def ch(gm):
    from core.command_handler import CommandHandler
    return CommandHandler(gm)


class TestCommandHandlerDispatch:
    def test_non_command_returns_none(self, ch):
        assert ch.dispatch("hello world") is None
        assert ch.dispatch("what is /goal") is None

    def test_goal_bare_returns_help(self, ch):
        result = ch.dispatch("/goal")
        assert result is not None
        assert "**/goal**" in result

    def test_goal_add(self, ch):
        r = ch.dispatch("/goal add Buy milk")
        assert "✅" in r
        assert "Buy milk" in r

    def test_goal_add_with_description(self, ch):
        r = ch.dispatch("/goal add Buy milk | from supermarket")
        assert "Buy milk" in r

    def test_goal_add_empty_title(self, ch):
        r = ch.dispatch("/goal add")
        assert "Usage" in r or "title" in r.lower()

    def test_goal_done(self, ch):
        g = ch._goal_manager.create("Finish")
        r = ch.dispatch(f"/goal done {g.id}")
        assert "✅" in r
        assert ch._goal_manager.get(g.id).status == "completed"

    def test_goal_done_nonexistent(self, ch):
        r = ch.dispatch("/goal done ghost-id")
        assert "❌" in r or "not found" in r

    def test_goal_cancel(self, ch):
        g = ch._goal_manager.create("Abort")
        r = ch.dispatch(f"/goal cancel {g.id}")
        assert "🗑️" in r

    def test_goal_list(self, ch):
        ch._goal_manager.create("A")
        ch._goal_manager.create("B")
        r = ch.dispatch("/goal list")
        assert "A" in r
        assert "B" in r

    def test_goal_list_empty(self, ch):
        r = ch.dispatch("/goal list")
        assert "No active goals" in r

    def test_goal_status(self, ch):
        r = ch.dispatch("/goal status")
        assert "📋" in r

    def test_goal_progress(self, ch):
        g = ch._goal_manager.create("Progress it")
        r = ch.dispatch(f"/goal progress {g.id} 80")
        assert "80%" in r
        assert ch._goal_manager.get(g.id).progress == 0.8

    def test_goal_help(self, ch):
        r = ch.dispatch("/goal help")
        assert "**/goal**" in r

    def test_goal_unknown_subcommand(self, ch):
        r = ch.dispatch("/goal blah")
        assert "Unknown subcommand" in r


# ── Transport adapter command interception ───────────────────────────────────

class TestTransportCommandInterception:
    """Verify that TransportAdapter routes /goal commands to CommandHandler."""

    async def test_command_routes_to_handler(self):
        from unittest.mock import MagicMock, AsyncMock
        from transport.adapter import TransportAdapter
        from core.command_handler import CommandHandler
        from core.goal_manager import GoalManager

        gm = GoalManager(storage_path=Path(tempfile.mkdtemp()) / "goals.json")
        ch = CommandHandler(gm)

        # Stub the abstract methods
        adapter = TransportAdapter.__new__(TransportAdapter)
        adapter._router = MagicMock()
        adapter._allowed_user_ids = set()
        adapter._transport_name = "test"
        adapter._command_handler = ch

        # Override primitives for the test
        adapter._extract_user_id = lambda msg: "user1"
        adapter._extract_text = lambda msg: msg["text"]
        adapter._extract_channel_id = lambda msg: "ch1"
        adapter._send_text = AsyncMock(return_value=True)
        adapter._is_user_allowed = lambda uid: True

        await adapter.handle_message({"text": "/goal list"})
        # Should NOT call router.process
        adapter._router.process.assert_not_called()
        # Should send a response
        adapter._send_text.assert_called_once()

    async def test_non_command_routes_to_router(self):
        from unittest.mock import MagicMock, AsyncMock
        from transport.adapter import TransportAdapter
        from core.command_handler import CommandHandler
        from core.goal_manager import GoalManager

        gm = GoalManager(storage_path=Path(tempfile.mkdtemp()) / "goals.json")
        ch = CommandHandler(gm)

        adapter = TransportAdapter.__new__(TransportAdapter)
        adapter._router = MagicMock()
        adapter._router.process = AsyncMock(return_value="router response")
        adapter._router.pop_pending_files = MagicMock(return_value=[])
        adapter._allowed_user_ids = set()
        adapter._transport_name = "test"
        adapter._command_handler = ch

        adapter._extract_user_id = lambda msg: "user1"
        adapter._extract_text = lambda msg: msg["text"]
        adapter._extract_channel_id = lambda msg: "ch1"
        adapter._send_text = AsyncMock(return_value=True)
        adapter._is_user_allowed = lambda uid: True

        await adapter.handle_message({"text": "plain message"})
        adapter._router.process.assert_called_once()


# ── Integration: P4a assembler goal layer ────────────────────────────────────

class TestAssemblerGoalLayer:
    def test_goal_layer_injects_active_goals(self):
        from core.prompt_assembler import SystemPromptAssembler
        from core.goal_manager import GoalManager

        gm = GoalManager(storage_path=Path(tempfile.mkdtemp()) / "goals.json")
        gm.create("Ship P4d", "Deliver /goal system")

        assembler = SystemPromptAssembler(identity_text="TestBot")
        assembler.register_layer(
            "goals",
            lambda ctx: gm.inject_into_context(),
            after="runtime",
        )
        prompt = assembler.build(session_id="test")
        assert "[Active Goals]" in prompt
        assert "Ship P4d" in prompt

    def test_empty_goals_produces_no_layer(self, gm):
        from core.prompt_assembler import SystemPromptAssembler

        assembler = SystemPromptAssembler(identity_text="TestBot")
        assembler.register_layer(
            "goals",
            lambda ctx: gm.inject_into_context(),
            after="runtime",
        )
        prompt = assembler.build(session_id="test")
        # When no active goals, inject_into_context returns "" → layer skipped
        assert "[Active Goals]" not in prompt
