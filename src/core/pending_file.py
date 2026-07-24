"""
Pending-file store for cross-platform file delivery.

Stores file paths that tools have "sent", which the transport layer
(Discord, Telegram, etc.) picks up and delivers natively.

Usage::

    store = PendingFileStore()
    set_pending_file_store(store)
    store.add(session_id, PendingFile(file_path="/tmp/report.md", filename="report.md"))
    files = store.pop_all(session_id)   # [(path, name), ...]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_current_session: str = ""


def set_current_session(session_id: str) -> None:
    """Set the current session ID for tools that queue pending files."""
    global _current_session  # noqa: PLW0603
    _current_session = session_id


def current_session() -> str:
    """Return the current session ID."""
    return _current_session


@dataclass
class PendingFile:
    """A file queued for delivery to the user."""

    file_path: str
    """Absolute path on disk."""

    filename: str
    """Display name for the recipient."""


_module_store: PendingFileStore | None = None


class PendingFileStore:
    """Thread-safe (async) store of pending file deliveries, keyed by session."""

    def __init__(self) -> None:
        self._files: dict[str, list[PendingFile]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, session_id: str, file: PendingFile) -> None:
        """Queue *file* for *session_id*."""
        self._files.setdefault(session_id, []).append(file)

    def pop_all(self, session_id: str) -> list[PendingFile]:
        """Dequeue and return all pending files for *session_id*."""
        return self._files.pop(session_id, [])

    def has_pending(self, session_id: str) -> bool:
        """Check if *session_id* has pending files (peek, no dequeue)."""
        files = self._files.get(session_id)
        return bool(files)


# ------------------------------------------------------------------
# Module-level access (same pattern as task_manager, scheduler, etc.)
# ------------------------------------------------------------------


def set_pending_file_store(store: PendingFileStore) -> None:
    """Inject the store (called by Router on init)."""
    global _module_store  # noqa: PLW0603
    _module_store = store


def get_pending_file_store() -> PendingFileStore:
    """Return the active store (raises if not wired yet)."""
    if _module_store is None:
        raise RuntimeError("PendingFileStore not wired. Call set_pending_file_store() first.")
    return _module_store
