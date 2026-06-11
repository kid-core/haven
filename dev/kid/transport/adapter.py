"""
TransportAdapter — abstract base for all transport channels.

Shared logic lives here:
  - user whitelist (allowed_user_ids)
  - session_id generation
  - mention/ping stripping
  - router.process() dispatch
  - pending file delivery

Each transport subclass implements four primitives:
  - _send_text(channel_id, text) -> bool
  - _send_file(channel_id, file_path, filename) -> bool
  - _extract_user_id(msg) -> str
  - _extract_text(msg) -> str
  - _extract_channel_id(msg) -> str
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)

# Pattern to strip @mentions and role pings
_MENTION_RE = re.compile(r"<@!\d+>|<@\d+>|<@&\d+>")


# ── Abstract base for transports ──────────────────────────────

class TransportAdapter:
    """Subclass this and implement the five primitives below."""

    def __init__(
        self,
        router: Router,
        allowed_user_ids: list[str] | None = None,
        transport_name: str | None = None,
        command_handler: Any | None = None,
    ) -> None:
        self._router = router
        self._allowed_user_ids = set(allowed_user_ids) if allowed_user_ids else set()
        self._transport_name = transport_name or self.__class__.__name__
        self._command_handler = command_handler

    # ══════════════════════════════════════════════════════════════
    # Primitives — override in subclass
    # ══════════════════════════════════════════════════════════════

    async def _send_text(self, channel_id: str, text: str) -> bool:
        """Send a text message. Return True on success."""
        raise NotImplementedError

    async def _send_file(self, channel_id: str, file_path: str, filename: str) -> bool:
        """Send a file attachment. Return True on success."""
        raise NotImplementedError

    def _extract_user_id(self, msg: Any) -> str:
        """Extract the user/sender id from the incoming message."""
        raise NotImplementedError

    def _extract_text(self, msg: Any) -> str:
        """Extract the plain text content from the incoming message."""
        raise NotImplementedError

    def _extract_channel_id(self, msg: Any) -> str:
        """Extract the channel id to reply to."""
        raise NotImplementedError

    # ══════════════════════════════════════════════════════════════
    # Shared logic — inherited as-is
    # ══════════════════════════════════════════════════════════════

    def _is_user_allowed(self, user_id: str) -> bool:
        """Check if a user is on the whitelist (empty = allow all)."""
        if not self._allowed_user_ids:
            return True
        return user_id in self._allowed_user_ids

    async def handle_message(self, msg: Any) -> None:
        """Process one incoming message through the shared pipeline."""
        user_id = self._extract_user_id(msg)

        if not self._is_user_allowed(user_id):
            logger.info("Blocked user %s (not in whitelist)", user_id)
            return

        raw = self._extract_text(msg)
        if not raw:
            return

        # Strip mentions/pings
        clean = _MENTION_RE.sub("", raw).strip()
        if not clean:
            return

        session_id = f"{self._transport_name.lower()}:{user_id}"
        channel_id = self._extract_channel_id(msg)
        pending_files: list = []

        from core.config import config

        async def _on_progress(event: dict) -> None:
            """Forward tool-call progress to the transport (opt-in via config)."""
            if not config.show_tool_calls:
                return
            if event.get("type") == "tool_call":
                name = event.get("name", "?")
                args = event.get("args", {})
                arg_str = " ".join(f"{k}={v}" for k, v in args.items())
                if len(arg_str) > 80:
                    arg_str = arg_str[:77] + "..."
                await self._send_text(
                    channel_id,
                    f"⚙️ `{name}` {arg_str}".strip(),
                )

        try:
            # P4d — intercept /goal commands before Router
            if self._command_handler is not None:
                cmd_reply = self._command_handler.dispatch(clean)
                if cmd_reply is not None:
                    reply = cmd_reply
                else:
                    reply = await self._router.process(
                        clean, session_id=session_id, on_progress=_on_progress,
                    )
            else:
                reply = await self._router.process(
                    clean, session_id=session_id, on_progress=_on_progress,
                )
            pending_files = self._router.pop_pending_files(session_id)
        except Exception as exc:
            logger.exception("Router error for %s message", self._transport_name)
            reply = f"❌ Sorry, I hit an error: {exc}"

        if pending_files:
            await self._send_text(channel_id, reply)
            for pf in pending_files:
                await self._send_file(channel_id, pf.file_path, pf.filename)
        else:
            await self._send_text(channel_id, reply)
