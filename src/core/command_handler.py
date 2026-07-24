"""P4d — Slash-command dispatcher for /goal and future commands.

Intercepts messages that start with ``/goal`` before they reach
the Router, routes them to the appropriate GoalManager method,
and returns a formatted response string.

Integration point: TransportAdapter.handle_message() checks
``command_handler.dispatch(text)`` before calling Router.process().
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from core.goal_manager import GoalManager

if TYPE_CHECKING:
    from core.scheduler import Scheduler

logger = logging.getLogger(__name__)

# ── Help text ────────────────────────────────────────────────────────────────

_HELP_TEXT = """**/goal** — manage persistent goals
```
/goal add <title> | <description>
/goal done <id>
/goal cancel <id>
/goal list
/goal status
/goal progress <id> <0-100>
```"""

_CRON_HELP = """**/cron** — manage scheduled jobs
```
/cron add "cron-expr" "title" | "description"
/cron list
/cron remove <id>
```"""


class CommandHandler:
    """Slash-command dispatcher.

    Currently supports only ``/goal``.  The ``dispatch()`` method
    returns a response string when the message is a handled command,
    or ``None`` to let the message flow through to the Router.
    """

    COMMAND_PREFIXES = ("/goal", "/cron")

    def __init__(self, goal_manager: GoalManager) -> None:
        self._goal_manager = goal_manager
        self._scheduler: Scheduler | None = None
        self._handlers: dict[str, callable] = {
            "add": self._handle_add,
            "done": self._handle_done,
            "cancel": self._handle_cancel,
            "list": self._handle_list,
            "status": self._handle_status,
            "progress": self._handle_progress,
        }

    def dispatch(self, text: str) -> str | None:
        """Handle a message that starts with a command prefix.

        Returns a response string if handled, or None if the message
        should be passed through to the Router.
        """
        if not text.startswith(self.COMMAND_PREFIXES):
            return None

        text = text.strip()
        parts = text.split(maxsplit=1)
        cmd = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

        # Route to command-specific handler
        if cmd == "/cron":
            return self._handle_cron(rest)
        else:
            return self._handle_goal(rest)

    def _handle_goal(self, rest: str) -> str:
        sub_parts = rest.split(maxsplit=1)
        sub = sub_parts[0].lower() if sub_parts else ""
        args = sub_parts[1] if len(sub_parts) > 1 else ""

        if not sub or sub in ("help", "h"):
            return _HELP_TEXT

        handler = self._handlers.get(sub)
        if handler is None:
            return f"Unknown subcommand: `{sub}`\n{_HELP_TEXT}"

        try:
            return handler(args)
        except Exception as exc:
            logger.exception("Error in /goal %s", sub)
            return f"❌ Error processing /goal {sub}: {exc}"

    def _handle_cron(self, rest: str) -> str:
        sub_parts = rest.split(maxsplit=1)
        sub = sub_parts[0].lower() if sub_parts else ""
        args = sub_parts[1] if len(sub_parts) > 1 else ""

        if not sub or sub in ("help", "h"):
            return _CRON_HELP

        return self._dispatch_cron(sub, args)

    # ── Subcommand handlers ─────────────────────────────────────────────

    def _handle_add(self, args: str) -> str:
        if not args.strip():
            return "Usage: `/goal add <title> | <description>`"

        # Split on the first `|` for optional description
        if "|" in args:
            title, desc = args.split("|", 1)
            title, desc = title.strip(), desc.strip()
        else:
            title, desc = args.strip(), ""

        if not title:
            return "Goal title cannot be empty."

        goal = self._goal_manager.create(title=title, description=desc)
        return f"✅ Goal created: `{goal.id}` — **{goal.title}**"

    def _handle_done(self, args: str) -> str:
        goal_id = args.strip()
        if not goal_id:
            return "Usage: `/goal done <id>`"
        goal = self._goal_manager.complete(goal_id)
        if goal is None:
            return f"❌ Goal `{goal_id}` not found or already completed."
        return f"✅ Goal completed: **{goal.title}**"

    def _handle_cancel(self, args: str) -> str:
        goal_id = args.strip()
        if not goal_id:
            return "Usage: `/goal cancel <id>`"
        goal = self._goal_manager.cancel(goal_id)
        if goal is None:
            return f"❌ Goal `{goal_id}` not found or already completed."
        return f"🗑️ Goal cancelled: **{goal.title}**"

    def _handle_list(self, args: str) -> str:
        active = self._goal_manager.list_active()
        if not active:
            return "No active goals. Use `/goal add` to create one."
        return self._goal_manager.status_report()

    def _handle_status(self, args: str) -> str:
        return self._goal_manager.status_report()

    def _handle_progress(self, args: str) -> str:
        parts = args.strip().split()
        if len(parts) < 2:
            return "Usage: `/goal progress <id> <0-100>`"
        goal_id = parts[0]
        try:
            pct = float(parts[1])
        except ValueError:
            return "Progress must be a number between 0 and 100."
        pct = max(0, min(100, pct))
        goal = self._goal_manager.update_progress(goal_id, pct / 100.0)
        if goal is None:
            return f"❌ Goal `{goal_id}` not found or not active."
        return f"📊 Goal **{goal.title}** → {pct:.0f}%"

    # ── Scheduler injection ────────────────────────────────────────────

    def set_scheduler(self, scheduler: Scheduler) -> None:
        """Bind the Scheduler for /cron commands (called after Router init)."""
        self._scheduler = scheduler  # type: ignore[assignment]

    # ── /cron subcommand handlers ───────────────────────────────────────

    def _dispatch_cron(self, sub: str, args: str) -> str:
        handlers = {
            "add": self._cron_add,
            "list": self._cron_list,
            "remove": self._cron_remove,
            "help": lambda a: _CRON_HELP,
            "h": lambda a: _CRON_HELP,
        }
        handler = handlers.get(sub)
        if handler is None:
            return f"Unknown subcommand: `{sub}`\n{_CRON_HELP}"
        try:
            return handler(args)
        except Exception as exc:
            logger.exception("/cron %s failed", sub)
            return f"❌ Error processing /cron {sub}: {exc}"

    def _cron_add(self, args: str) -> str:
        if self._scheduler is None:
            return "❌ Scheduler not available yet."
        if not args.strip():
            return f'Usage: `/cron add "cron-expr" "title"`\n{_CRON_HELP}'

        import shlex
        try:
            parts = shlex.split(args)
        except ValueError:
            parts = args.split()

        if len(parts) < 2:
            return f'Usage: `/cron add "cron-expr" "title"`\n{_CRON_HELP}'

        cron_expr = parts[0]
        title = " ".join(parts[1:]).strip()

        if not title:
            return "❌ Title cannot be empty."
        if "*" not in cron_expr:
            return f"❌ Invalid cron expression: `{cron_expr}`. Must contain at least one `*`."

        import asyncio
        from core.models import ScheduleType
        sid = asyncio.run(
            self._scheduler.add_schedule(  # type: ignore[union-attr]
                name=title,
                schedule_type=ScheduleType.CRON,
                cron_expression=cron_expr,
            )
        )
        return f"⏰ Cron scheduled: `{sid}` — **{title}** (`{cron_expr}`)"

    def _cron_list(self, args: str) -> str:
        if self._scheduler is None:
            return "❌ Scheduler not available yet."
        import asyncio
        schedules = asyncio.run(self._scheduler.list_schedules())  # type: ignore[union-attr]
        if not schedules:
            return "No scheduled jobs."
        lines = ["⏰ **Scheduled Jobs**"]
        for s in schedules:
            cron = getattr(s, "cron_expression", "n/a")
            lines.append(f"  `{s.schedule_id}` {cron} → {s.name}")
        return "\n".join(lines)

    def _cron_remove(self, args: str) -> str:
        if self._scheduler is None:
            return "❌ Scheduler not available yet."
        sid = args.strip()
        if not sid:
            return "Usage: `/cron remove <id>`"
        import asyncio
        asyncio.run(self._scheduler.remove_schedule(sid))  # type: ignore[union-attr]
        return f"🗑️ Cron job `{sid}` removed."
