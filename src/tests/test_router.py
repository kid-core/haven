"""
Router (ReAct loop) state-machine tests.

Uses FakeProvider from conftest.py so every path through the ReAct loop
can be tested deterministically without an actual LLM.
"""

from __future__ import annotations

import pytest
from core.models import ProviderResponse

from conftest import FakeProvider, FailingProvider


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def registry():
    """Populated ToolRegistry singleton."""
    import tools  # noqa: F401 — triggers @tool registration
    from core.tool_decorator import get_default_registry
    return get_default_registry()


@pytest.fixture
def router(registry, fake_provider):
    """Router with one FakeProvider and registry."""
    from core.router import Router
    return Router(registry, providers=[(fake_provider, None)])


# ======================================================================
# Tests: Simple text response
# ======================================================================

class TestRouterText:
    """Router behaviour when the model returns text directly."""

    async def test_simple_text_response(self, router, fake_provider):
        fake_provider.add_response(content="Hello, world!")
        result = await router.process("Hi")
        assert "Hello" in result

    async def test_text_ends_loop_immediately(self, router, fake_provider):
        """Text response → no tool execution → exactly one LLM call."""
        fake_provider.add_response(content="Done")
        await router.process("Hi")
        assert fake_provider.call_count == 1

    async def test_multiple_text_turns(self, registry):
        """Two separate process() calls maintain history."""
        from core.router import Router

        provider = FakeProvider(responses=[
            ProviderResponse(content="Response 1"),
            ProviderResponse(content="Response 2"),
        ])
        router = Router(registry, providers=[(provider, None)])

        r1 = await router.process("Msg 1")
        assert r1 == "Response 1"

        r2 = await router.process("Msg 2")
        assert r2 == "Response 2"

    async def test_empty_user_message(self, router, fake_provider):
        fake_provider.add_response(content="Empty processed")
        result = await router.process("")
        assert "Empty processed" in result

    async def test_system_prompt_injected_on_first_turn(self, registry):
        """First turn should include system prompt in messages."""
        from core.router import Router

        provider = FakeProvider(responses=[
            ProviderResponse(content="ok"),
        ])
        system = "You are a helpful assistant."
        router = Router(registry, providers=[(provider, None)], system_prompt=system)

        await router.process("Hi")

        assert provider.last_messages is not None
        roles = [m["role"] for m in provider.last_messages]
        assert roles[0] == "system"
        # System prompt is augmented with tool list + model info, but should contain our text
        assert system in provider.last_messages[0]["content"]


# ======================================================================
# Tests: Turn limits
# ======================================================================

class TestTurnLimits:
    """Router respects max_turns."""

    TOOL_CALL = ProviderResponse(
        content=None,
        tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "execute_command", "arguments": '{"cmd": "echo hi"}'},
        }],
    )

    async def test_max_turns_exceeded(self, registry):
        """Provider keeps returning tool_calls → hit max_turns."""
        from core.router import TURN_LIMIT_MESSAGE, Router

        provider = FakeProvider(responses=[
            self.TOOL_CALL, self.TOOL_CALL, self.TOOL_CALL,
        ])
        router = Router(registry, providers=[(provider, None)])

        result = await router.process("Do something", max_turns=2)
        assert result == TURN_LIMIT_MESSAGE

    async def test_max_turns_call_count(self, registry):
        """At max_turns, the loop stops after max_turns LLM calls."""
        from core.router import TURN_LIMIT_MESSAGE, Router

        provider = FakeProvider(responses=[
            self.TOOL_CALL, self.TOOL_CALL, self.TOOL_CALL,
        ])
        router = Router(registry, providers=[(provider, None)])

        result = await router.process("Loop", max_turns=2)
        assert result == TURN_LIMIT_MESSAGE
        # With max_turns=2, LLM called for turn 1 (tool) and turn 2 (limit)
        assert provider.call_count <= 3

    async def test_single_turn_allows_tool_and_text(self, registry):
        """max_turns=3 should allow tool+tool+text flow."""
        from core.router import Router

        provider = FakeProvider(responses=[
            self.TOOL_CALL,
            self.TOOL_CALL,
            ProviderResponse(content="Done"),
        ])
        router = Router(registry, providers=[(provider, None)])

        result = await router.process("Complex", max_turns=5)
        assert result == "Done"


# ======================================================================
# Tests: Provider fallback
# ======================================================================

class TestProviderFallback:
    """Router's provider chain fallback behaviour."""

    async def test_single_provider_succeeds(self, registry):
        """One provider, no failure → works."""
        from core.router import Router
        provider = FakeProvider(responses=[ProviderResponse(content="OK")])
        router = Router(registry, providers=[(provider, None)])
        result = await router.process("Hi")
        assert result == "OK"

    async def test_primary_failure_falls_to_secondary(self, registry):
        """Primary fails → secondary takes over."""
        from core.router import Router
        primary = FakeProvider(responses=[ProviderResponse(content="should not")])
        secondary = FakeProvider(responses=[ProviderResponse(content="Fallback worked")])
        primary.set_should_fail(True, error="HTTP 500")

        router = Router(registry, providers=[(primary, None), (secondary, None)])
        result = await router.process("Hi")

        assert result == "Fallback worked"
        assert primary.call_count >= 1
        assert secondary.call_count == 1

    async def test_primary_called_before_secondary(self, registry):
        """Primary tried first, secondary only called after primary fails."""
        from core.router import Router
        primary = FakeProvider()
        secondary = FakeProvider(responses=[ProviderResponse(content="Fallback")])
        primary.set_should_fail(True)

        router = Router(registry, providers=[(primary, None), (secondary, None)])
        await router.process("Hi")

        assert primary.call_count == 1
        assert secondary.call_count == 1

    async def test_all_providers_fail_returns_error(self, registry):
        """All providers fail → error message."""
        from core.router import Router

        router = Router(registry, providers=[
            (FailingProvider(), None),
            (FailingProvider(), None),
        ])
        result = await router.process("Hi")
        assert "All providers failed" in result

    async def test_fallback_preserves_messages(self, registry):
        """Fallback provider should receive the same messages primary got."""
        from core.router import Router

        primary = FakeProvider()
        secondary = FakeProvider(responses=[ProviderResponse(content="Fallback")])
        primary.set_should_fail(True)

        router = Router(registry, providers=[(primary, None), (secondary, None)])
        await router.process("Hello there")

        assert secondary.last_messages is not None
        roles = [m["role"] for m in secondary.last_messages]
        assert "user" in roles
        assert any("Hello there" in str(m.get("content", "")) for m in secondary.last_messages)

    async def test_provider_chain_respects_order(self, registry):
        """Providers tried in list order, not random."""
        from core.router import Router

        p1 = FakeProvider(); p1.set_should_fail(True)
        p2 = FakeProvider(responses=[ProviderResponse(content="P2")])
        p3 = FakeProvider(responses=[ProviderResponse(content="P3")])

        router = Router(registry, providers=[(p1, None), (p2, None), (p3, None)])
        result = await router.process("Hi")

        assert result == "P2"
        assert p2.call_count == 1
        assert p3.call_count == 0  # P2 succeeded, P3 never called


# ======================================================================
# Tests: Tool execution
# ======================================================================

class TestToolExecution:
    """Router executes tools and feeds results back to the model."""

    EXEC_CALL = {
        "id": "call_exec",
        "type": "function",
        "function": {
            "name": "execute_command",
            "arguments": '{"cmd": "echo tool_ok"}',
        },
    }

    async def test_single_tool_call(self, registry):
        """Tool call → execute → result back to LLM → LLM replies."""
        from core.router import Router

        provider = FakeProvider(responses=[
            ProviderResponse(content=None, tool_calls=[self.EXEC_CALL]),
            ProviderResponse(content="Command executed"),
        ])
        router = Router(registry, providers=[(provider, None)])

        result = await router.process("Run echo", max_turns=5)
        assert "Command" in result or "tool_ok" in result
        assert provider.call_count == 2

    async def test_tool_result_sent_to_llm(self, registry):
        """Tool execution result appears in the next LLM call's messages.

        Uses read_file to avoid rate-limit conflicts with execute_command.
        """
        from core.router import Router

        read_call = {
            "id": "call_read",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path": "/tmp/test_router_output.txt"}',
            },
        }

        provider = FakeProvider(responses=[
            ProviderResponse(content=None, tool_calls=[read_call]),
            ProviderResponse(content="File content received"),
        ])
        router = Router(registry, providers=[(provider, None)])
        await router.process("Read", max_turns=5)

        # Second LLM call should include tool role message
        assert provider.last_messages is not None
        tool_msgs = [m for m in provider.last_messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1

    async def test_tool_error_reported_to_llm(self, registry):
        """Tool that fails → error info sent to LLM, not a crash."""
        from core.router import Router

        nonexistent_call = {
            "id": "call_err",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path": "/tmp/nonexistent_test_router_file_xyz.txt"}',
            },
        }

        provider = FakeProvider(responses=[
            ProviderResponse(content=None, tool_calls=[nonexistent_call]),
            ProviderResponse(content="I couldn't read that file."),
        ])
        router = Router(registry, providers=[(provider, None)])
        result = await router.process("Read missing file", max_turns=5)

        assert result == "I couldn't read that file."

        # Second call should include tool error information
        assert provider.last_messages is not None
        tool_msgs = [m for m in provider.last_messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert "error" in tool_msgs[0]["content"].lower() or "not found" in tool_msgs[0]["content"].lower()

    async def test_unknown_tool_returns_error(self, registry):
        """Unknown tool name → error in tool result."""
        from core.router import Router

        provider = FakeProvider(responses=[
            ProviderResponse(
                content=None,
                tool_calls=[{
                    "id": "call_unknown",
                    "type": "function",
                    "function": {"name": "nonexistent_tool", "arguments": "{}"},
                }],
            ),
            ProviderResponse(content="Tool error handled"),
        ])
        router = Router(registry, providers=[(provider, None)])

        result = await router.process("Use unknown tool", max_turns=5)
        assert isinstance(result, str)
        assert provider.call_count == 2

    async def test_multiple_tools_in_one_turn(self, registry):
        """Multiple tool calls in one LLM response → all executed."""
        from core.router import Router

        provider = FakeProvider(responses=[
            ProviderResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "execute_command",
                            "arguments": '{"cmd": "echo first"}',
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "execute_command",
                            "arguments": '{"cmd": "echo second"}',
                        },
                    },
                ],
            ),
            ProviderResponse(content="Both executed"),
        ])
        router = Router(registry, providers=[(provider, None)])

        result = await router.process("Run two tools", max_turns=5)
        assert result == "Both executed"
        assert provider.call_count == 2

    async def test_tool_timeout_does_not_crash(self, registry):
        """Tool that times out → graceful error, not crash."""
        from core.router import Router

        # Use a tool with a very short timeout
        from core.tool_decorator import get_default_registry
        reg = get_default_registry()
        spec = reg.get("execute_command")
        assert spec is not None, "execute_command should be registered"

        provider = FakeProvider(responses=[
            ProviderResponse(
                content=None,
                tool_calls=[{
                    "id": "call_timeout",
                    "type": "function",
                    "function": {
                        "name": "background_task",
                        "arguments": '{"cmd": "sleep 100", "timeout": 0.001}',
                    },
                }],
            ),
            ProviderResponse(content="Timed out gracefully"),
        ])
        router = Router(registry, providers=[(provider, None)])

        result = await router.process("Timeout test", max_turns=5)
        assert isinstance(result, str)

    async def test_confirm_required_not_executed(self, registry):
        """Tool requiring confirmation should return confirm message, not execute."""
        from core.router import Router

        provider = FakeProvider(responses=[
            ProviderResponse(
                content=None,
                tool_calls=[{
                    "id": "call_confirm",
                    "type": "function",
                    "function": {
                        "name": "execute_command",
                        "arguments": '{"cmd": "rm -rf /tmp/test"}',
                    },
                }],
            ),
            ProviderResponse(content="Confirmed"),
        ])
        router = Router(registry, providers=[(provider, None)])

        result = await router.process("Delete", max_turns=5)
        assert result == "Confirmed"


# ======================================================================
# Tests: Reasoning content
# ======================================================================

class TestReasoningContent:
    """reasoning_content is preserved in messages."""

    async def test_reasoning_content_preserved_in_history(self, registry):
        """reasoning_content stored in assistant message."""
        from core.router import Router
        provider = FakeProvider(responses=[
            ProviderResponse(content="Final answer", reasoning_content="Step-by-step reasoning"),
        ])
        router = Router(registry, providers=[(provider, None)])

        result = await router.process("Think step by step")
        assert result == "Final answer"

        history = router._get_or_init_history("default")
        assistant_msg = history[-1]
        assert assistant_msg["role"] == "assistant"
        assert "reasoning_content" in assistant_msg


# ======================================================================
# Tests: Session management
# ======================================================================

class TestSessionManagement:
    """Session isolation, history clear, and state."""

    async def test_clear_history(self, registry):
        """clear_history should wipe the session."""
        from core.router import Router
        provider = FakeProvider(responses=[ProviderResponse(content="Response")])
        router = Router(registry, providers=[(provider, None)])

        await router.process("Msg 1")
        assert len(router._get_or_init_history("default")) >= 3

        router.clear_history("default")
        hist = router._get_or_init_history("default")
        assert len(hist) == 1  # only the system prompt

    async def test_session_isolation(self, registry):
        """Two sessions have independent histories."""
        from core.router import Router
        provider = FakeProvider(responses=[
            ProviderResponse(content="Session A"),
            ProviderResponse(content="Session B"),
        ])
        router = Router(registry, providers=[(provider, None)])

        r1 = await router.process("First", session_id="session_a")
        r2 = await router.process("Second", session_id="session_b")

        assert r1 == "Session A"
        assert r2 == "Session B"

    async def test_new_session_empty_history(self, router, fake_provider):
        """New session_id has an empty fresh history."""
        fake_provider.add_response(content="ok")
        await router.process("Hi", session_id="fresh")
        # Should work without error

    async def test_default_session_id_used(self, router, fake_provider):
        """No session_id → 'default' used."""
        fake_provider.add_response(content="ok")
        await router.process("Hi")
        hist = router._get_or_init_history("default")
        assert len(hist) >= 2


# ======================================================================
# Tests: SessionStore integration
# ======================================================================

class TestSessionStoreIntegration:
    """Router persists history when a SessionStore is injected."""

    @pytest.fixture
    def store(self, tmp_path):
        from soul.memory import SessionStore
        return SessionStore(session_dir=tmp_path, max_messages=10)

    async def test_persists_history_after_process(self, registry, store):
        from core.router import Router
        provider = FakeProvider(responses=[ProviderResponse(content="Hello persisted!")])
        router = Router(registry, providers=[(provider, None)], session_store=store)
        await router.process("Test", session_id="persist_test")

        loaded = store.load("persist_test")
        assert len(loaded) > 1
        assert loaded[-1]["role"] == "assistant"
        assert loaded[-1]["content"] == "Hello persisted!"

    async def test_loads_history_on_new_router(self, registry, store):
        from core.router import Router

        provider_a = FakeProvider(responses=[ProviderResponse(content="Turn 1")])
        router_a = Router(registry, providers=[(provider_a, None)], session_store=store)
        await router_a.process("First", session_id="restore_test")

        provider_b = FakeProvider(responses=[ProviderResponse(content="Turn 2")])
        router_b = Router(registry, providers=[(provider_b, None)], session_store=store)
        result = await router_b.process("Second", session_id="restore_test")

        assert result == "Turn 2"
        assert provider_b.call_count == 1

    async def test_clear_history_clears_store(self, registry, store):
        from core.router import Router
        provider = FakeProvider(responses=[ProviderResponse(content="Saved")])
        router = Router(registry, providers=[(provider, None)], session_store=store)
        await router.process("Hi", session_id="clear_test")
        assert len(store.load("clear_test")) > 0

        router.clear_history("clear_test")
        assert len(store.load("clear_test")) == 0


# ======================================================================
# Tests: concurrent sessions
# ======================================================================

class TestConcurrentSessions:
    """Multiple sessions running process() simultaneously."""

    async def test_two_sessions_independent(self, registry):
        """Two sessions in parallel do not interfere.

        Each session gets its own provider to simulate real concurrent API calls.
        """
        from core.router import Router

        p_a = FakeProvider(responses=[ProviderResponse(content="Hello A")])
        p_b = FakeProvider(responses=[ProviderResponse(content="Hello B")])

        router_a = Router(registry, providers=[(p_a, None)])
        router_b = Router(registry, providers=[(p_b, None)])

        import asyncio

        async def session_a():
            return await router_a.process("msg for A", session_id="sess_a")

        async def session_b():
            return await router_b.process("msg for B", session_id="sess_b")

        r_a, r_b = await asyncio.gather(session_a(), session_b())
        assert r_a == "Hello A"
        assert r_b == "Hello B"
        assert p_a.call_count == 1
        assert p_b.call_count == 1

    async def test_two_sessions_same_router(self, registry):
        """Two sessions, same router, same provider — sequential processing works."""
        from core.router import Router

        provider = FakeProvider(responses=[
            ProviderResponse(content="First"),
            ProviderResponse(content="Second"),
        ])
        router = Router(registry, providers=[(provider, None)])

        # Sequential, not concurrent — each session gets its turn
        r1 = await router.process("msg 1", session_id="sess_1")
        r2 = await router.process("msg 2", session_id="sess_2")
        assert r1 == "First"
        assert r2 == "Second"

    async def test_same_session_multiple_turns(self, registry):
        """Same session, multiple turns preserves context."""
        from core.router import Router

        provider = FakeProvider(responses=[
            ProviderResponse(content="Turn 1"),
            ProviderResponse(content="Turn 2"),
        ])
        router = Router(registry, providers=[(provider, None)])

        r1 = await router.process("first", session_id="multi")
        r2 = await router.process("second", session_id="multi")
        assert r1 == "Turn 1"
        assert r2 == "Turn 2"
