"""
TransportAdapter — abstract base for all transport channels.

Shared logic lives here:
  - user whitelist (allowed_user_ids)
  - session_id generation
  - mention/ping stripping
  - router.process() dispatch
  - pending file delivery
  - long-message splitting (Discord 2000-char limit)

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

from core.confirmation import ConfirmationStore

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)

# Pattern to strip @mentions and role pings
_MENTION_RE = re.compile(r"<@!\d+>|<@\d+>|<@&\d+>")

# Platform message length limits
DISCORD_MAX_LEN = 2000
TELEGRAM_MAX_LEN = 4096


# ── Long-message splitter ──────────────────────────────────────────────

def split_long_message(text: str, max_len: int = DISCORD_MAX_LEN) -> list[str]:
    """Split *text* into chunks ≤ *max_len*, aware of code blocks and line boundaries.

    Strategy (tried in order):
    1. Split on paragraph boundary (``\\n\\n``)
    2. Split on line boundary (``\\n``)
    3. Split on word boundary (space)
    4. Hard split at *max_len*

    Code blocks: if a chunk contains an unclosed ``` fence, the fence is
    closed at the end of the chunk and reopened at the start of the next,
    so Markdown rendering stays intact.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Find the best split point (search backwards from max_len)
        split_at = remaining[:max_len].rfind('\n\n')
        if split_at == -1:
            split_at = remaining[:max_len].rfind('\n')
        if split_at == -1:
            split_at = remaining[:max_len].rfind(' ')
        if split_at == -1 or split_at < max_len // 2:
            split_at = max_len

        first = remaining[:split_at].rstrip()
        remaining = remaining[split_at:].lstrip()

        # Code-block fence balancing: if we have an unclosed ``` in *first*,
        # close it here and reopen in *remaining*.
        fence_count = first.count('```')
        if fence_count % 2 == 1:
            first += '\n```'
            remaining = '```\n' + remaining

        chunks.append(first)

    return chunks


# ── Abstract base for transports ───────────────────────────────────────

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
        # ── Confirmation bridge ───────────────────────────────────────
        self._confirm_store: ConfirmationStore | None = None
        if hasattr(router, 'get_confirm_store'):
            store = router.get_confirm_store()
            if isinstance(store, ConfirmationStore):
                self._confirm_store = store

    # ═══════════════════════════════════════════════════════════════════
    # Primitives — override in subclass
    # ═══════════════════════════════════════════════════════════════════

    async def _send_text(self, channel_id: str, text: str) -> bool:
        """Send a text message. Return True on success."""
        raise NotImplementedError

    async def _send_progress(self, channel_id: str, text: str) -> str | None:
        """Send a progress message. Returns message_id for later edit/delete."""
        await self._send_text(channel_id, text)
        return None  # default: no tracking (terminal, telegram)

    async def _edit_progress(self, channel_id: str, msg_id: str, text: str) -> None:
        """Edit an existing progress message. Default no-op."""

    async def _delete_progress(self, channel_id: str, msg_id: str) -> None:
        """Delete a progress message. Default no-op."""

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

    # ═══════════════════════════════════════════════════════════════════
    # Shared logic — inherited as-is
    # ═══════════════════════════════════════════════════════════════════

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

        # ── Confirmation reply check ───────────────────────────────────
        confirm_store = getattr(self, '_confirm_store', None)
        if confirm_store and confirm_store.has_pending(session_id):
            approval = confirm_store.is_approval(clean)
            if approval is not None:
                confirm_store.resolve(session_id, approval)
                if approval:
                    await self._send_text(channel_id, "✅ 已確認，執行中…")
                else:
                    await self._send_text(channel_id, "❌ 已取消。")
                return

        from core.config import config

        _MAX_PROGRESS_MSGS = 8
        _progress_msg_ids: list[str] = []  # rolling window of progress messages

        async def _on_progress(event: dict) -> None:
            """Forward tool-call progress (up to 8 concurrent messages, rolling)."""
            nonlocal _progress_msg_ids
            if not config.show_tool_calls:
                return
            if event.get("type") == "tool_call":
                name = event.get("name", "?")
                args = event.get("args", {})
                arg_str = " ".join(f"{k}={v}" for k, v in args.items())
                if len(arg_str) > 80:
                    arg_str = arg_str[:77] + "..."
                
                # Tool-specific emoji mapping
                emoji_map = {
                    "execute_command": "🛠️",
                    "read_file": "📝",
                    "write_file": "📝",
                    "web_search": "🌐",
                    "memory_search": "🧠",
                    "add_schedule": "⏰",
                    "remove_schedule": "⏰",
                    "list_schedules": "⏰",
                    "pause_schedule": "⏰",
                    "resume_schedule": "⏰",
                    "background_task": "⚙️",
                    "send_file": "📁",
                    "send_task_message": "💬",
                    "check_task_messages": "💬",
                    "set_model": "🤖",
                    "skill_tool": "🌟",
                    "query_task": "🔍",
                    "cancel_task": "🚫",
                    "list_tasks": "📋",
                    "spawn_child": "🐣",
                    "spawn_tool": "🛠️",
                }
                emoji = emoji_map.get(name, "🔬")
                text = f"{emoji} `{name}` {arg_str}".strip()

                # Rolling window: if at max, delete oldest before sending new
                if len(_progress_msg_ids) >= _MAX_PROGRESS_MSGS:
                    oldest = _progress_msg_ids.pop(0)
                    try:
                        await self._delete_progress(channel_id, oldest)
                    except Exception:
                        pass

                msg_id = await self._send_progress(channel_id, text)
                if msg_id:
                    _progress_msg_ids.append(msg_id)

        async def _cleanup_progress() -> None:
            """Delete all progress messages after final response."""
            nonlocal _progress_msg_ids
            for mid in _progress_msg_ids:
                try:
                    await self._delete_progress(channel_id, mid)
                except Exception:
                    pass
            _progress_msg_ids.clear()

        try:
            # ── Wire confirmation bridge ─────────────────────────────
            if hasattr(self._router, 'set_current_channel'):
                self._router.set_current_channel(channel_id)
            if confirm_store and not confirm_store.has_send_fn:
                confirm_store.set_send_fn(
                    lambda ch_id, text: self._send_text(ch_id, text)
                )

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
            # Delete progress message(s) before sending final reply
            await _cleanup_progress()
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
