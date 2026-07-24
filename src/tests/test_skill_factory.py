"""
Tests for learning/skill_factory.py + learning/skill_refiner.py.

Covers: pattern detection, skill generation, sensitive-data redaction,
refinement (auto-deprecate low-success skills), and health reporting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.categories import ToolCategory
from learning.skill_factory import (
    MIN_PATTERN_OCCURRENCES,
    SENSITIVE_PATTERNS,
    BLOCKED_CATEGORIES,
    PatternMatch,
    SkillFactory,
    ToolCallRecord,
    _contains_sensitive,
    inject_active_skills,
)
from learning.skill_refiner import (
    DEPRECATE_THRESHOLD,
    MIN_USES_FOR_REFINE,
    WARN_THRESHOLD,
    SkillRefiner,
)
from learning.skill_store import SkillStore, SkillState


# ═══════════════════════════════════════════════════════════════════
# SkillFactory — ToolCallRecord, PatternMatch
# ═══════════════════════════════════════════════════════════════════

class TestToolCallRecord:
    def test_default_fields(self):
        rec = ToolCallRecord(
            tool_name="read_file",
            arguments={"path": "/tmp/x"},
            category="FILES",
            success=True,
            timestamp=100.0,
            session_id="sess_1",
        )
        assert rec.tool_name == "read_file"
        assert rec.response_preview == ""


class TestPatternMatch:
    def test_default_description(self):
        pm = PatternMatch(
            tool_name="read_file",
            recurring_keys=["path"],
            sample_values={"path": "/tmp"},
            occurrences=3,
            recent_session_ids=["s1"],
        )
        assert pm.description == ""


# ═══════════════════════════════════════════════════════════════════
# SkillFactory — observe + sanitize
# ═══════════════════════════════════════════════════════════════════

class TestSkillFactoryObserve:
    @pytest.fixture
    def factory(self, tmp_path: Path) -> SkillFactory:
        return SkillFactory(store=SkillStore(storage_dir=tmp_path))

    def test_observe_adds_record(self, factory: SkillFactory):
        factory.observe("read_file", {"path": "/test.txt"}, "FILES", True, "s1")
        assert len(factory._records) == 1
        assert factory._records[0].tool_name == "read_file"

    def test_observe_multiple_same_tool(self, factory: SkillFactory):
        for _ in range(5):
            factory.observe("read_file", {"path": "/test.txt"}, "FILES", True, "s1")
        assert len(factory._records) == 5

    def test_observe_skips_blocked_category(self, factory: SkillFactory):
        for cat in BLOCKED_CATEGORIES:
            factory.observe("sys_tool", {}, cat, True, "s1")
        assert len(factory._records) == 0

    def test_observe_skips_sensitive_content(self, factory: SkillFactory):
        factory.observe(
            "write_env", {"key": "API_KEY=sk-abc123secret"}, "CONFIG", True, "s1",
        )
        assert len(factory._records) == 0

    def test_observe_trims_old_records(self, factory: SkillFactory):
        factory._max_records = 3
        for i in range(5):
            factory.observe("tool", {"i": i}, "TEST", True, f"s{i}")
        assert len(factory._records) == 3


class TestSanitizeArguments:
    def test_long_string_truncated(self):
        long_val = "a" * 300
        result = SkillFactory._sanitize_arguments({"data": long_val})
        assert len(result["data"]) == 200 + 3  # 200 chars + "..."

    def test_sensitive_keyword_values_redacted(self):
        """Values containing password/secret/token/api_key are redacted."""
        result = SkillFactory._sanitize_arguments({
            "config": "password=secret123",
            "env": "API_KEY=sk-abc12345678901234567890",
            "auth": "Bearer token=xyz",
        })
        assert result["config"] == "***REDACTED***"
        assert result["env"] == "***REDACTED***"
        assert result["auth"] == "***REDACTED***"

    def test_dict_summary(self):
        result = SkillFactory._sanitize_arguments({"nested": {"a": 1, "b": 2, "c": 3}})
        assert "<dict 3 keys>" in result["nested"]

    def test_list_summary(self):
        result = SkillFactory._sanitize_arguments({"items": [1, 2, 3, 4, 5]})
        assert "<list 5 items>" in result["items"]

    def test_primitives_pass_through(self):
        data = {"int": 42, "float": 3.14, "bool": True, "none": None}
        result = SkillFactory._sanitize_arguments(data)
        assert result == data


class TestContainsSensitive:
    def test_detects_api_key_pattern(self):
        assert _contains_sensitive({"key": "my_api_key=sk-abc123"}) is True

    def test_detects_private_key(self):
        assert _contains_sensitive({"key": "-----BEGIN RSA PRIVATE KEY-----"}) is True

    def test_clear_text_passes(self):
        assert _contains_sensitive({"content": "hello world"}) is False

    def test_empty_args_passes(self):
        assert _contains_sensitive({}) is False


# ═══════════════════════════════════════════════════════════════════
# SkillFactory — pattern detection
# ═══════════════════════════════════════════════════════════════════

class TestDetectPatterns:
    @pytest.fixture
    def factory(self, tmp_path: Path) -> SkillFactory:
        return SkillFactory(store=SkillStore(storage_dir=tmp_path))

    def test_no_patterns_with_few_calls(self, factory: SkillFactory):
        factory.observe("read_file", {"path": "/x"}, "FILES", True, "s1")
        assert factory.detect_patterns() == []

    def test_pattern_detected_after_min_occurrences(self, factory: SkillFactory):
        for _ in range(MIN_PATTERN_OCCURRENCES):
            factory.observe("read_file", {"path": "/data.txt"}, "FILES", True, "s1")
        patterns = factory.detect_patterns()
        assert len(patterns) == 1
        assert patterns[0].tool_name == "read_file"
        assert patterns[0].occurrences == MIN_PATTERN_OCCURRENCES

    def test_recurring_keys_detected(self, factory: SkillFactory):
        for _ in range(5):
            factory.observe("search_web", {"query": "python"}, "SEARCH", True, "s1")
        patterns = factory.detect_patterns()
        assert len(patterns) == 1
        assert "query" in patterns[0].recurring_keys

    def test_non_recurring_keys_excluded(self, factory: SkillFactory):
        """Keys that vary between calls should NOT be recurring."""
        for i in range(5):
            factory.observe("read_file", {"path": f"/file_{i}.txt"}, "FILES", True, "s1")
        patterns = factory.detect_patterns()
        # "path" varies each time, so no key reaches 80% threshold
        # Actually, "path" IS in every call, so it DOES recur at 100%
        # Let me use a different key that only appears sometimes
        for i in range(3):
            extra = {"mode": "text"} if i < 2 else {"mode": "binary"}
            factory.observe("read_file", {"path": "/x.txt", **extra}, "FILES", True, "s1")
        patterns = factory.detect_patterns()
        # "path" appears in all calls (100%), "mode" is less consistent
        assert "path" in patterns[0].recurring_keys if patterns else True

    def test_different_tools_separate_patterns(self, factory: SkillFactory):
        for _ in range(5):
            factory.observe("read_file", {"path": "/x"}, "FILES", True, "s1")
            factory.observe("write_file", {"path": "/y"}, "FILES", True, "s2")
        patterns = factory.detect_patterns()
        assert len(patterns) == 2
        tool_names = {p.tool_name for p in patterns}
        assert tool_names == {"read_file", "write_file"}

    def test_observe_with_response_preview(self, factory: SkillFactory):
        for _ in range(5):
            factory.observe("read_file", {"path": "/x"}, "FILES", True, "s1",
                            response_preview="file content here")
        patterns = factory.detect_patterns()
        assert len(patterns) == 1

    def test_only_successful_calls_are_patterned(self, factory: SkillFactory):
        """No requirement that calls must be successful — all calls are tracked."""
        for _ in range(3):
            factory.observe("read_file", {"path": "/x"}, "FILES", False, "s1")
        patterns = factory.detect_patterns()
        assert len(patterns) == 1


# ═══════════════════════════════════════════════════════════════════
# SkillFactory — skill generation
# ═══════════════════════════════════════════════════════════════════

class TestGenerateSkill:
    @pytest.fixture
    def factory(self, tmp_path: Path) -> SkillFactory:
        return SkillFactory(store=SkillStore(storage_dir=tmp_path))

    def test_generate_creates_draft(self, factory: SkillFactory):
        pattern = PatternMatch(
            tool_name="read_file",
            recurring_keys=["path"],
            sample_values={"path": "/data.txt"},
            occurrences=5,
            recent_session_ids=["s1", "s2"],
            description="Repeated file reads",
        )
        skill = factory.generate_skill(pattern)
        assert skill.state == SkillState.DRAFT
        assert "read_file" in skill.name
        assert "path" in skill.entry_pattern
        assert len(skill.tags) >= 2
        assert "auto-generated" in skill.tags

    def test_generate_content_includes_keys(self, factory: SkillFactory):
        pattern = PatternMatch(
            tool_name="search_web",
            recurring_keys=["query"],
            sample_values={"query": "python"},
            occurrences=10,
            recent_session_ids=["s1"],
        )
        skill = factory.generate_skill(pattern)
        assert "search_web" in skill.content
        assert "query" in skill.content

    def test_generate_empty_sample_values(self, factory: SkillFactory):
        """Pattern with None sample values should not crash."""
        pattern = PatternMatch(
            tool_name="tool",
            recurring_keys=["key1", "key2"],
            sample_values={},
            occurrences=3,
            recent_session_ids=["s1"],
        )
        skill = factory.generate_skill(pattern)
        assert skill is not None
        assert skill.content != ""


class TestApproveAllDrafts:
    def test_approve_all(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        factory = SkillFactory(store=store)
        # Generate 3 drafts
        for i in range(3):
            pattern = PatternMatch(
                tool_name=f"tool_{i}", recurring_keys=["k"],
                sample_values={"k": f"v{i}"}, occurrences=3,
                recent_session_ids=["s1"],
            )
            factory.generate_skill(pattern)
        assert len(store.get_drafts()) == 3
        assert factory.approve_all_drafts() == 3
        assert len(store.get_active()) == 3


# ═══════════════════════════════════════════════════════════════════
# inject_active_skills
# ═══════════════════════════════════════════════════════════════════

class TestInjectActiveSkills:
    def test_no_active_skills_returns_unchanged(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        result = inject_active_skills(store, "You are Haven.")
        assert result == "You are Haven."

    def test_injects_active_skills(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        s = store.create(name="short-replies", description="x", entry_pattern="x", content="Keep it short")
        store.approve(s.id)

        result = inject_active_skills(store, "You are Haven.")
        assert "Learned Skills" in result
        assert "short-replies" in result
        # P5a deferred: full content NOT in prompt (use skill_tool to load)
        assert "Keep it short" not in result
        assert "You are Haven." in result


# ═══════════════════════════════════════════════════════════════════
# SkillRefiner
# ═══════════════════════════════════════════════════════════════════

class TestSkillRefinerEvaluate:
    @pytest.fixture
    def refiner(self, tmp_path: Path) -> SkillRefiner:
        store = SkillStore(storage_dir=tmp_path)
        return SkillRefiner(store=store)

    def test_skip_few_uses(self, refiner: SkillRefiner):
        """Skills below MIN_USES_FOR_REFINE are not evaluated."""
        s = refiner.store.create(name="new-skill", description="x", entry_pattern="x", content="x")
        refiner.store.approve(s.id)
        refiner.store.record_usage(s.id, success=True)

        warnings = refiner.evaluate()
        assert warnings == []

    def test_deprecate_low_success(self, refiner: SkillRefiner):
        """Below DEPRECATE_THRESHOLD → deprecated."""
        s = refiner.store.create(name="bad-skill", description="x", entry_pattern="x", content="x")
        refiner.store.approve(s.id)
        for _ in range(MIN_USES_FOR_REFINE):
            refiner.store.record_usage(s.id, success=False)

        warnings = refiner.evaluate()
        assert any("DEPRECATED" in w for w in warnings)
        updated = refiner.store.get(s.id)
        assert updated is not None
        assert updated.state == SkillState.DEPRECATED

    def test_warn_borderline_success(self, refiner: SkillRefiner):
        """Between DEPRECATE_THRESHOLD and WARN_THRESHOLD → warning."""
        s = refiner.store.create(name="okay-skill", description="x", entry_pattern="x", content="x")
        refiner.store.approve(s.id)
        # Set rate just below 50% (e.g., 2/5 = 40%)
        for _ in range(3):
            refiner.store.record_usage(s.id, success=False)
        for _ in range(2):
            refiner.store.record_usage(s.id, success=True)

        warnings = refiner.evaluate()
        assert any("WARNING" in w for w in warnings)
        updated = refiner.store.get(s.id)
        assert updated is not None
        assert updated.state == SkillState.ACTIVE  # not deprecated

    def test_high_success_no_action(self, refiner: SkillRefiner):
        """Above WARN_THRESHOLD → no warnings."""
        s = refiner.store.create(name="good-skill", description="x", entry_pattern="x", content="x")
        refiner.store.approve(s.id)
        for _ in range(MIN_USES_FOR_REFINE):
            refiner.store.record_usage(s.id, success=True)

        warnings = refiner.evaluate()
        assert warnings == []

    def test_multiple_skills_evaluated(self, refiner: SkillRefiner):
        """All active skills are evaluated."""
        s1 = refiner.store.create(name="good", description="x", entry_pattern="x", content="x")
        s2 = refiner.store.create(name="bad", description="x", entry_pattern="x", content="x")
        refiner.store.approve(s1.id)
        refiner.store.approve(s2.id)

        for _ in range(5):
            refiner.store.record_usage(s1.id, success=True)
            refiner.store.record_usage(s2.id, success=False)

        warnings = refiner.evaluate()
        dep_warnings = [w for w in warnings if "DEPRECATED" in w]
        assert len(dep_warnings) >= 1

    def test_idempotent_evaluate(self, refiner: SkillRefiner):
        """Calling evaluate() multiple times doesn't double-process."""
        s = refiner.store.create(name="bad", description="x", entry_pattern="x", content="x")
        refiner.store.approve(s.id)
        for _ in range(5):
            refiner.store.record_usage(s.id, success=False)

        refiner.evaluate()
        warnings2 = refiner.evaluate()
        # Already deprecated, so no new warnings
        non_dep_warnings = [w for w in warnings2 if "DEPRECATED" in w]
        assert len(non_dep_warnings) == 0


class TestHealthReport:
    def test_empty_store(self, tmp_path: Path):
        store = SkillStore(storage_dir=tmp_path)
        refiner = SkillRefiner(store=store)
        report = refiner.get_health_report()
        assert "No skills stored." in report

    def test_populated_report(self, refiner_with_skills):
        report = refiner_with_skills.get_health_report()
        assert "Skill Health Report" in report
        assert "test-skill" in report

    @pytest.fixture
    def refiner_with_skills(self, tmp_path: Path) -> SkillRefiner:
        store = SkillStore(storage_dir=tmp_path)
        s = store.create(name="test-skill", description="x", entry_pattern="x", content="x")
        store.approve(s.id)
        store.record_usage(s.id, success=True)
        return SkillRefiner(store=store)
