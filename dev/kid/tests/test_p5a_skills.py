"""P5a tests — Skills defer loading (two-stage expansion)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from learning.skill_store import SkillStore, SkillState, StoredSkill
from learning.skill_factory import inject_active_skills


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as td:
        s = SkillStore(storage_dir=Path(td))
        yield s


@pytest.fixture
def store_with_skills(store):
    s1 = store.create("deploy-check", "Checks deployment health", "deploy", "#!/bin/bash\nkubectl get pods")
    store.approve(s1.id)
    s2 = store.create("log-parser", "Parse error logs", "error log", "grep -E 'ERROR|FATAL' /var/log/app.log")
    store.approve(s2.id)
    return store


# ── SkillStore get_by_name ───────────────────────────────────────────────────

class TestSkillStoreGetByName:
    def test_exact_match(self, store_with_skills):
        s = store_with_skills.get_by_name("deploy-check")
        assert s is not None
        assert s.name == "deploy-check"

    def test_case_insensitive(self, store_with_skills):
        s = store_with_skills.get_by_name("DEPLOY-CHECK")
        assert s is not None
        assert s.name == "deploy-check"

    def test_not_found(self, store_with_skills):
        assert store_with_skills.get_by_name("ghost") is None

    def test_ignores_drafts(self, store):
        store.create("secret", "draft skill", "trigger", "secret content")
        assert store.get_by_name("secret") is None


# ── Deferred inject_active_skills ────────────────────────────────────────────

class TestDeferredInjection:
    def test_deferred_injects_summaries_only(self, store_with_skills):
        base = "You are helpful."
        result = inject_active_skills(store_with_skills, base)
        assert "[Learned Skills" in result
        assert "skill_tool(name)" in result
        assert "#!/bin/bash" not in result

    def test_deferred_includes_descriptions(self, store_with_skills):
        result = inject_active_skills(store_with_skills, "base")
        assert "deploy-check" in result
        assert "Checks deployment health" in result

    def test_deferred_caps_at_12(self, store):
        for i in range(15):
            s = store.create(f"skill-{i}", f"desc {i}", f"trigger{i}", f"content {i}")
            store.approve(s.id)
        result = inject_active_skills(store, "base")
        assert result.count("- ") <= 12

    def test_no_active_skills_returns_unchanged(self, store):
        base = "Just base prompt."
        result = inject_active_skills(store, base)
        assert result == base


# ── skill_tool expansion ─────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSkillToolExpansion:
    async def test_expand_returns_full_content(self, store_with_skills):
        from tools.skill_tool import set_skill_store, skill_tool, clear_session_cache
        clear_session_cache()
        set_skill_store(store_with_skills)
        result = await skill_tool(name="deploy-check")
        assert "kubectl get pods" in result

    async def test_expand_not_found(self, store_with_skills):
        from tools.skill_tool import set_skill_store, skill_tool, clear_session_cache
        clear_session_cache()
        set_skill_store(store_with_skills)
        result = await skill_tool(name="nonexistent")
        assert "not found" in result
        assert "deploy-check" in result

    async def test_expand_caches_result(self, store_with_skills):
        from tools.skill_tool import set_skill_store, skill_tool, clear_session_cache
        clear_session_cache()
        set_skill_store(store_with_skills)
        r1 = await skill_tool(name="deploy-check")
        r2 = await skill_tool(name="deploy-check")
        assert r1 == r2

    async def test_no_store_configured(self):
        from tools.skill_tool import skill_tool, clear_session_cache, set_skill_store
        clear_session_cache()
        # Clear the global store reference from other tests
        set_skill_store(None)
        result = await skill_tool(name="anything")
        assert "No skill store" in result

    async def test_clear_cache_works(self, store_with_skills):
        from tools.skill_tool import set_skill_store, skill_tool, clear_session_cache
        clear_session_cache()
        set_skill_store(store_with_skills)
        await skill_tool(name="deploy-check")
        clear_session_cache()
        result = await skill_tool(name="deploy-check")
        assert "kubectl" in result


# ── Router integration ───────────────────────────────────────────────────────

class TestRouterSkillTool:
    async def test_router_uses_deferred_injection(self):
        from core.router import Router
        from core.tool_registry import ToolRegistry
        from core.base_provider import BaseProvider
        from core.models import ProviderResponse

        store = SkillStore.__new__(SkillStore)
        store._skills = {}
        sid = "test-skill"
        store._skills[sid] = StoredSkill(
            id=sid, name="fast-test", description="Quick test",
            state=SkillState.ACTIVE, content="ACTUAL: run_unit_tests()",
            version=1, created_at=0,
        )
        store.get_active = lambda: list(store._skills.values())

        class SimpleProvider(BaseProvider):
            def get_model(self, o=None): return "simple"
            async def close(self): pass
            async def chat_completion(self, m, tools=None, **kw):
                return ProviderResponse(content="ok")

        registry = ToolRegistry()
        router = Router(registry, providers=SimpleProvider(), skill_store=store)
        msgs = router._get_or_init_history("test-defer")
        prompt = msgs[0]["content"]
        assert "[Learned Skills" in prompt
        assert "skill_tool" in prompt.lower()
        assert "run_unit_tests()" not in prompt
