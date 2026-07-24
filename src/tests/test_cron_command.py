"""P4d-ext tests — /cron command handler."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from core.command_handler import CommandHandler
from core.goal_manager import GoalManager


@pytest.fixture
def gm():
    return GoalManager(storage_path=Path(tempfile.mkdtemp()) / "goals.json")


@pytest.fixture
def ch(gm):
    return CommandHandler(gm)


# ── Dispatch basics ─────────────────────────────────────────────────────────

class TestCronDispatch:
    def test_cron_bare_returns_help(self, ch):
        result = ch.dispatch("/cron")
        assert "**/cron**" in result

    def test_cron_help(self, ch):
        result = ch.dispatch("/cron help")
        assert "**/cron**" in result

    def test_cron_unknown_subcommand(self, ch):
        result = ch.dispatch("/cron blah")
        assert "Unknown subcommand" in result

    def test_non_cron_returns_none(self, ch):
        assert ch.dispatch("hello") is None

    def test_slash_goal_still_works(self, ch):
        r = ch.dispatch("/goal list")
        assert "No active goals" in r


# ── Cron commands with mock scheduler ───────────────────────────────────────

class FakeSchedule:
    def __init__(self, sid, name, cron_expr):
        self.schedule_id = sid
        self.name = name
        self.cron_expression = cron_expr


class FakeScheduler:
    def __init__(self):
        self.schedules: dict[str, FakeSchedule] = {}
        self._next_id = 0

    async def add_schedule(self, *, name, schedule_type, cron_expression=None, **kw):
        self._next_id += 1
        sid = f"cron_{self._next_id:03d}"
        self.schedules[sid] = FakeSchedule(sid, name, cron_expression)
        return sid

    async def remove_schedule(self, schedule_id):
        self.schedules.pop(schedule_id, None)

    async def list_schedules(self, schedule_type=None):
        return list(self.schedules.values())


@pytest.fixture
def ch_with_scheduler(gm):
    ch = CommandHandler(gm)
    scheduler = FakeScheduler()
    ch.set_scheduler(scheduler)
    return ch


class TestCronWithScheduler:
    def test_add_cron(self, ch_with_scheduler):
        r = ch_with_scheduler.dispatch('/cron add "0 9 * * *" "daily report"')
        assert "⏰" in r
        assert "daily report" in r
        assert "0 9 * * *" in r
        assert "cron_001" in r

    def test_add_invalid_cron_no_star(self, ch_with_scheduler):
        r = ch_with_scheduler.dispatch('/cron add "not-a-cron" "title"')
        assert "❌" in r

    def test_add_empty_title(self, ch_with_scheduler):
        r = ch_with_scheduler.dispatch('/cron add "0 9 * * *"')
        assert "Usage" in r or "Title" in r

    def test_list_empty(self, ch_with_scheduler):
        r = ch_with_scheduler.dispatch("/cron list")
        assert "No scheduled jobs" in r

    def test_list_with_jobs(self, ch_with_scheduler):
        ch_with_scheduler.dispatch('/cron add "0 9 * * *" "morning"')
        ch_with_scheduler.dispatch('/cron add "0 18 * * *" "evening"')
        r = ch_with_scheduler.dispatch("/cron list")
        assert "morning" in r
        assert "evening" in r
        assert "0 9 * * *" in r

    def test_remove(self, ch_with_scheduler):
        r = ch_with_scheduler.dispatch('/cron add "0 9 * * *" "temp"')
        # extract id from response: `cron_001`
        sid = r.split("`")[1]
        r2 = ch_with_scheduler.dispatch(f"/cron remove {sid}")
        assert "🗑️" in r2
        assert sid in r2

    def test_remove_empty_id(self, ch_with_scheduler):
        r = ch_with_scheduler.dispatch("/cron remove")
        assert "Usage" in r

    def test_scheduler_not_set(self, ch):
        r = ch.dispatch('/cron add "0 9 * * *" "test"')
        assert "not available" in r
