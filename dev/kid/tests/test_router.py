"""
Router (ReAct loop) state-machine tests.

Uses a MockProvider that returns controlled ProviderResponse values
so every path through the ReAct loop can be tested deterministically
without an actual LLM.
"""

from __future__ import annotations

import pytest
from core.models import ProviderResponse

# ======================================================================
# Mock providers — duck-typed, no inheritance needed
# ======================================================================

class MockProvider:
    """Returns pre-recorded responses for deterministic testing."""

    def __init__(self, responses: list[ProviderResponse] | None = None):
        self.responses = list(responses) if responses else []
        self.call_count = 0

    async def chat_completion(self, messages, tools=None, temperature=None, max_tokens=None):
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
        else:
            resp = self.responses[-1] if self.responses else ProviderResponse(content="")
        self.call_count += 1
        return resp

    def get_model(self, override=None):
        return "mock-model"

    async def close(self):
        pass


class FailingProvider:
    """Always raises an exception — used for fallback tests."""

    async def chat_completion(self, messages, tools=None, temperature=None, max_tokens=None):
        raise RuntimeError("Simulated provider failure")

    def get_model(self, override=None):
        return "failing-model"

    async def close(self):
        pass


# ======================================================================
# Tests
# ======================================================================

@pytest.fixture
def registry():
    """Populated ToolRegistry singleton."""
    import tools  # noqa: F401 — triggers @tool registration
    from core.tool_decorator import get_default_registry
    return get_default_registry()


class TestRouter:
    """Router ReAct loop tests with MockProvider."""

    def _make_text_provider(self, text: str = "Hello, world!"):
        return MockProvider(responses=[
            ProviderResponse(content=text, tool_calls=None),
        ])

    def _rtup(self, p):
        """Wrap a single provider in the list-of-tuples format the Router expects."""
        return [(p, None)]

    # -- simple text response ------------------------------------------

    @pytest.mark.asyncio
    async def test_simple_text_response(self, registry):
        from core.router import Router

        provider = self._make_text_provider("Hello, world!")
        router = Router(registry, providers=self._rtup(provider))

        result = await router.process("Hi")
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_multiple_text_turns(self, registry):
        """Two separate process() calls maintain history."""
        from core.router import Router

        provider = MockProvider(responses=[
            ProviderResponse(content="Response 1", tool_calls=None),
            ProviderResponse(content="Response 2", tool_calls=None),
        ])
        router = Router(registry, providers=self._rtup(provider))

        r1 = await router.process("Msg 1")
        assert r1 == "Response 1"

        r2 = await router.process("Msg 2")
        assert r2 == "Response 2"

    # -- max turns limit -----------------------------------------------

    @pytest.mark.asyncio
    async def test_max_turns_limit(self, registry):
        """Provider keeps returning tool_calls → should hit max_turns."""
        from core.router import TURN_LIMIT_MESSAGE, Router

        tool_call_response = ProviderResponse(
            content=None,
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "execute_command", "arguments": '{"cmd": "echo hi"}'},
            }],
        )

        provider = MockProvider(responses=[
            tool_call_response,
            tool_call_response,  # tool result sent back → should trigger again
            tool_call_response,  # extra buffer
        ])
        router = Router(registry, providers=self._rtup(provider))

        result = await router.process("Do something", max_turns=2)
        assert result == TURN_LIMIT_MESSAGE

    # -- provider fallback ---------------------------------------------

    @pytest.mark.asyncio
    async def test_provider_fallback_succeeds(self, registry):
        """First provider fails, second should succeed."""
        from core.router import Router

        failing = FailingProvider()
        working = self._make_text_provider("Fallback success")

        router = Router(registry, providers=[(failing, None), (working, None)])

        result = await router.process("Hi")
        assert "Fallback success" in result

    @pytest.mark.asyncio
    async def test_all_providers_fail(self, registry):
        """All providers fail → should return error message."""
        from core.router import Router

        router = Router(registry, providers=[
            (FailingProvider(), None),
            (FailingProvider(), None),
        ])

        result = await router.process("Hi")
        assert "All providers failed" in result

    # -- tool execution -------------------------------------------------

    @pytest.mark.asyncio
    async def test_tool_execution_and_result_returned(self, registry):
        """Router should execute a tool call and feed the result back."""
        from core.router import Router

        provider = MockProvider(responses=[
            ProviderResponse(
                content=None,
                tool_calls=[{
                    "id": "call_exec",
                    "type": "function",
                    "function": {
                        "name": "execute_command",
                        "arguments": '{"cmd": "echo tool_ok"}',
                    },
                }],
            ),
            ProviderResponse(
                content="Command executed successfully",
                tool_calls=None,
            ),
        ])
        router = Router(registry, providers=self._rtup(provider))

        result = await router.process("Run echo", max_turns=5)
        assert "Command" in result or "tool_ok" in result
        assert provider.call_count == 2

    # -- unknown tool ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, registry):
        """Unknown tool name should return error in tool result."""
        from core.router import Router

        provider = MockProvider(responses=[
            ProviderResponse(
                content=None,
                tool_calls=[{
                    "id": "call_unknown",
                    "type": "function",
                    "function": {
                        "name": "nonexistent_tool",
                        "arguments": "{}",
                    },
                }],
            ),
            ProviderResponse(
                content="Tool error handled",
                tool_calls=None,
            ),
        ])
        router = Router(registry, providers=self._rtup(provider))

        result = await router.process("Use unknown tool", max_turns=5)
        assert isinstance(result, str)
        assert provider.call_count == 2

    # -- reasoning content ----------------------------------------------

    @pytest.mark.asyncio
    async def test_reasoning_content_preserved_in_history(self, registry):
        """reasoning_content from provider should be stored in assistant message."""
        from core.router import Router

        provider = MockProvider(responses=[
            ProviderResponse(
                content="Final answer",
                tool_calls=None,
                reasoning_content="Step-by-step reasoning",
            ),
        ])
        router = Router(registry, providers=self._rtup(provider))

        result = await router.process("Think step by step")
        assert result == "Final answer"
        history = router._get_or_init_history("default")
        assert len(history) >= 3  # system + user + assistant
        assistant_msg = history[-1]
        assert assistant_msg["role"] == "assistant"
        assert "reasoning_content" in assistant_msg

    # -- clear history --------------------------------------------------

    @pytest.mark.asyncio
    async def test_clear_history(self, registry):
        """clear_history should wipe the session."""
        from core.router import Router

        provider = self._make_text_provider("Response")
        router = Router(registry, providers=self._rtup(provider))

        await router.process("Msg 1")
        assert len(router._get_or_init_history("default")) >= 3

        router.clear_history("default")
        hist = router._get_or_init_history("default")
        assert len(hist) == 1  # only the system prompt

    # -- string arguments parsing ---------------------------------------

    @pytest.mark.asyncio
    async def test_tool_with_string_arguments(self, registry):
        """Tool calls with string arguments (JSON inside a string) should parse correctly."""
        from core.router import Router

        provider = MockProvider(responses=[
            ProviderResponse(
                content=None,
                tool_calls=[{
                    "id": "call_str_args",
                    "type": "function",
                    "function": {
                        "name": "execute_command",
                        "arguments": '{"cmd": "echo str_args_ok"}',
                    },
                }],
            ),
            ProviderResponse(
                content="String args handled",
                tool_calls=None,
            ),
        ])
        router = Router(registry, providers=self._rtup(provider))

        result = await router.process("Run with string args", max_turns=5)
        assert "String args" in result
        assert provider.call_count == 2

    # -- empty user message ---------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_user_message(self, registry):
        """Empty user message should still be processed."""
        from core.router import Router

        provider = self._make_text_provider("Empty processed")
        router = Router(registry, providers=self._rtup(provider))

        result = await router.process("")
        assert "Empty processed" in result

    # -- session isolation ----------------------------------------------

    @pytest.mark.asyncio
    async def test_session_isolation(self, registry):
        """Two sessions should have independent histories."""
        from core.router import Router

        provider = MockProvider(responses=[
            ProviderResponse(content="Session A", tool_calls=None),
            ProviderResponse(content="Session B", tool_calls=None),
        ])
        router = Router(registry, providers=self._rtup(provider))

        r1 = await router.process("First", session_id="session_a")
        r2 = await router.process("Second", session_id="session_b")

        assert r1 == "Session A"
        assert r2 == "Session B"


class TestSessionStoreIntegration:
    """Verify Router persists history when a SessionStore is injected."""

    @pytest.fixture
    def store(self, tmp_path):
        from soul.memory import SessionStore
        return SessionStore(session_dir=tmp_path, max_messages=10)

    @pytest.mark.asyncio
    async def test_persists_history_after_process(self, registry, store):
        """After process(), history should be saved to disk."""
        from core.router import Router

        provider = MockProvider(responses=[
            ProviderResponse(content="Hello persisted!", tool_calls=None),
        ])
        router = Router(registry, providers=[(provider, None)], session_store=store)

        await router.process("Test", session_id="persist_test")

        loaded = store.load("persist_test")
        assert len(loaded) > 1  # system + user + assistant
        assert loaded[-1]["role"] == "assistant"
        assert loaded[-1]["content"] == "Hello persisted!"

    @pytest.mark.asyncio
    async def test_loads_history_on_new_router(self, registry, store):
        """A new Router with the same store should restore history."""
        from core.router import Router

        provider_a = MockProvider(responses=[
            ProviderResponse(content="Turn 1", tool_calls=None),
        ])
        router_a = Router(registry, providers=[(provider_a, None)], session_store=store)
        await router_a.process("First", session_id="restore_test")

        # New router, new provider — but history restored from store
        provider_b = MockProvider(responses=[
            ProviderResponse(content="Turn 2", tool_calls=None),
        ])
        router_b = Router(registry, providers=[(provider_b, None)], session_store=store)
        result = await router_b.process("Second", session_id="restore_test")

        # The restored history means the provider sees 4 messages
        # (system + user"First" + assis"Turn 1" + user"Second")
        assert result == "Turn 2"
        assert provider_b.call_count == 1

    @pytest.mark.asyncio
    async def test_clear_history_clears_store(self, registry, store):
        """clear_history() should also clear the session file."""
        from core.router import Router

        provider = MockProvider(responses=[
            ProviderResponse(content="Saved", tool_calls=None),
        ])
        router = Router(registry, providers=[(provider, None)], session_store=store)
        await router.process("Hi", session_id="clear_test")

        assert len(store.load("clear_test")) > 0

        router.clear_history("clear_test")
        assert len(store.load("clear_test")) == 0
