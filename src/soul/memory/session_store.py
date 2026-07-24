"""JSON file-backed session-history persistence (migrated from soul.memory)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.paths import session_dir

logger = logging.getLogger(__name__)

SESSION_DIR = session_dir()


class SessionStore:
    """Persist conversation history to JSON files.

    Enforces tool-call pairing to prevent orphaned ``role: "tool"``
    messages after trimming — DeepSeek rejects such arrays with HTTP 400.
    """

    def __init__(self, session_dir: Path = SESSION_DIR, max_messages: int = 50):
        self._dir = session_dir
        self._max = max_messages
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def session_dir(self) -> Path:
        return self._dir

    # ── Orphan tool guard ────────────────────────────────────────────

    @staticmethod
    def _validate_tool_pairing(messages: list[dict]) -> list[dict]:
        """Remove tool messages that lack a preceding assistant with
        a matching ``tool_calls`` entry.

        This prevents DeepSeek HTTP 400 errors caused by trimming
        ``assistant(tool_calls)`` while keeping its trailing tool results.
        """
        seen_ids: set[str] = set()
        clean: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            if role == "assistant" and "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id")
                    if tc_id:
                        seen_ids.add(tc_id)
                clean.append(msg)
            elif role == "tool":
                if msg.get("tool_call_id", "") in seen_ids:
                    clean.append(msg)
                # else: silently drop orphaned tool message
            else:
                clean.append(msg)
        return clean

    # ── Public API ───────────────────────────────────────────────────

    def load(self, session_id: str) -> list[dict]:
        path = self._dir / f"{session_id}.json"
        if not path.exists():
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, list):
                logger.warning("Session file %s is not a list; returning []", path)
                return []
            return self._validate_tool_pairing(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load session file %s: %s", path, exc)
            return []

    def save(self, session_id: str, messages: list[dict]) -> None:
        path = self._dir / f"{session_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Strip orphans before trimming so tool pairing is always intact
        clean = self._validate_tool_pairing(messages)
        if self._max == 0:
            trimmed = []
        elif self._max > 0 and len(clean) > self._max:
            trimmed = clean[-self._max:]
        else:
            trimmed = clean
        with open(path, "w") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
