"""
Crash Journal — file-backed crash log for recovery after unexpected failures.

SRP: single-purpose module for crash persistence.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class CrashJournal:
    """File-backed crash log for recovery after unexpected failures."""

    DEFAULT_PATH: ClassVar[str] = "/tmp/haven_crash.json"

    def __init__(self, storage_path: str | None = None) -> None:
        self._path = Path(storage_path or self.DEFAULT_PATH)

    # -- helpers ----------------------------------------------------------

    def _read_all(self) -> list[dict[str, Any]]:
        """Return all entries from disk, or [] on missing / corrupt file."""
        if not self._path.exists():
            return []
        try:
            raw = self._path.read_text(encoding="utf-8")
            if not raw.strip():
                return []
            return json.loads(raw)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            logger.exception("CrashJournal: failed to read %s", self._path)
            return []

    def _write_all(self, entries: list[dict[str, Any]]) -> None:
        """Atomic write for crash safety."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    # -- public api -------------------------------------------------------

    def log(self, task_name: str, error: str, context: dict[str, Any] | None = None) -> str:
        """Append a crash entry; returns the generated crash id."""
        entry: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "task_name": task_name,
            "error": error,
            "context": context or {},
            "handled": False,
            "timestamp": time.time(),
        }
        entries = self._read_all()
        entries.append(entry)
        self._write_all(entries)
        return entry["id"]

    def read_pending(self) -> list[dict[str, Any]]:
        """Return all un-handled entries."""
        return [e for e in self._read_all() if not e.get("handled", False)]

    def mark_handled(self, crash_id: str) -> None:
        """Mark one entry as handled by its id."""
        entries = self._read_all()
        for entry in entries:
            if entry.get("id") == crash_id:
                entry["handled"] = True
                break
        self._write_all(entries)
