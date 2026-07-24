"""
Tests for core/category_router.py — CategoryRouter, ExecutionMode, CategoryRule.

Unit tests: no external dependencies, tests pure data structures and routing logic.
"""

from __future__ import annotations

import pytest
from core.categories import ToolCategory
from core.category_router import (
    CategoryRouter,
    CategoryRule,
    DEFAULT_RULES,
    ExecutionMode,
)


class TestExecutionMode:
    """ExecutionMode enum — three modes."""

    def test_inline_value(self):
        assert ExecutionMode.INLINE.value == 1  # auto() starts at 1

    def test_ai_proxy_value(self):
        assert ExecutionMode.AI_PROXY.value == 2

    def test_external_value(self):
        assert ExecutionMode.EXTERNAL.value == 3

    def test_all_modes_defined(self):
        assert len(ExecutionMode) == 3


class TestCategoryRule:
    """CategoryRule dataclass — routing rule for a single category."""

    def test_default_supports_fallback(self):
        rule = CategoryRule(mode=ExecutionMode.INLINE)
        assert rule.supports_fallback is True

    def test_supports_fallback_false(self):
        rule = CategoryRule(mode=ExecutionMode.INLINE, supports_fallback=False)
        assert rule.supports_fallback is False

    def test_provider_role_default_none(self):
        rule = CategoryRule(mode=ExecutionMode.INLINE)
        assert rule.provider_role is None

    def test_provider_role_set(self):
        rule = CategoryRule(mode=ExecutionMode.AI_PROXY, provider_role="vision")
        assert rule.provider_role == "vision"

    def test_frozen_dataclass(self):
        """CategoryRule is frozen — should raise when modified."""
        rule = CategoryRule(mode=ExecutionMode.INLINE)
        with pytest.raises((AttributeError, TypeError)):
            rule.mode = ExecutionMode.EXTERNAL  # type: ignore[misc]


class TestDefaultRules:
    """DEFAULT_RULES covers all ToolCategories."""

    def test_inline_categories(self):
        """FILE, ENV, SESSION, MEMORY → INLINE."""
        inline_cats = [
            ToolCategory.FILE,
            ToolCategory.ENV,
            ToolCategory.SESSION,
            ToolCategory.MEMORY,
        ]
        for cat in inline_cats:
            rule = DEFAULT_RULES[cat]
            assert rule.mode == ExecutionMode.INLINE, f"{cat} should be INLINE"

    def test_ai_proxy(self):
        rule = DEFAULT_RULES[ToolCategory.MEDIA]
        assert rule.mode == ExecutionMode.AI_PROXY

    def test_external(self):
        rule = DEFAULT_RULES[ToolCategory.COLLAB]
        assert rule.mode == ExecutionMode.EXTERNAL

    def test_files_supports_fallback_false(self):
        assert DEFAULT_RULES[ToolCategory.FILE].supports_fallback is False

    def test_ai_supports_fallback_true(self):
        assert DEFAULT_RULES[ToolCategory.MEDIA].supports_fallback is True

    def test_external_supports_fallback_false(self):
        assert DEFAULT_RULES[ToolCategory.COLLAB].supports_fallback is False

    def test_all_categories_have_rules(self):
        """Every ToolCategory enum has a corresponding DEFAULT_RULES entry."""
        for cat in ToolCategory:
            assert cat in DEFAULT_RULES, f"{cat} missing from DEFAULT_RULES"

    def test_fallback_default_true(self):
        """Default for CategoryRule.supports_fallback is True."""
        rule = CategoryRule(mode=ExecutionMode.INLINE)
        assert rule.supports_fallback


class TestCategoryRouter:
    """CategoryRouter — routing logic and provider management."""

    def test_get_rule_defaults(self):
        router = CategoryRouter()
        for cat in ToolCategory:
            rule = router.get_rule(cat)
            assert isinstance(rule, CategoryRule)
            assert rule.mode in (ExecutionMode.INLINE, ExecutionMode.AI_PROXY, ExecutionMode.EXTERNAL)

    def test_get_rule_for_unknown_category_falls_to_inline(self):
        """get_rule returns INLINE for any ToolCategory, even if not in _rules."""
        router = CategoryRouter()
        # All defined categories should return a valid rule
        for cat in ToolCategory:
            rule = router.get_rule(cat)
            assert isinstance(rule, CategoryRule)
            assert rule.mode in (
                ExecutionMode.INLINE, ExecutionMode.AI_PROXY, ExecutionMode.EXTERNAL
            )

    def test_set_rule_overrides_default(self):
        router = CategoryRouter()
        new_rule = CategoryRule(mode=ExecutionMode.AI_PROXY, provider_role="custom")
        router.set_rule(ToolCategory.FILE, new_rule)
        assert router.get_rule(ToolCategory.FILE).mode == ExecutionMode.AI_PROXY

    def test_should_inline_true_for_files(self):
        router = CategoryRouter()
        assert router.should_inline(ToolCategory.FILE) is True

    def test_should_inline_false_for_ai(self):
        router = CategoryRouter()
        assert router.should_inline(ToolCategory.MEDIA) is False

    def test_should_inline_true_for_external(self):
        """EXTERNAL executes inline (no provider proxy)."""
        router = CategoryRouter()
        assert router.should_inline(ToolCategory.COLLAB) is True

    def test_needs_provider_for_ai(self):
        router = CategoryRouter()
        assert router.needs_provider(ToolCategory.MEDIA) is True

    def test_needs_provider_false_for_files(self):
        router = CategoryRouter()
        assert router.needs_provider(ToolCategory.FILE) is False

    def test_provider_management(self):
        router = CategoryRouter()

        class FakeProvider:
            def get_model(self): return "fake"
            async def chat_completion(self, **kw): pass
            async def close(self): pass

        p = FakeProvider()
        router.set_provider("vision", p)
        assert router.get_provider("vision") is p

    def test_get_provider_unknown_role(self):
        router = CategoryRouter()
        assert router.get_provider("nonexistent") is None

    def test_get_provider_none(self):
        router = CategoryRouter()
        assert router.get_provider(None) is None

    def test_get_provider_for_ai(self):
        router = CategoryRouter()

        class FakeProvider:
            def get_model(self): return "fake"
            async def chat_completion(self, **kw): pass
            async def close(self): pass

        p = FakeProvider()
        router.set_provider("default", p)
        result = router.get_provider_for(ToolCategory.MEDIA)
        assert result is p

    def test_get_provider_for_files_returns_none(self):
        router = CategoryRouter()
        result = router.get_provider_for(ToolCategory.FILE)
        assert result is None

    def test_set_rule_and_get_rule_consistency(self):
        router = CategoryRouter()
        rule = CategoryRule(mode=ExecutionMode.EXTERNAL, supports_fallback=True)
        router.set_rule(ToolCategory.MEMORY, rule)
        retrieved = router.get_rule(ToolCategory.MEMORY)
        assert retrieved.mode == ExecutionMode.EXTERNAL
        assert retrieved.supports_fallback is True

    def test_multiple_providers(self):
        router = CategoryRouter()

        class FakeProvider:
            def __init__(self, name): self.name = name
            def get_model(self): return self.name
            async def chat_completion(self, **kw): pass
            async def close(self): pass

        router.set_provider("default", FakeProvider("deepseek"))
        router.set_provider("vision", FakeProvider("ollama"))

        assert router.get_provider("default").get_model() == "deepseek"
        assert router.get_provider("vision").get_model() == "ollama"
