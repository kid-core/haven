"""
Tests for learning/skill_store.py — SkillStore lifecycle.

Covers: create → approve → deprecate → remove, persistence,
context block rendering, usage tracking, and edge cases.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from learning.skill_store import (
    SkillChange,
    SkillState,
    SkillStore,
    StoredSkill,
)


class TestSkillDataTypes:
    """StoredSkill + SkillChange + SkillState basics."""

    def test_skill_state_values(self):
        assert SkillState.DRAFT == "draft"
        assert SkillState.ACTIVE == "active"
        assert SkillState.DEPRECATED == "deprecated"

    def test_stored_skill_default_fields(self):
        skill = StoredSkill(id="s1", name="test", description="desc", content="content")
        assert skill.state == SkillState.DRAFT
        assert skill.version == 1
        assert skill.usage_count == 0
        assert skill.success_count == 0
        assert skill.tags == []
        assert skill.history == []

    def test_success_rate_zero_when_unused(self):
        skill = StoredSkill(id="s1", name="test", description="desc", content="content")
        assert skill.success_rate == 0.0

    def test_success_rate_after_usage(self):
        skill = StoredSkill(
            id="s1", name="test", description="desc", content="content",
            usage_count=10, success_count=7,
        )
        assert skill.success_rate == 0.7

    def test_skill_change_dataclass(self):
        change = SkillChange(timestamp=100.0, action="created", detail="draft")
        assert change.timestamp == 100.0
        assert change.action == "created"

    def test_to_context_block(self):
        skill = StoredSkill(
            id="s1", name="short-replies",
            description="Keep it short",
            content="Respond in 1-2 sentences.",
            entry_pattern="any user message",
        )
        block = skill.to_context_block()
        assert "[Learned Skill: short-replies]" in block
        assert "Trigger: any user message" in block
        assert "Respond in 1-2 sentences." in block


class TestSkillStoreCRUD:
    """Create, read, update, delete operations."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SkillStore:
        return SkillStore(storage_dir=tmp_path)

    def test_create_returns_draft(self, store: SkillStore):
        skill = store.create(
            name="prefer-python",
            description="Cris prefers Python",
            entry_pattern="coding questions",
            content="Use Python by default unless asked otherwise.",
            tags=["preference", "coding"],
        )
        assert skill.state == SkillState.DRAFT
        assert skill.name == "prefer-python"
        assert len(skill.id) == 10
        assert len(store) == 1

    def test_get_returns_skill(self, store: SkillStore):
        created = store.create(name="test", description="x", entry_pattern="x", content="x")
        fetched = store.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_unknown_id_returns_none(self, store: SkillStore):
        assert store.get("nonexistent") is None

    def test_approve_promotes_to_active(self, store: SkillStore):
        skill = store.create(name="test", description="x", entry_pattern="x", content="x")
        assert store.approve(skill.id) is True

        updated = store.get(skill.id)
        assert updated is not None
        assert updated.state == SkillState.ACTIVE

    def test_approve_already_active_returns_false(self, store: SkillStore):
        skill = store.create(name="test", description="x", entry_pattern="x", content="x")
        store.approve(skill.id)
        assert store.approve(skill.id) is False  # already active

    def test_approve_unknown_returns_false(self, store: SkillStore):
        assert store.approve("nonexistent") is False

    def test_deprecate_marks_deprecated(self, store: SkillStore):
        skill = store.create(name="test", description="x", entry_pattern="x", content="x")
        store.approve(skill.id)
        assert store.deprecate(skill.id, reason="better approach found") is True

        updated = store.get(skill.id)
        assert updated is not None
        assert updated.state == SkillState.DEPRECATED

    def test_deprecate_unknown_returns_false(self, store: SkillStore):
        assert store.deprecate("nonexistent") is False

    def test_remove_deletes(self, store: SkillStore):
        skill = store.create(name="test", description="x", entry_pattern="x", content="x")
        assert store.remove(skill.id) is True
        assert store.get(skill.id) is None
        assert len(store) == 0

    def test_remove_unknown_returns_false(self, store: SkillStore):
        assert store.remove("nonexistent") is False

    def test_update_content_new_version(self, store: SkillStore):
        skill = store.create(name="test", description="x", entry_pattern="x", content="v1")
        updated = store.update_content(skill.id, content="v2", description="Improved")
        assert updated is not None
        assert updated.version == 2
        assert updated.content == "v2"
        assert len(updated.history) == 2  # created + updated

    def test_update_content_unknown_returns_none(self, store: SkillStore):
        assert store.update_content("nonexistent", content="x") is None


class TestSkillStoreQueries:
    """Getter and filtering logic."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SkillStore:
        s = SkillStore(storage_dir=tmp_path)
        s.create(name="a", description="x", entry_pattern="x", content="alpha", tags=["one"])
        s.create(name="b", description="x", entry_pattern="x", content="beta", tags=["two"])
        c = s.create(name="c", description="x", entry_pattern="x", content="gamma", tags=["one"])
        s.approve(c.id)
        return s

    def test_all_returns_all(self, store: SkillStore):
        assert len(store.all()) == 3

    def test_get_active_only_approved(self, store: SkillStore):
        active = store.get_active()
        assert len(active) == 1
        assert active[0].name == "c"

    def test_get_drafts_only_unapproved(self, store: SkillStore):
        drafts = store.get_drafts()
        assert len(drafts) == 2
        assert all(s.state == SkillState.DRAFT for s in drafts)

    def test_get_by_tag(self, store: SkillStore):
        ones = store.get_by_tag("one")
        assert len(ones) == 2
        twos = store.get_by_tag("two")
        assert len(twos) == 1

    def test_get_by_tag_unknown_returns_empty(self, store: SkillStore):
        assert store.get_by_tag("nonexistent") == []


class TestSkillStoreUsage:
    """Usage tracking."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SkillStore:
        s = SkillStore(storage_dir=tmp_path)
        skill = s.create(name="test", description="x", entry_pattern="x", content="x")
        s.approve(skill.id)
        return s

    def test_record_usage_increments_count(self, store: SkillStore):
        active = store.get_active()
        assert len(active) == 1
        sid = active[0].id

        store.record_usage(sid, success=True)
        updated = store.get(sid)
        assert updated is not None
        assert updated.usage_count == 1
        assert updated.success_count == 1

    def test_record_multiple_usages(self, store: SkillStore):
        sid = store.get_active()[0].id
        for _ in range(5):
            store.record_usage(sid, success=True)
        store.record_usage(sid, success=False)

        updated = store.get(sid)
        assert updated is not None
        assert updated.usage_count == 6
        assert updated.success_count == 5
        assert updated.success_rate == 5.0 / 6.0

    def test_record_usage_unknown_does_nothing(self, store: SkillStore):
        store.record_usage("nonexistent", success=True)
        # No crash, nothing recorded
        assert True


class TestSkillStorePersistence:
    """Reload from disk preserves state."""

    def test_reload_preserves_all(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        s1 = store.create(name="persist-test", description="x", entry_pattern="x", content="content")
        store.approve(s1.id)
        store.record_usage(s1.id, success=True)

        # Fresh instance reloads from same dir
        store2 = SkillStore(storage_dir=tmp_path)
        assert len(store2) == 1
        reloaded = store2.get(s1.id)
        assert reloaded is not None
        assert reloaded.name == "persist-test"
        assert reloaded.state == SkillState.ACTIVE
        assert reloaded.version == 1

    def test_reload_empty_dir(self, tmp_path: Path):
        """Loading from empty dir does not crash."""
        store = SkillStore(storage_dir=tmp_path)
        assert len(store) == 0

    def test_reload_corrupted_file(self, tmp_path: Path):
        """Corrupted JSON file does not crash."""
        (tmp_path / "skills.json").write_text("{{{garbage}}}")
        store = SkillStore(storage_dir=tmp_path)
        assert len(store) == 0

    def test_reload_preserves_history(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        s1 = store.create(name="hist-test", description="x", entry_pattern="x", content="v1")
        store.update_content(s1.id, content="v2")
        store.approve(s1.id)

        store2 = SkillStore(storage_dir=tmp_path)
        reloaded = store2.get(s1.id)
        assert reloaded is not None
        assert len(reloaded.history) == 3  # created + updated + approved
        assert reloaded.history[0].action == "created"
        assert reloaded.history[1].action == "updated"
        assert reloaded.history[2].action == "approved"

    def test_multiple_skills_persist(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        ids = []
        for i in range(10):
            s = store.create(name=f"skill-{i}", description="x", entry_pattern="x", content=f"content-{i}")
            ids.append(s.id)
            if i % 2 == 0:
                store.approve(s.id)

        store2 = SkillStore(storage_dir=tmp_path)
        assert len(store2) == 10
        assert len(store2.get_active()) == 5
        assert len(store2.get_drafts()) == 5


class TestSkillStoreEdgeCases:
    """Boundary conditions."""

    def test_create_empty_content(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        skill = store.create(name="empty", description="x", entry_pattern="x", content="")
        assert skill is not None
        assert skill.content == ""

    def test_create_with_tags(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        tags = ["a", "b", "c"]
        skill = store.create(name="tagged", description="x", entry_pattern="x", content="x", tags=tags)
        assert skill.tags == tags

    def test_deprecate_twice_still_succeeds(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        s = store.create(name="test", description="x", entry_pattern="x", content="x")
        store.approve(s.id)
        assert store.deprecate(s.id) is True
        assert store.deprecate(s.id) is True  # idempotent

    def test_multiple_updates_track_versions(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        s = store.create(name="versioned", description="x", entry_pattern="x", content="v1")
        for v in range(2, 6):
            store.update_content(s.id, content=f"v{v}")
        reloaded = store.get(s.id)
        assert reloaded is not None
        assert reloaded.version == 5
        assert reloaded.content == "v5"
        assert len(reloaded.history) == 5  # created + 4 updates

    def test_no_history_in_empty_skill(self):
        skill = StoredSkill(id="s1", name="test", description="desc", content="content")
        assert skill.history == []
