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

from core.goal_manager import GoalManager

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


class CommandHandler:
    """Slash-command dispatcher.

    Currently supports only ``/goal``.  The ``dispatch()`` method
    returns a response string when the message is a handled command,
    or ``None`` to let the message flow through to the Router.
    """

    COMMAND_PREFIXES = ("/goal",)

    def __init__(self, goal_manager: GoalManager) -> None:
        self._goal_manager = goal_manager
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
        # Parse "/goal <subcommand> [args...]"
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return _HELP_TEXT

        cmd = parts[0]  # "/goal"
        rest = parts[1]  # "<subcommand> [args]"

        sub_parts = rest.split(maxsplit=1)
        sub = sub_parts[0].lower()
        args = sub_parts[1] if len(sub_parts) > 1 else ""

        if sub in ("help", "h"):
            return _HELP_TEXT

        handler = self._handlers.get(sub)
        if handler is None:
            return f"Unknown subcommand: `{sub}`\n{_HELP_TEXT}"

        try:
            return handler(args)
        except Exception as exc:
            logger.exception("/goal %s failed", sub)
            return f"❌ Error processing /goal {sub}: {exc}"

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
