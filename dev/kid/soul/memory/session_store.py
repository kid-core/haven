"""JSON file-backed session-history persistence (migrated from soul.memory)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_DIR = Path(__file__).resolve().parent.parent.parent / "sessions"


class SessionStore:
    """Persist conversation history to JSON files."""

    def __init__(self, session_dir: Path = SESSION_DIR, max_messages: int = 50):
        self._dir = session_dir
        self._max = max_messages
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def session_dir(self) -> Path:
        return self._dir

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
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load session file %s: %s", path, exc)
            return []

    def save(self, session_id: str, messages: list[dict]) -> None:
        path = self._dir / f"{session_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._max == 0:
            trimmed = []
        elif self._max > 0 and len(messages) > self._max:
            trimmed = messages[-self._max:]
        else:
            trimmed = messages
        with open(path, "w") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
