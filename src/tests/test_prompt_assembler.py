"""P4a tests — SystemPromptAssembler five-layer prompt builder."""

from __future__ import annotations

import datetime

import pytest

from core.prompt_assembler import (
    BuildContext,
    SystemPromptAssembler,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def assembler() -> SystemPromptAssembler:
    return SystemPromptAssembler(identity_text="I am TestBot.")


@pytest.fixture
def ctx() -> BuildContext:
    return BuildContext(
        session_id="test-001",
        role="default",
        extra_rules="",
        now=datetime.datetime(2026, 6, 11, 12, 0, 0),
        tz="Asia/Hong_Kong",
        model_name="test-model",
        workspace_root="/tmp/test-haven",
    )


# ── BuildContext ─────────────────────────────────────────────────────────────

class TestBuildContext:
    def test_defaults(self):
        ctx = BuildContext()
        assert ctx.session_id == "default"
        assert ctx.role == "default"
        assert ctx.extra_rules == ""
        assert ctx.model_name != ""  # falls back to config

    def test_explicit_values(self, ctx):
        assert ctx.session_id == "test-001"
        assert ctx.role == "default"
        assert ctx.now == datetime.datetime(2026, 6, 11, 12, 0, 0)
        assert ctx.tz == "Asia/Hong_Kong"
        assert ctx.model_name == "test-model"
        assert ctx.workspace_root == "/tmp/test-haven"


# ── Basic assembly ───────────────────────────────────────────────────────────

class TestAssemblyBasic:
    def test_build_returns_non_empty_string(self, assembler):
        prompt = assembler.build()
        assert len(prompt) > 0

    def test_default_build_has_identity(self, assembler):
        prompt = assembler.build()
        assert "I am TestBot." in prompt

    def test_default_build_has_runtime(self, assembler):
        prompt = assembler.build(session_id="abc")
        assert "Session: abc" in prompt

    def test_default_build_has_tool_guidance(self, assembler):
        prompt = assembler.build()
        assert "[Tools]" in prompt

    def test_empty_identity_produces_valid_prompt(self):
        assembler = SystemPromptAssembler(identity_text="")
        prompt = assembler.build()
        assert len(prompt) > 0
        assert "[Runtime]" in prompt


# ── Layer content tests ──────────────────────────────────────────────────────

class TestLayerContent:
    def test_runtime_layer_contains_session_id(self, assembler):
        prompt = assembler.build(session_id="sess-42")
        assert "Session: sess-42" in prompt

    def test_runtime_layer_contains_date(self, assembler):
        prompt = assembler.build(now=datetime.datetime(2026, 1, 1, 0, 0, 0))
        assert "2026-01-01 00:00" in prompt

    def test_runtime_layer_contains_tz(self, assembler):
        prompt = assembler.build(tz="Asia/Hong_Kong")
        assert "Asia/Hong_Kong" in prompt

    def test_runtime_layer_contains_model(self, assembler):
        prompt = assembler.build(model_name="gpt-99")
        assert "Model: gpt-99" in prompt

    def test_user_rules_empty_by_default(self, assembler):
        prompt = assembler.build()
        assert "[Additional Rules]" not in prompt

    def test_user_rules_injected_when_provided(self, assembler):
        prompt = assembler.build(extra_rules="Be extra careful.\nNo deleting files.")
        assert "[Additional Rules]" in prompt
        assert "Be extra careful." in prompt
        assert "No deleting files." in prompt

    def test_role_default(self, assembler):
        prompt = assembler.build(role="default")
        assert "[Role: default]" in prompt
        assert "helpful assistant" in prompt.lower()

    def test_role_coding(self, assembler):
        prompt = assembler.build(role="coding")
        assert "[Role: coding]" in prompt
        assert "coding assistant" in prompt.lower()

    def test_role_research(self, assembler):
        prompt = assembler.build(role="research")
        assert "[Role: research]" in prompt
        assert "research assistant" in prompt.lower()

    def test_unknown_role_falls_back_to_default(self, assembler):
        prompt = assembler.build(role="nonexistent")
        assert "[Role: nonexistent]" in prompt
        # uses default guidance
        assert "helpful assistant" in prompt.lower()


# ── Layer management ─────────────────────────────────────────────────────────

class TestLayerManagement:
    def test_register_new_layer(self, assembler):
        def safety_layer(ctx):
            return "[Safety]\nNever rm -rf /."
        assembler.register_layer("safety", safety_layer, after="runtime")
        prompt = assembler.build()
        assert "[Safety]" in prompt
        # verify order: identity → runtime → safety → ...
        idx_runtime = prompt.index("[Runtime]")
        idx_safety = prompt.index("[Safety]")
        assert idx_runtime < idx_safety

    def test_register_without_after_appends_to_end(self, assembler):
        def extra_layer(ctx):
            return "[Extra]"
        assembler.register_layer("extra", extra_layer)
        prompt = assembler.build()
        assert prompt.endswith("[Extra]")

    def test_replace_existing_layer(self, assembler):
        def new_tool_layer(ctx):
            return "[Tools]\nno tools available."
        assembler.register_layer("tool", new_tool_layer)
        prompt = assembler.build()
        assert "no tools available." in prompt

    def test_remove_layer(self, assembler):
        assembler.remove_layer("user_rules")
        prompt = assembler.build()
        assert "[Additional Rules]" not in prompt

    def test_remove_nonexistent_layer_no_error(self, assembler):
        assembler.remove_layer("ghost_layer")  # should not raise

    def test_set_order(self, assembler):
        assembler.set_order("tool", "role", "runtime", "identity", "user_rules")
        prompt = assembler.build(session_id="x", extra_rules="rule")
        # tool should come before role
        idx_tool = prompt.index("[Tools]")
        idx_role = prompt.index("[Role: default]")
        assert idx_tool < idx_role

    def test_set_order_unknown_layer_raises(self, assembler):
        with pytest.raises(KeyError, match="ghost"):
            assembler.set_order("ghost", "identity")

    def test_layers_property(self, assembler):
        layers = assembler.layers
        assert "identity" in layers
        assert "runtime" in layers
        assert "tool" in layers
        assert callable(layers["runtime"])

    def test_order_property(self, assembler):
        assert len(assembler.order) == 5
        assert assembler.order[0] == "identity"


# ── Session-by-session variance ──────────────────────────────────────────────

class TestSessionVariance:
    def test_different_sessions_get_different_runtime(self, assembler):
        p1 = assembler.build(session_id="aaa")
        p2 = assembler.build(session_id="bbb")
        assert "Session: aaa" in p1
        assert "Session: bbb" in p2

    def test_different_roles_produce_different_output(self, assembler):
        p_code = assembler.build(role="coding")
        p_research = assembler.build(role="research")
        assert p_code != p_research

    def test_extra_rules_do_not_leak_across_builds(self, assembler):
        _ = assembler.build(extra_rules="secret rule")
        prompt2 = assembler.build()
        assert "[Additional Rules]" not in prompt2


# ── Integration: backward-compatible Router fallback ─────────────────────────

class TestRouterFallback:
    """Router without prompt_assembler falls back to system_prompt string.

    These tests verify that the P4a assembler is optional and existing
    code that passes system_prompt=... continues to work.
    """

    async def test_router_without_assembler_uses_system_prompt(self):
        from core.router import Router
        from core.tool_registry import ToolRegistry
        from core.base_provider import BaseProvider

        class FakeProvider(BaseProvider):
            def get_model(self) -> str:
                return "fake"
            async def chat_completion(self, messages, tools=None, timeout=30, **kw):
                return {"choices": [{"message": {"content": "hi"}}]}
            async def close(self) -> None:
                pass

        registry = ToolRegistry()
        router = Router(
            registry,
            providers=FakeProvider(),
            system_prompt="Custom flat prompt",
        )
        # Access history to trigger prompt assembly
        msgs = router._get_or_init_history("test-sid")
        system_msg = msgs[0]
        assert system_msg["role"] == "system"
        assert "Custom flat prompt" in system_msg["content"]

    async def test_router_with_assembler_uses_layered_prompt(self):
        from core.router import Router
        from core.tool_registry import ToolRegistry
        from core.base_provider import BaseProvider

        class FakeProvider(BaseProvider):
            def get_model(self) -> str:
                return "fake"
            async def chat_completion(self, messages, tools=None, timeout=30, **kw):
                return {"choices": [{"message": {"content": "hi"}}]}
            async def close(self) -> None:
                pass

        assembler = SystemPromptAssembler(identity_text="LayeredBot")
        registry = ToolRegistry()
        router = Router(
            registry,
            providers=FakeProvider(),
            prompt_assembler=assembler,
        )
        msgs = router._get_or_init_history("test-sid")
        system_msg = msgs[0]
        assert system_msg["role"] == "system"
        assert "LayeredBot" in system_msg["content"]
        assert "[Runtime]" in system_msg["content"]
        assert "[Role: default]" in system_msg["content"]
