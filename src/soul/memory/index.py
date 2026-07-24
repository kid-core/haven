"""Full-text search index for long-term memory (Phase 2a).

Simple keyword-based scoring.  Phase 2b will add vector/embedding search.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soul.memory.long_term import LongTermMemory, MemoryEntry


class MemoryIndex:
    """Full-text search wrapper around LongTermMemory.

    Provides more sophisticated query parsing than the built-in
    ``LongTermMemory.search()``, including phrase matching and
    multi-keyword scoring.

    Usage::

        index = MemoryIndex(ltm)
        results = index.query("Python preference", limit=5)
    """

    def __init__(self, memory: LongTermMemory) -> None:
        self._memory = memory

    def query(
        self,
        query: str,
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[MemoryEntry]:
        """Search with multi-keyword relevance scoring.

        Split *query* into words, score each entry by how many
        unique keywords match its content + tags.
        """
        # Tokenise query into lowercase keywords
        keywords = self._tokenize(query)
        if not keywords:
            return self._memory.get_recent(limit)

        scored: list[tuple[int, MemoryEntry]] = []

        for entry in self._memory.all():
            if type_filter and entry.type != type_filter:
                continue

            target = (entry.content + " " + " ".join(entry.tags)).lower()
            hits = sum(1 for kw in keywords if kw in target)
            if hits > 0:
                scored.append((hits, entry))

        # Sort by relevance (hits), then by access_count (popularity)
        scored.sort(key=lambda x: (x[0], x[1].access_count), reverse=True)

        results = [e for _, e in scored[:limit]]
        for e in results:
            e.touch()
        return results

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Split text into meaningful lowercase keywords."""
        # Remove punctuation, split on whitespace
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())
        tokens = cleaned.split()
        # Filter out very short tokens and duplicates
        seen: set[str] = set()
        result: list[str] = []
        for t in tokens:
            if len(t) >= 2 and t not in seen:
                result.append(t)
                seen.add(t)
        return result
