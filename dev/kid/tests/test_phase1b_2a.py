"""Phase 1b + 2a tests — CategoryRouter, LongTermMemory, Summarizer, MemoryIndex."""

import tempfile
from pathlib import Path

import pytest
from core.categories import ToolCategory
from core.category_router import CategoryRouter, CategoryRule, ExecutionMode, DEFAULT_RULES
from soul.memory import LongTermMemory, summarize_session, MemoryIndex


class TestCategoryRouter:
    def test_all_categories_have_rules(self):
        for cat in ToolCategory:
            assert cat in DEFAULT_RULES, f"Missing rule for {cat}"

    def test_execution_modes_match_design(self):
        assert DEFAULT_RULES[ToolCategory.FILES].mode == ExecutionMode.INLINE
        assert DEFAULT_RULES[ToolCategory.SYSTEM].mode == ExecutionMode.INLINE
        assert DEFAULT_RULES[ToolCategory.AI].mode == ExecutionMode.AI_PROXY
        assert DEFAULT_RULES[ToolCategory.EXTERNAL].mode == ExecutionMode.EXTERNAL

    def test_should_inline(self):
        cr = CategoryRouter()
        assert cr.should_inline(ToolCategory.FILES) is True
        assert cr.should_inline(ToolCategory.AI) is False

    def test_needs_provider(self):
        cr = CategoryRouter()
        assert cr.needs_provider(ToolCategory.AI) is True
        assert cr.needs_provider(ToolCategory.FILES) is False

    def test_provider_management(self):
        from core.base_provider import BaseProvider
        from core.models import ProviderResponse

        class MockProvider(BaseProvider):
            async def chat_completion(self, **kw):
                return ProviderResponse(content="mock")
            def get_model(self, o=None):
                return "mock"
            async def close(self):
                pass

        cr = CategoryRouter()
        cr.set_provider("default", MockProvider())
        cr.set_provider("vision", MockProvider())
        assert cr.get_provider("default") is not None
        assert cr.get_provider("nonexistent") is None

    def test_custom_rule_override(self):
        cr = CategoryRouter()
        cr.set_rule(
            ToolCategory.WEB,
            CategoryRule(mode=ExecutionMode.AI_PROXY, provider_role="vision"),
        )
        rule = cr.get_rule(ToolCategory.WEB)
        assert rule.mode == ExecutionMode.AI_PROXY
        assert rule.provider_role == "vision"


class TestLongTermMemory:
    def test_add_and_search(self):
        with tempfile.TemporaryDirectory() as td:
            ltm = LongTermMemory(Path(td))
            ltm.add("fact", "Cris prefers Python", tags=["coding"])
            results = ltm.search("Python")
            assert len(results) == 1
            assert "Python" in results[0].content

    def test_remove(self):
        with tempfile.TemporaryDirectory() as td:
            ltm = LongTermMemory(Path(td))
            e = ltm.add("fact", "test")
            assert ltm.remove(e.id) is True
            assert ltm.remove(e.id) is False

    def test_get_recent(self):
        with tempfile.TemporaryDirectory() as td:
            ltm = LongTermMemory(Path(td))
            ltm.add("fact", "a")
            ltm.add("preference", "b")
            recent = ltm.get_recent(5)
            assert len(recent) == 2

    def test_tag_filter(self):
        with tempfile.TemporaryDirectory() as td:
            ltm = LongTermMemory(Path(td))
            ltm.add("fact", "python stuff", tags=["coding"])
            ltm.add("fact", "infra stuff", tags=["infra"])
            results = ltm.search("stuff", tag_filter="coding")
            assert len(results) == 1
            assert "python" in results[0].content

    def test_access_tracking(self):
        with tempfile.TemporaryDirectory() as td:
            ltm = LongTermMemory(Path(td))
            ltm.add("fact", "test")
            ltm.search("test")
            results = ltm.search("test")
            assert results[0].access_count == 2

    def test_persistence(self):
        td = tempfile.mkdtemp()
        try:
            ltm = LongTermMemory(Path(td))
            ltm.add("fact", "persisted")
            # Reload
            ltm2 = LongTermMemory(Path(td))
            assert len(ltm2) == 1
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)


class TestSummarizer:
    def test_extracts_preferences(self):
        msgs = [
            {"role": "user", "content": "I prefer Python over JavaScript."},
        ]
        s = summarize_session("test", msgs)
        assert len(s.preferences_mentioned) > 0

    def test_extracts_decisions(self):
        msgs = [
            {"role": "user", "content": "I have decided to use FastAPI for the project."},
        ]
        s = summarize_session("test", msgs)
        assert any("FastAPI" in d for d in s.decisions)

    def test_empty_session(self):
        s = summarize_session("empty", [])
        assert s.brief == "(empty session)"

    def test_topic_detection(self):
        msgs = [
            {"role": "user", "content": "The Python deployment on the server needs a memory upgrade."},
        ]
        s = summarize_session("test", msgs)
        assert len(s.key_topics) > 0


class TestMemoryIndex:
    def test_keyword_query(self):
        with tempfile.TemporaryDirectory() as td:
            ltm = LongTermMemory(Path(td))
            ltm.add("fact", "Python is great", tags=["coding"])
            ltm.add("preference", "Use FastAPI", tags=["python"])
            ltm.add("fact", "Port 8080", tags=["infra"])
            idx = MemoryIndex(ltm)
            results = idx.query("python fastapi", 5)
            assert len(results) >= 1
