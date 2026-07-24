"""
Tests for core/policy.py + core/tool_spec.py.

Covers: ToolPolicy, RateLimitTracker, ToolProfile, pre-built profiles,
and ToolSpec integration.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.categories import ToolCategory
from core.policy import (
    CODING_PROFILE,
    READONLY_PROFILE,
    SAFE_PROFILE,
    RateLimitTracker,
    ToolPolicy,
    ToolProfile,
)
from core.tool_spec import ToolSpec


# ═══════════════════════════════════════════════════════════════════
# ToolPolicy
# ═══════════════════════════════════════════════════════════════════

class TestToolPolicy:
    def test_default_enabled(self):
        policy = ToolPolicy()
        assert policy.enabled is True

    def test_default_no_rate_limit(self):
        policy = ToolPolicy()
        assert policy.rate_limit is None

    def test_default_no_timeout(self):
        policy = ToolPolicy()
        assert policy.timeout is None

    def test_default_no_confirm(self):
        policy = ToolPolicy()
        assert policy.require_confirm is False

    def test_custom_values(self):
        policy = ToolPolicy(enabled=False, require_confirm=True, rate_limit=5.0, timeout=30.0)
        assert policy.enabled is False
        assert policy.require_confirm is True
        assert policy.rate_limit == 5.0
        assert policy.timeout == 30.0

    def test_disabled_tool_blocked(self):
        policy = ToolPolicy(enabled=False)
        assert policy.enabled is False


# ═══════════════════════════════════════════════════════════════════
# RateLimitTracker
# ═══════════════════════════════════════════════════════════════════

class TestRateLimitTracker:
    @pytest.fixture
    def tracker(self) -> RateLimitTracker:
        return RateLimitTracker()

    def test_first_call_allowed(self, tracker: RateLimitTracker):
        allowed, wait = tracker.check("read_file", rate_limit=5.0)
        assert allowed is True
        assert wait == 0.0

    def test_denied_within_limit(self, tracker: RateLimitTracker):
        tracker.record("read_file")
        allowed, wait = tracker.check("read_file", rate_limit=5.0)
        assert allowed is False
        assert wait > 0.0
        assert wait <= 5.0

    def test_allowed_after_limit(self, tracker: RateLimitTracker):
        """After rate_limit seconds, the tool is allowed again."""
        tracker.record("read_file")
        # Simulate time passing by directly setting _last_called to far past
        tracker._last_called["read_file"] = time.monotonic() - 10.0
        allowed, wait = tracker.check("read_file", rate_limit=5.0)
        assert allowed is True
        assert wait == 0.0

    def test_different_tools_independent(self, tracker: RateLimitTracker):
        tracker.record("read_file")
        allowed, wait = tracker.check("write_file", rate_limit=1.0)
        assert allowed is True

    def test_no_rate_limit_passes(self, tracker: RateLimitTracker):
        """rate_limit=None means no rate limit."""
        allowed, wait = tracker.check("tool", rate_limit=None)
        # Should not crash — rate_limit=None is handled
        assert allowed is True

    def test_zero_rate_limit_passes(self, tracker: RateLimitTracker):
        """rate_limit=0 means no delay."""
        allowed, wait = tracker.check("tool", rate_limit=0.0)
        assert allowed is True


# ═══════════════════════════════════════════════════════════════════
# ToolProfile
# ═══════════════════════════════════════════════════════════════════

class TestToolProfile:
    def test_default_name(self):
        profile = ToolProfile()
        assert profile.name == "default"

    def test_empty_rules(self):
        profile = ToolProfile()
        assert profile.is_enabled("any_tool", True) is True
        assert profile.is_enabled("any_tool", False) is False

    def test_custom_rules(self):
        profile = ToolProfile(name="custom", rules={"danger": False, "safe": True})
        assert profile.is_enabled("danger", True) is False
        assert profile.is_enabled("safe", False) is True

    def test_fallback_to_default(self):
        """Tools not in rules fall back to the default."""
        profile = ToolProfile(rules={"write_file": False})
        assert profile.is_enabled("read_file", True) is True
        assert profile.is_enabled("write_file", True) is False


# ═══════════════════════════════════════════════════════════════════
# Pre-built profiles
# ═══════════════════════════════════════════════════════════════════

class TestPrebuiltProfiles:
    def test_safe_profile_disables_dangerous_tools(self):
        assert SAFE_PROFILE.is_enabled("execute_command", True) is False
        assert SAFE_PROFILE.is_enabled("write_file", True) is False
        assert SAFE_PROFILE.name == "safe"

    def test_coding_profile_enables_dev_tools(self):
        assert CODING_PROFILE.is_enabled("execute_command", False) is True
        assert CODING_PROFILE.is_enabled("write_file", False) is True
        assert CODING_PROFILE.is_enabled("read_file", False) is True
        assert CODING_PROFILE.is_enabled("web_search", False) is True
        assert CODING_PROFILE.name == "coding"

    def test_readonly_profile_blocks_writes(self):
        assert READONLY_PROFILE.is_enabled("execute_command", True) is False
        assert READONLY_PROFILE.is_enabled("write_file", True) is False
        assert READONLY_PROFILE.name == "readonly"


# ═══════════════════════════════════════════════════════════════════
# ToolSpec integration
# ═══════════════════════════════════════════════════════════════════

class TestToolSpec:
    def test_default_category(self):
        async def handler() -> str:
            return "ok"

        spec = ToolSpec(name="test", description="a test", parameters={}, handler=handler)
        assert spec.category == ToolCategory.ENV

    def test_default_policy(self):
        async def handler() -> str:
            return "ok"

        spec = ToolSpec(name="test", description="a test", parameters={}, handler=handler)
        assert spec.policy.enabled is True
        assert spec.policy.rate_limit is None

    def test_custom_policy(self):
        async def handler() -> str:
            return "ok"

        policy = ToolPolicy(enabled=False, rate_limit=10.0)
        spec = ToolSpec(
            name="restricted", description="a restricted tool",
            parameters={}, handler=handler, policy=policy,
        )
        assert spec.policy.enabled is False
        assert spec.policy.rate_limit == 10.0

    def test_custom_category(self):
        async def handler() -> str:
            return "ok"

        spec = ToolSpec(
            name="web", description="web search", parameters={},
            handler=handler, category=ToolCategory.COLLAB,
        )
        assert spec.category == ToolCategory.COLLAB

    def test_handler_can_be_called(self):
        """The handler function is callable via spec."""
        storage = []

        async def handler(arg: str) -> str:
            storage.append(arg)
            return f"processed: {arg}"

        spec = ToolSpec(
            name="store", description="store a value", parameters={"arg": {"type": "string"}},
            handler=handler,
        )

        import asyncio
        assert asyncio.run(spec.handler("hello")) == "processed: hello"
        assert storage == ["hello"]
