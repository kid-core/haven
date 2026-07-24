"""User confirmation handling for tools that require approval.

Bridges the ReAct loop (inside Router) with the transport layer,
allowing the agent to pause and ask the user for confirmation
before executing sensitive tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

DEFAULT_CONFIRM_TIMEOUT = 120.0

_YES_WORDS = frozenset({
    "yes", "y", "confirm", "approve", "ok", "okay", "sure", "go",
    "執行", "是", "好", "可以", "確認", "批准", "proceed",
})
_NO_WORDS = frozenset({
    "no", "n", "cancel", "deny", "否", "不", "取消", "拒絕", "stop",
})


class ConfirmationStore:
    """Manages pending confirmation requests across sessions."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future] = {}
        self._details: dict[str, dict] = {}
        self._send_fn: Callable[[str, str], Awaitable[None]] | None = None
        self._timeout = DEFAULT_CONFIRM_TIMEOUT

    def set_send_fn(self, fn: Callable[[str, str], Awaitable[None]]) -> None:
        self._send_fn = fn

    @property
    def has_send_fn(self) -> bool:
        return self._send_fn is not None

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = value

    async def request(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict,
        channel_id: str,
    ) -> bool:
        """Request user confirmation. Returns True if approved, False otherwise."""
        args_str = json.dumps(arguments, indent=2, ensure_ascii=False)
        if len(args_str) > 800:
            args_str = args_str[:800] + "\n..."

        msg = (
            f"⚠️ **確認請求**\n"
            f"工具: `{tool_name}`\n"
            f"```json\n{args_str}\n```\n"
            f"回覆 `yes` 確認執行，`no` 取消。（{int(self._timeout)}秒內有效）"
        )

        if self._send_fn:
            try:
                await self._send_fn(channel_id, msg)
            except Exception as exc:
                logger.warning("Failed to send confirmation message: %s", exc)

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[session_id] = future
        self._details[session_id] = {"tool_name": tool_name, "arguments": arguments}

        try:
            result = await asyncio.wait_for(future, timeout=self._timeout)
            return result
        except asyncio.TimeoutError:
            logger.info("Confirmation timed out for session %s", session_id)
            if self._send_fn:
                try:
                    await self._send_fn(channel_id, "⏰ 確認已超時，已自動取消。")
                except Exception:
                    pass
            return False
        finally:
            self._pending.pop(session_id, None)
            self._details.pop(session_id, None)

    def has_pending(self, session_id: str) -> bool:
        return session_id in self._pending

    def resolve(self, session_id: str, approved: bool) -> bool:
        """Resolve a pending confirmation. Returns True if found."""
        future = self._pending.pop(session_id, None)
        self._details.pop(session_id, None)
        if future and not future.done():
            future.set_result(approved)
            return True
        return False

    @staticmethod
    def is_approval(text: str) -> bool | None:
        """Parse a message as yes/no/None (not a confirmation reply)."""
        clean = text.strip().lower()
        if clean in _YES_WORDS:
            return True
        if clean in _NO_WORDS:
            return False
        return None
