"""
Security boundary tests for Haven.

Tests cover: tool injection, sensitive data leakage, path traversal,
policy bypass, and rate-limit enforcement.

Marked ``@pytest.mark.security`` for selective runs.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.security


class TestToolInjection:
    """Tool name and argument injection prevention."""

    async def test_unknown_tool_returns_noop(self, router, fake_provider):
        """Unknown tool name returns error, not a crash."""
        fake_provider.add_response(content="ok")
        result = await router.process("Run nonexistent tool", max_turns=5)
        assert isinstance(result, str)

    async def test_tool_name_is_not_executed_directly(self):
        """Tool registry uses name-based dispatch, not eval/exec."""
        from core.categories import ToolCategory
        from core.policy import ToolPolicy
        from core.tool_registry import ToolRegistry
        from core.tool_spec import ToolSpec

        reg = ToolRegistry()
        harm = ToolSpec("safe_name", "", {}, lambda **kw: kw,
                        ToolCategory.ENV, ToolPolicy())
        reg.add(harm)

        spec = reg.get("safe_name")
        assert spec is not None
        spec2 = reg.get("harmful_name")
        assert spec2 is None


class TestRateLimit:
    """Rate-limit enforcement."""

    async def test_rate_limited_tool_blocks_rapid_calls(self):
        """Tool with rate_limit rejects second call within window."""
        from core.policy import RateLimitTracker

        tracker = RateLimitTracker()

        allowed, wait = tracker.check("cmd", rate_limit=10.0)
        assert allowed is True
        tracker.record("cmd")

        allowed, wait = tracker.check("cmd", rate_limit=10.0)
        assert allowed is False
        assert wait > 0

    async def test_rate_limit_expires(self):
        """After cooldown, rate-limited tool is allowed again."""
        import time

        from core.policy import RateLimitTracker

        tracker = RateLimitTracker()
        tracker.record("cmd")

        # Simulate elapsed time past limit
        tracker._last_called["cmd"] = time.monotonic() - 11.0

        allowed, wait = tracker.check("cmd", rate_limit=10.0)
        assert allowed is True
        assert wait == 0.0

    async def test_different_tools_independent_limits(self):
        """Different tools have independent rate limits."""
        from core.policy import RateLimitTracker

        tracker = RateLimitTracker()

        # Record cmd, then immediately check — blocked
        tracker.record("cmd")
        cmd_allowed, _ = tracker.check("cmd", rate_limit=1.0)
        assert cmd_allowed is False

        # read_file not recorded yet — should be allowed
        read_allowed, _ = tracker.check("read_file", rate_limit=1.0)
        assert read_allowed is True
        tracker.record("read_file")

        # Now read_file also blocked
        read_allowed2, _ = tracker.check("read_file", rate_limit=1.0)
        assert read_allowed2 is False


class TestPathTraversal:
    """Path traversal protection in file tools."""

    async def test_read_outside_prefix_rejected(self):
        """read_file should reject paths outside the allowed prefix."""
        from tools.read import read_file

        result = await read_file(path="/etc/passwd")
        assert "error" in result.lower() or "permission" in result.lower() or "denied" in result.lower()

    async def test_read_inside_prefix_allowed(self):
        """read_file should allow paths within the allowed prefix (/mnt/z/)."""
        from pathlib import Path

        from tools.read import read_file

        test_path = Path("/mnt/z/Haven/") / "__security_test_read.txt"
        test_path.write_text("hello security")

        try:
            result = await read_file(path=str(test_path))
            assert "hello security" in result
        finally:
            test_path.unlink(missing_ok=True)

    async def test_write_to_protected_path_rejected(self):
        """write_file should reject writes to protected system paths."""
        from tools.write import write_file

        result = await write_file(path="/etc/hosts", content="evil")
        assert "error" in result.lower() or "denied" in result.lower() or "permission" in result.lower()

    async def test_write_allowed_path_succeeds(self):
        """write_file should allow writes to permitted paths (/mnt/z/)."""
        from pathlib import Path

        from tools.write import write_file

        test_path = Path("/mnt/z/Haven/") / "__security_test_write.txt"

        try:
            result = await write_file(path=str(test_path), content="test data")
            assert "error" not in result.lower()
            assert test_path.read_text() == "test data"
        finally:
            test_path.unlink(missing_ok=True)


class TestPolicyEnforcement:
    """ToolPolicy enforcement at the registry level."""

    async def test_disabled_tool_returns_policy_error(self):
        """Disabled tool returns policy-blocked error message."""
        from core.tool_decorator import get_default_registry

        reg = get_default_registry()

        # Find a disabled tool
        disabled = [name for name, spec in reg._tools.items() if not spec.policy.enabled]
        if not disabled:
            pytest.skip("No disabled tools in default registry")

        result = await reg.execute("call_disabled", disabled[0], {})
        assert "disabled" in result.lower() or "policy" in result.lower()

    async def test_confirm_required_detection(self):
        """Tool with require_confirm=True is flagged."""
        from core.policy import ToolPolicy

        policy = ToolPolicy(require_confirm=True)
        assert policy.require_confirm is True

    async def test_disabled_tool_policy(self):
        """Tool with enabled=False has the flag set."""
        from core.policy import ToolPolicy

        policy = ToolPolicy(enabled=False)
        assert policy.enabled is False

    async def test_memory_search_is_allowed(self):
        """memory_search tool should be accessible."""
        from tools.memory_search import memory_search

        result = await memory_search(action="search", query="test")
        assert isinstance(result, str)
        # Should either return results or a "no results" message, never crash
        assert "error" not in result.lower()

    async def test_read_non_existent_returns_error(self):
        """read_file on non-existent file returns error, not crash."""
        from tools.read import read_file

        result = await read_file(path="/tmp/__nonexistent_security_test_file_xyz.txt")
        assert "error" in result.lower() or "not found" in result.lower()
