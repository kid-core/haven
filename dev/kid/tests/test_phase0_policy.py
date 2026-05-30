"""Phase 0 tests — ToolCategory, ToolPolicy, Registry policy enforcement."""

import pytest
from core.categories import ToolCategory
from core.policy import CODING_PROFILE, SAFE_PROFILE, RateLimitTracker, ToolPolicy
from core.tool_registry import PolicyBlockedError, ToolRegistry
from core.tool_spec import ToolSpec


class TestToolCategory:
    def test_all_categories_defined(self):
        names = {c.name for c in ToolCategory}
        assert "FILES" in names
        assert "SYSTEM" in names
        assert "WEB" in names
        assert "AI" in names
        assert "COMMUNICATION" in names
        assert "MEMORY" in names
        assert "EXTERNAL" in names

    def test_default_policy(self):
        for cat in ToolCategory:
            p = cat.default_policy()
            assert isinstance(p, ToolPolicy)
            assert p.enabled is True

    def test_category_defaults_sensible(self):
        assert ToolCategory.SYSTEM.default_policy().require_confirm is True
        assert ToolCategory.WEB.default_policy().require_confirm is False
        assert ToolCategory.AI.default_policy().timeout == 60.0


class TestToolPolicy:
    def test_defaults(self):
        p = ToolPolicy()
        assert p.enabled is True
        assert p.require_confirm is False
        assert p.rate_limit is None
        assert p.timeout is None

    def test_custom(self):
        p = ToolPolicy(require_confirm=True, timeout=30, rate_limit=10)
        assert p.require_confirm is True
        assert p.timeout == 30
        assert p.rate_limit == 10


class TestToolProfile:
    def test_safe_profile_blocks_cmd(self):
        assert SAFE_PROFILE.is_enabled("execute_command", True) is False

    def test_safe_profile_allows_search(self):
        assert SAFE_PROFILE.is_enabled("web_search", True) is True

    def test_coding_profile_allows_all(self):
        assert CODING_PROFILE.is_enabled("execute_command", False) is True
        assert CODING_PROFILE.is_enabled("write_file", False) is True


class TestRateLimitTracker:
    def test_allows_first_call(self):
        tracker = RateLimitTracker()
        ok, _ = tracker.check("cmd", 10.0)
        assert ok is True

    def test_blocks_second_call(self):
        tracker = RateLimitTracker()
        tracker.record("cmd")
        ok, wait = tracker.check("cmd", 10.0)
        assert ok is False
        assert wait > 0

    def test_allows_after_cooldown(self):
        import time
        tracker = RateLimitTracker()
        tracker.record("cmd")
        # Hack: override last time to simulate cooldown
        tracker._last_called["cmd"] = time.monotonic() - 20
        ok, _ = tracker.check("cmd", 10.0)
        assert ok is True


class TestToolRegistryPolicy:
    async def _echo(self, **kw):
        return "ok"

    def test_confirm_required_detection(self):
        reg = ToolRegistry()
        spec = ToolSpec("test", "", {}, self._echo, ToolCategory.SYSTEM,
                        ToolPolicy(require_confirm=True))
        reg.add(spec)
        assert reg.is_confirm_required("test") is True

    def test_disabled_tool_blocked(self):
        reg = ToolRegistry()
        reg.add(ToolSpec("disabled", "", {}, self._echo, ToolCategory.FILES,
                         ToolPolicy(enabled=False)))
        ok, reason = reg.check_policy("disabled")
        assert ok is False
        assert "disabled" in reason.lower()

    def test_openai_tools_excludes_disabled(self):
        reg = ToolRegistry()
        reg.add(ToolSpec("a", "", {}, self._echo, ToolCategory.FILES,
                         ToolPolicy(enabled=True)))
        reg.add(ToolSpec("b", "", {}, self._echo, ToolCategory.FILES,
                         ToolPolicy(enabled=False)))
        tools = reg.get_openai_tools()
        names = [t["function"]["name"] for t in tools]
        assert "a" in names
        assert "b" not in names

    @pytest.mark.asyncio
    async def test_policy_blocked_error(self):
        reg = ToolRegistry()
        async def noop(**kw):
            return "ok"
        reg.add(ToolSpec("rl", "", {}, noop, ToolCategory.FILES,
                         ToolPolicy(rate_limit=10.0)))
        # First call passes
        await reg.execute("id1", "rl", {})
        # Second call should block
        with pytest.raises(PolicyBlockedError):
            await reg.execute("id2", "rl", {})
