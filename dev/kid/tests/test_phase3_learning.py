"""Phase 3 tests — SkillStore, SkillFactory, SkillRefiner."""

import tempfile
from pathlib import Path

import pytest
from learning.skill_store import SkillStore, SkillState, StoredSkill
from learning.skill_factory import SkillFactory, inject_active_skills
from learning.skill_refiner import SkillRefiner


class TestSkillStore:
    def test_create_draft(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            s = store.create("test", "desc", "trigger", "content")
            assert s.state == SkillState.DRAFT
            assert s.version == 1

    def test_approve_transition(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            s = store.create("test", "desc", "trigger", "content")
            assert store.approve(s.id) is True
            s2 = store.get(s.id)
            assert s2.state == SkillState.ACTIVE

    def test_deprecate_transition(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            s = store.create("test", "desc", "trigger", "content")
            store.approve(s.id)
            assert store.deprecate(s.id, "no longer needed") is True
            assert store.get(s.id).state == SkillState.DEPRECATED

    def test_update_versioning(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            s = store.create("test", "desc", "trigger", "content")
            store.update_content(s.id, "new content", "updated")
            s2 = store.get(s.id)
            assert s2.version == 2
            assert s2.content == "new content"
            assert len(s2.history) == 2  # created + updated

    def test_usage_tracking(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            s = store.create("test", "desc", "trigger", "content")
            store.record_usage(s.id, True)
            store.record_usage(s.id, True)
            store.record_usage(s.id, False)
            s2 = store.get(s.id)
            assert s2.usage_count == 3
            assert s2.success_rate == 2 / 3

    def test_get_active_empty(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            assert store.get_active() == []

    def test_get_drafts(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            store.create("a", "desc", "t", "c")
            store.create("b", "desc", "t", "c")
            assert len(store.get_drafts()) == 2

    def test_tag_filter(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            store.create("a", "desc", "t", "c", tags=["coding"])
            store.create("b", "desc", "t", "c", tags=["infra"])
            assert len(store.get_by_tag("coding")) == 1

    def test_persistence(self):
        td = tempfile.mkdtemp()
        try:
            store = SkillStore(Path(td))
            store.create("saved", "desc", "t", "c")
            store2 = SkillStore(Path(td))
            assert len(store2) == 1
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)

    def test_to_context_block(self):
        s = StoredSkill(
            id="x", name="test", description="d", state=SkillState.ACTIVE,
            content="Do X when Y", entry_pattern="trigger",
        )
        block = s.to_context_block()
        assert "Learned Skill: test" in block
        assert "Do X when Y" in block


class TestSkillFactory:
    def test_pattern_detection_below_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            factory = SkillFactory(store)
            factory.observe("read_file", {"path": "/x"}, "FILES", True, "s1")
            factory.observe("read_file", {"path": "/y"}, "FILES", True, "s2")
            patterns = factory.detect_patterns()
            assert patterns == []  # only 2 occurrences

    def test_pattern_detection_at_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            factory = SkillFactory(store)
            for i in range(3):
                factory.observe("read_file", {"path": f"/tmp/{i}"}, "FILES", True, f"s{i}")
            patterns = factory.detect_patterns()
            assert len(patterns) >= 1
            assert patterns[0].tool_name == "read_file"

    def test_blocked_category_skipped(self):
        from core.categories import ToolCategory
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            factory = SkillFactory(store)
            for i in range(5):
                factory.observe(
                    "cmd", {"cmd": "ls"},
                    ToolCategory.SYSTEM,  # pass enum, not string
                    True, f"s{i}",
                )
            patterns = factory.detect_patterns()
            # SYSTEM is blocked — no patterns for cmd
            for p in patterns:
                if p.tool_name == "cmd":
                    pytest.fail("SYSTEM tool should be blocked from learning")

    def test_generate_skill(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            factory = SkillFactory(store)
            for i in range(3):
                factory.observe("write_file", {"path": "/tmp/o.txt", "content": "test"},
                                "FILES", True, f"s{i}")
            patterns = factory.detect_patterns()
            assert len(patterns) >= 1
            skill = factory.generate_skill(patterns[0])
            assert skill.state == SkillState.DRAFT
            assert "write_file" in skill.name

    def test_inject_active_skills_empty(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            prompt = "base prompt"
            result = inject_active_skills(store, prompt)
            assert result == prompt  # no active skills

    def test_inject_active_skills_with_active(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            s = store.create("test", "desc", "trigger", "do X")
            store.approve(s.id)
            prompt = "base prompt"
            result = inject_active_skills(store, prompt)
            assert len(result) > len(prompt)
            assert "Learned Skills" in result


class TestSkillRefiner:
    def test_empty_evaluate(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            refiner = SkillRefiner(store)
            warnings = refiner.evaluate()
            assert warnings == []

    def test_health_report(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(Path(td))
            store.create("a", "desc", "t", "content")
            refiner = SkillRefiner(store)
            report = refiner.get_health_report()
            assert "Skill Health Report" in report
            assert "a" in report
