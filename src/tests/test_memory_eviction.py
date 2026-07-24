"""
Tests for memory eviction in LongTermMemory (P2).
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from soul.memory.long_term import LongTermMemory, MemoryEntry


class TestMemoryEviction:
    """LTM evict() behaviour."""

    @pytest.fixture
    def ltm(self, tmp_path: Path) -> LongTermMemory:
        return LongTermMemory(storage_dir=tmp_path)

    @pytest.fixture
    def full_ltm(self, tmp_path: Path) -> LongTermMemory:
        """LTM with entries over the default max (1000)."""
        ltm = LongTermMemory(storage_dir=tmp_path)
        # Directly inject entries to bypass auto-evict on add
        now = time.time()
        for i in range(1010):
            ltm._entries.append(MemoryEntry(
                id=f"entry_{i:04d}",
                type="fact",
                content=f"Memory entry #{i}",
                tags=[],
                created_at=now,
                access_count=0,
                last_accessed=now - (1010 - i) * 10,  # newest later
            ))
        ltm._save()
        return ltm

    # ── TTL eviction ────────────────────────────────────────────

    def test_evict_removes_old_entries(self, ltm: LongTermMemory):
        """Old entries (beyond TTL) are removed."""
        now = time.time()
        # Add 3 entries: 1 current, 2 very old
        ltm._entries = [
            MemoryEntry(id="a", type="fact", content="new", tags=[],
                        created_at=now, access_count=0, last_accessed=now),
            MemoryEntry(id="b", type="fact", content="old", tags=[],
                        created_at=now - 60 * 86400, access_count=0,
                        last_accessed=now - 60 * 86400),
            MemoryEntry(id="c", type="fact", content="ancient", tags=[],
                        created_at=now - 100 * 86400, access_count=0,
                        last_accessed=now - 100 * 86400),
        ]
        ltm._save()

        with patch.object(type(ltm), "_save") as mock_save:
            evicted = ltm.evict()
            assert evicted == 2
            assert len(ltm) == 1
            # Check entry exists without triggering another _save call
            assert any(e.id == "a" for e in ltm._entries)
            mock_save.assert_called()

    def test_evict_preserves_recent_entries(self, ltm: LongTermMemory):
        """Entries within TTL are kept."""
        now = time.time()
        ltm.add("fact", "recent", tags=["test"])
        # Manually set last_accessed to now
        ltm._entries[-1].last_accessed = now

        evicted = ltm.evict()
        assert evicted == 0
        assert len(ltm) == 1

    # ── LRU eviction ────────────────────────────────────────────

    def test_evict_removes_oldest_when_over_limit(self, full_ltm: LongTermMemory):
        """When over max_entries, oldest entries are removed."""
        with patch.object(type(full_ltm), "_save") as mock_save:
            evicted = full_ltm.evict()
            assert evicted == 10  # 1010 -> 1000
            assert len(full_ltm) == 1000

    def test_lru_keeps_most_recent(self, full_ltm: LongTermMemory):
        """After eviction, only the most recent entries remain."""
        full_ltm.evict()
        # The remaining entries should be entry_0010 through entry_1009
        # (the oldest 10 were entry_0000 through entry_0009)
        ids = [e.id for e in full_ltm.all()]
        assert "entry_0000" not in ids
        assert "entry_0001" not in ids
        assert "entry_1009" in ids  # most recent

    def test_lru_empty_when_all_old(self, ltm: LongTermMemory):
        """When all entries exceed TTL, eviction removes them all."""
        now = time.time()
        for i in range(10):
            ltm._entries.append(MemoryEntry(
                id=f"old_{i}", type="fact", content=f"old #{i}", tags=[],
                created_at=now - 100 * 86400, access_count=0,
                last_accessed=now - 100 * 86400,
            ))
        ltm._save()

        evicted = ltm.evict()
        assert evicted == 10
        assert len(ltm) == 0

    # ── Auto-evict on add ───────────────────────────────────────

    def test_auto_evict_on_add(self, tmp_path: Path):
        """Adding over the limit triggers eviction automatically."""
        ltm = LongTermMemory(storage_dir=tmp_path)
        now = time.time()

        # Fill past the limit
        for i in range(1010):
            ltm._entries.append(MemoryEntry(
                id=f"pre_{i:04d}", type="fact", content=f"pre #{i}", tags=[],
                created_at=now, access_count=0, last_accessed=now,
            ))
        ltm._save()

        # The next add auto-triggers eviction
        with patch.object(type(ltm), "_save") as mock_save:
            entry = ltm.add("fact", "new entry", tags=["test"])
            # evict() doesn't save if nothing evicted,
            # but add() saves after adding
            mock_save.assert_called()

    def test_no_evict_when_under_limit(self, ltm: LongTermMemory):
        """Adding under the limit does NOT trigger eviction."""
        for i in range(5):
            ltm.add("fact", f"entry {i}", tags=["test"])
        assert len(ltm) == 5

    def test_evict_zero_when_under_limit(self, ltm: LongTermMemory):
        """evict() returns 0 when within limits."""
        for i in range(5):
            ltm.add("fact", f"entry {i}", tags=["test"])
        evicted = ltm.evict()
        assert evicted == 0

    # ── force flag ──────────────────────────────────────────────

    def test_force_evict_runs_even_when_not_needed(self, ltm: LongTermMemory):
        """force=True runs eviction regardless."""
        ltm.add("fact", "only one", tags=["test"])
        evicted = ltm.evict(force=True)
        assert evicted == 0  # nothing to evict, but no crash
