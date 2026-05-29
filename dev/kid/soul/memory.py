"""JSON file-backed session-history persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)

SESSION_DIR = Path(__file__).resolve().parent.parent / "sessions"


class SessionStore:
    """Persist conversation history to JSON files."""

    def __init__(self, session_dir: Path = SESSION_DIR, max_messages: int = 50):
        self._dir = session_dir
        self._max = max_messages
        self._dir.mkdir(parents=True, exist_ok=True)

    def load(self, session_id: str) -> list[dict]:
        """Retrieve message history for *session_id*.

        Returns an empty list if the file is missing, corrupt, or
        contains non-list JSON (e.g. a plain object).
        """
        path = self._dir / f"{session_id}.json"
        if not path.exists():
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, list):
                logger.warning("Session file %s is not a list; returning []", path)
                return []
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load session file %s: %s", path, exc)
            return []

    def save(self, session_id: str, messages: list[dict]) -> None:
        """Persist messages, trimming oldest beyond *max_messages*."""
        path = self._dir / f"{session_id}.json"
        # Ensure parent directory exists (session IDs with slashes)
        path.parent.mkdir(parents=True, exist_ok=True)

        if self._max <= 0:
            trimmed: list[dict] = []
        else:
            trimmed = messages[-self._max :] if len(messages) > self._max else messages

        with open(path, "w") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
