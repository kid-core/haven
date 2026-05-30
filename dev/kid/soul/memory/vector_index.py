"""Vector search for long-term memory — ollama embedding + cosine similarity (Phase 2b).

Uses nomic-embed-text via ollama for semantic search.
Graceful fallback to keyword-only when ollama is unavailable.
"""

from __future__ import annotations

import logging
import math
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soul.memory.long_term import MemoryEntry

logger = logging.getLogger(__name__)


class VectorIndex:
    """Semantic search wrapper for long-term memory.

    Uses ollama's nomic-embed-text for embeddings, falls back to
    keyword matching when ollama is unavailable.

    Usage::

        vix = VectorIndex(memory=ltm, keyword_index=MemoryIndex(ltm))
        results = await vix.search("Cris prefers Python")
        # Returns hybrid-ranked results (semantic + keyword)

    Enabled when ``HAVEN_USE_VECTOR=true`` env var is set, or
    when ollama is detected at ``OLLAMA_BASE_URL`` (defaults to
    http://localhost:11434).
    """

    OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    EMBED_MODEL = os.getenv("HAVEN_EMBED_MODEL", "nomic-embed-text:latest")

    def __init__(
        self,
        memory: LongTermMemory,
        keyword_index: MemoryIndex | None = None,
    ) -> None:

        self._memory: LongTermMemory = memory
        self._keyword = keyword_index
        self._available: bool | None = None  # lazy detection

        # We also support embedding caching (Phase 2a → 2b migration)
        # When an entry is added, we embed it; we store embeddings
        # externally so we don't pollute the MemoryEntry dataclass.
        self._embeddings: dict[str, list[float]] = {}
        self._load_embeddings()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 10,
        type_filter: str | None = None,
    ) -> list[MemoryEntry]:
        """Hybrid search: semantic (cosine) + keyword, merged and ranked.

        Falls back to keyword-only if ollama isn't available.
        """
        if await self._is_available():
            return await self._hybrid_search(query, limit, type_filter)

        logger.debug("Vector search unavailable, using keyword fallback")
        if self._keyword:
            return self._keyword.query(query, limit, type_filter)
        return self._memory.search(query, limit, type_filter)

    async def index_entry(self, entry: MemoryEntry) -> None:
        """Compute and cache embedding for a single entry."""
        if not await self._is_available():
            return
        embedding = await self._embed(entry.content)
        if embedding:
            self._embeddings[entry.id] = embedding
            self._save_embeddings()

    async def index_all(self) -> int:
        """Compute embeddings for all entries without one. Returns count indexed."""
        if not await self._is_available():
            return 0
        count = 0
        for entry in self._memory.all():
            if entry.id not in self._embeddings:
                emb = await self._embed(entry.content)
                if emb:
                    self._embeddings[entry.id] = emb
                    count += 1
        if count:
            self._save_embeddings()
        return count

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _is_available(self) -> bool:
        """Lazy-detect ollama availability."""
        if self._available is not None:
            return self._available
        if os.getenv("HAVEN_USE_VECTOR", "").lower() in ("true", "1", "yes"):
            # User explicitly enabled, try to connect
            self._available = await self._ping()
        else:
            # Auto-detect
            self._available = await self._ping()
        logger.info("Vector search: %s", "enabled" if self._available else "unavailable")
        return self._available

    async def _ping(self) -> bool:
        """Check if ollama is reachable."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.OLLAMA_URL}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def _embed(self, text: str) -> list[float] | None:
        """Get embedding vector for text from ollama."""
        if not text.strip():
            return None
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.OLLAMA_URL}/api/embeddings",
                    json={"model": self.EMBED_MODEL, "prompt": text[:1000]},
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()
                return data.get("embedding")
        except Exception as exc:
            logger.debug("Embedding failed: %s", exc)
            self._available = False
            return None

    async def _hybrid_search(
        self, query: str, limit: int, type_filter: str | None,
    ) -> list[MemoryEntry]:
        """Combine semantic + keyword results."""
        # Get query embedding
        query_emb = await self._embed(query)
        if not query_emb:
            return self._memory.search(query, limit, type_filter)

        # Score all entries
        candidates = self._memory.all()
        if type_filter:
            candidates = [e for e in candidates if e.type == type_filter]

        scored: list[tuple[float, MemoryEntry]] = []
        for entry in candidates:
            entry_emb = self._embeddings.get(entry.id)
            if entry_emb is None:
                # Lazy-embed on first search
                entry_emb = await self._embed(entry.content)
                if entry_emb:
                    self._embeddings[entry.id] = entry_emb

            semantic = self._cosine(query_emb, entry_emb) if entry_emb else 0.0

            # Keyword bonus: 0.2 per keyword match
            kw_score = 0.0
            if self._keyword:
                q_tokens = self._keyword._tokenize(query)
                target = (entry.content + " " + " ".join(entry.tags)).lower()
                kw_score = 0.2 * sum(1 for t in q_tokens if t in target)

            combined = semantic + kw_score
            if combined > 0.01:  # minimum threshold
                scored.append((combined, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [e for _, e in scored[:limit]]
        for e in results:
            e.touch()
        if results:
            self._save_embeddings()
        return results

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two vectors."""
        if len(a) != len(b) or not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    # ------------------------------------------------------------------
    # Embedding cache persistence
    # ------------------------------------------------------------------

    @property
    def _cache_path(self) -> Path:
        from soul.memory.long_term import DEFAULT_MEMORY_DIR
        return DEFAULT_MEMORY_DIR / "embeddings.json"

    def _load_embeddings(self) -> None:
        import contextlib
        import json
        path = self._cache_path
        if not path.exists():
            return
        with contextlib.suppress(json.JSONDecodeError, OSError):
            self._embeddings = json.loads(path.read_text())

    def _save_embeddings(self) -> None:
        import json
        self._cache_path.write_text(json.dumps(self._embeddings))


# ---------------------------------------------------------------------------
# Re-export compatible type hints for TYPE_CHECKING
# ---------------------------------------------------------------------------
if TYPE_CHECKING:
    from pathlib import Path  # noqa: F811

    from soul.memory.index import MemoryIndex  # noqa: F811
    from soul.memory.long_term import LongTermMemory  # noqa: F811
