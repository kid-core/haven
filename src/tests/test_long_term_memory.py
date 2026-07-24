"""
Tests for soul/memory/long_term.py — LongTermMemory persistence, CRUD, search.

Unit tests: uses tmp_path for isolation, verifies data survives store reload.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soul.memory.long_term import LongTermMemory, MemoryEntry


class TestMemoryEntry:
    """MemoryEntry dataclass — basic structure."""

    def test_touch_increments_access_count(self):
        entry = MemoryEntry(
            id="abc123",
            type="fact",
            content="test",
            created_at=100.0,
        )
        assert entry.access_count == 0
        entry.touch()
        assert entry.access_count == 1
        assert entry.last_accessed > 0

    def test_touch_updates_timestamp(self):
        entry = MemoryEntry(
            id="abc123",
            type="fact",
            content="test",
            created_at=100.0,
        )
        old = entry.last_accessed
        entry.touch()
        assert entry.last_accessed >= old

    def test_default_tags_empty(self):
        entry = MemoryEntry(id="abc", type="fact", content="x", created_at=0)
        assert entry.tags == []


class TestLTM:
    """LongTermMemory — CRUD and persistence."""

    # ── CRUD ────────────────────────────────────────────────────────

    def test_add_returns_entry(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        entry = ltm.add("fact", "Cris likes Python")
        assert entry.id is not None
        assert len(entry.id) == 12
        assert entry.type == "fact"
        assert entry.content == "Cris likes Python"
        assert entry.created_at > 0

    def test_add_with_tags(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        entry = ltm.add("preference", "Dark mode", tags=["ui", "theme"])
        assert "ui" in entry.tags
        assert "theme" in entry.tags

    def test_get_existing_entry(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        e = ltm.add("fact", "something")
        retrieved = ltm.get(e.id)
        assert retrieved is not None
        assert retrieved.content == "something"

    def test_get_nonexistent_returns_none(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        assert ltm.get("nonexistent") is None

    def test_get_updates_access_count(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        e = ltm.add("fact", "data")
        assert e.access_count == 0
        ltm.get(e.id)
        assert ltm.get(e.id).access_count == 2  # each get touches

    def test_remove_existing(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        e = ltm.add("fact", "delete me")
        assert len(ltm) == 1
        removed = ltm.remove(e.id)
        assert removed is True
        assert len(ltm) == 0

    def test_remove_nonexistent(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        assert ltm.remove("nonexistent") is False

    def test_all_returns_all_entries(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        ltm.add("fact", "a")
        ltm.add("preference", "b")
        assert len(ltm.all()) == 2

    def test_len(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        assert len(ltm) == 0
        ltm.add("fact", "x")
        assert len(ltm) == 1

    # ── Persistence ─────────────────────────────────────────────────

    def test_survives_store_reload(self, tmp_path: Path):
        ltm1 = LongTermMemory(storage_dir=tmp_path)
        e = ltm1.add("fact", "persistent memory")

        ltm2 = LongTermMemory(storage_dir=tmp_path)
        assert len(ltm2) == 1
        retrieved = ltm2.get(e.id)
        assert retrieved is not None
        assert retrieved.content == "persistent memory"
        assert retrieved.type == "fact"

    def test_persists_multiple_entries(self, tmp_path: Path):
        ltm1 = LongTermMemory(storage_dir=tmp_path)
        ids = []
        for i in range(5):
            e = ltm1.add("fact", f"entry {i}")
            ids.append(e.id)

        ltm2 = LongTermMemory(storage_dir=tmp_path)
        assert len(ltm2) == 5
        for i, eid in enumerate(ids):
            assert ltm2.get(eid).content == f"entry {i}"

    def test_persists_tags(self, tmp_path: Path):
        ltm1 = LongTermMemory(storage_dir=tmp_path)
        e = ltm1.add("preference", "dark mode", tags=["ui", "theme"])

        ltm2 = LongTermMemory(storage_dir=tmp_path)
        retrieved = ltm2.get(e.id)
        assert retrieved.tags == ["ui", "theme"]

    def test_persists_access_count(self, tmp_path: Path):
        ltm1 = LongTermMemory(storage_dir=tmp_path)
        e = ltm1.add("fact", "popular")
        ltm1.get(e.id)  # access once

        ltm2 = LongTermMemory(storage_dir=tmp_path)
        retrieved = ltm2.get(e.id)
        assert retrieved.access_count >= 1

    def test_remove_persists(self, tmp_path: Path):
        ltm1 = LongTermMemory(storage_dir=tmp_path)
        e1 = ltm1.add("fact", "keep me")
        e2 = ltm1.add("fact", "remove me")
        ltm1.remove(e2.id)

        ltm2 = LongTermMemory(storage_dir=tmp_path)
        assert len(ltm2) == 1
        assert ltm2.get(e1.id) is not None
        assert ltm2.get(e2.id) is None

    # ── Corrupted file handling ─────────────────────────────────────

    def test_corrupted_file_loads_empty(self, tmp_path: Path):
        mem_file = tmp_path / "memory.json"
        mem_file.write_text("{invalid json", encoding="utf-8")
        ltm = LongTermMemory(storage_dir=tmp_path)
        assert len(ltm) == 0

    def test_corrupted_file_does_not_block_writes(self, tmp_path: Path):
        mem_file = tmp_path / "memory.json"
        mem_file.write_text("not json", encoding="utf-8")
        ltm = LongTermMemory(storage_dir=tmp_path)
        e = ltm.add("fact", "after corruption")
        assert e.content == "after corruption"

    def test_missing_file_starts_empty(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        assert len(ltm) == 0

    def test_empty_json_file_loads_empty(self, tmp_path: Path):
        mem_file = tmp_path / "memory.json"
        mem_file.write_text("", encoding="utf-8")
        ltm = LongTermMemory(storage_dir=tmp_path)
        assert len(ltm) == 0

    # ── Queries ─────────────────────────────────────────────────────

    def test_search_by_content(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        ltm.add("fact", "Cris likes Python")
        ltm.add("fact", "Cris dislikes Java")
        ltm.add("fact", "Weather is nice")

        results = ltm.search("Python")
        assert len(results) == 1
        assert "Python" in results[0].content

    def test_search_multiple_matches(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        ltm.add("fact", "Python is great")
        ltm.add("preference", "Python over JavaScript")
        ltm.add("fact", "Rust is fast")

        results = ltm.search("Python")
        assert len(results) == 2

    def test_search_no_match(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        ltm.add("fact", "hello world")
        results = ltm.search("nonexistent")
        assert len(results) == 0

    def test_search_with_type_filter(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        ltm.add("fact", "Python is fun")
        ltm.add("preference", "Python over Java")

        results = ltm.search("Python", type_filter="fact")
        assert len(results) == 1
        assert results[0].type == "fact"

    def test_search_with_tag_filter(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        ltm.add("fact", "Python is fun", tags=["coding"])
        ltm.add("fact", "Swimming is healthy", tags=["sport"])

        results = ltm.search("Python", tag_filter="coding")
        assert len(results) == 1

    def test_search_case_insensitive(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        ltm.add("fact", "python is great")
        results = ltm.search("Python")
        assert len(results) == 1

    def test_search_limit(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        for i in range(5):
            ltm.add("fact", f"Python item {i}")
        results = ltm.search("Python", limit=2)
        assert len(results) == 2

    def test_get_recent(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        import time
        e1 = ltm.add("fact", "old")
        time.sleep(0.01)
        e2 = ltm.add("fact", "new")

        recent = ltm.get_recent(limit=5)
        assert recent[0].id == e2.id
        assert recent[1].id == e1.id

    def test_get_important(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        pop = ltm.add("fact", "popular")
        ltm.add("fact", "unpopular")
        ltm.get(pop.id)
        ltm.get(pop.id)
        ltm.get(pop.id)

        important = ltm.get_important(limit=5)
        assert important[0].id == pop.id
        assert important[0].access_count == 3

    def test_get_by_tag(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        ltm.add("fact", "a", tags=["coding"])
        ltm.add("fact", "b", tags=["sport"])
        ltm.add("fact", "c", tags=["coding"])

        tagged = ltm.get_by_tag("coding")
        assert len(tagged) == 2

    def test_get_by_tag_with_limit(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        for i in range(5):
            ltm.add("fact", f"item {i}", tags=["common"])
        tagged = ltm.get_by_tag("common", limit=3)
        assert len(tagged) == 3

    # ── Entry types ─────────────────────────────────────────────────

    def test_all_entry_types(self, tmp_path: Path):
        ltm = LongTermMemory(storage_dir=tmp_path)
        for t in ["fact", "preference", "skill", "session_summary"]:
            entry = ltm.add(t, f"a {t} memory", tags=[t])
            assert entry.type == t

    def test_reload_preserves_all_types(self, tmp_path: Path):
        ltm1 = LongTermMemory(storage_dir=tmp_path)
        for t in ["fact", "preference", "skill", "session_summary"]:
            ltm1.add(t, f"type: {t}")

        ltm2 = LongTermMemory(storage_dir=tmp_path)
        all_entries = ltm2.all()
        types = {e.type for e in all_entries}
        assert types == {"fact", "preference", "skill", "session_summary"}
