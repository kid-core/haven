"""Long-term memory — persistent storage for facts, preferences, and session summaries.

Phase 2a: JSON file-based, key-value with tags and access tracking.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_DIR = Path(__file__).resolve().parent.parent.parent / "long_term_memory"


@dataclass
class MemoryEntry:
    """A single piece of long-term memory."""

    id: str
    type: Literal["fact", "preference", "skill", "session_summary"]
    content: str
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0  # epoch timestamp
    access_count: int = 0
    last_accessed: float = 0.0

    def touch(self) -> None:
        """Mark this entry as accessed (increment counter + update timestamp)."""
        self.access_count += 1
        self.last_accessed = time.time()


class LongTermMemory:
    """Persistent long-term memory store backed by a single JSON file.

    Usage::

        ltm = LongTermMemory()
        ltm.add("fact", "Cris prefers Python over JavaScript", tags=["preference", "coding"])
        results = ltm.search("Python")
        relevant = ltm.get_recent(limit=10)

    Thread-safe for read operations; writes should be serialised externally.
    """

    def __init__(self, storage_dir: Path = DEFAULT_MEMORY_DIR):
        self._dir = storage_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "memory.json"
        self._entries: list[MemoryEntry] = []
        self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(
        self,
        type_: Literal["fact", "preference", "skill", "session_summary"],
        content: str,
        tags: list[str] | None = None,
    ) -> MemoryEntry:
        """Create and persist a new memory entry."""
        now = time.time()
        entry = MemoryEntry(
            id=uuid.uuid4().hex[:12],
            type=type_,
            content=content,
            tags=tags or [],
            created_at=now,
            access_count=0,
            last_accessed=now,
        )
        self._entries.append(entry)
        self._save()
        logger.debug("Memory added: %s → %r", entry.id, entry.content[:60])
        return entry

    def get(self, entry_id: str) -> MemoryEntry | None:
        """Retrieve a single entry by id."""
        for e in self._entries:
            if e.id == entry_id:
                e.touch()
                self._save()
                return e
        return None

    def remove(self, entry_id: str) -> bool:
        """Remove an entry by id. Returns True if found and removed."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != entry_id]
        if len(self._entries) < before:
            self._save()
            return True
        return False

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 10,
        type_filter: str | None = None,
        tag_filter: str | None = None,
    ) -> list[MemoryEntry]:
        """Simple case-insensitive full-text search over content and tags.

        Results are sorted by relevance (match count) then recency.
        """
        q = query.lower()
        scored: list[tuple[int, float, MemoryEntry]] = []

        for e in self._entries:
            if type_filter and e.type != type_filter:
                continue
            if tag_filter and tag_filter not in e.tags:
                continue

            score = e.content.lower().count(q)
            if score == 0:
                # Also check tags
                for tag in e.tags:
                    if q in tag.lower():
                        score = 1
                        break
            if score == 0:
                continue

            scored.append((score, e.last_accessed, e))

        # Sort: higher score first, then more recent
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

        results = [e for _, _, e in scored[:limit]]
        for e in results:
            e.touch()
        if results:
            self._save()
        return results

    def get_recent(self, limit: int = 10) -> list[MemoryEntry]:
        """Return the most recently created entries."""
        sorted_entries = sorted(self._entries, key=lambda e: e.created_at, reverse=True)
        return sorted_entries[:limit]

    def get_important(self, limit: int = 10) -> list[MemoryEntry]:
        """Return the most frequently accessed entries."""
        sorted_entries = sorted(self._entries, key=lambda e: e.access_count, reverse=True)
        return sorted_entries[:limit]

    def get_by_tag(self, tag: str, limit: int = 20) -> list[MemoryEntry]:
        """Return all entries with a given tag."""
        results = [e for e in self._entries if tag in e.tags]
        results.sort(key=lambda e: e.last_accessed, reverse=True)
        return results[:limit]

    def all(self) -> list[MemoryEntry]:
        """Return all entries (for admin/diagnostics)."""
        return list(self._entries)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load entries from disk."""
        if not self._path.exists():
            return
        try:
            with open(self._path) as f:
                data = json.load(f)
            if isinstance(data, list):
                self._entries = [
                    MemoryEntry(
                        id=e["id"],
                        type=e["type"],
                        content=e["content"],
                        tags=e.get("tags", []),
                        created_at=e.get("created_at", 0),
                        access_count=e.get("access_count", 0),
                        last_accessed=e.get("last_accessed", 0),
                    )
                    for e in data
                ]
            logger.info("Loaded %d long-term memories from %s", len(self._entries), self._path)
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning("Could not load long-term memory: %s", exc)

    def _save(self) -> None:
        """Persist all entries to disk."""
        data = [
            {
                "id": e.id,
                "type": e.type,
                "content": e.content,
                "tags": e.tags,
                "created_at": e.created_at,
                "access_count": e.access_count,
                "last_accessed": e.last_accessed,
            }
            for e in self._entries
        ]
        with open(self._path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def __len__(self) -> int:
        return len(self._entries)
