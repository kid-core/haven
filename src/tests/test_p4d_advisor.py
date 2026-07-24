"""P4d-B tests — Advisor Pattern and Router integration."""

from __future__ import annotations

import pytest

from core.advisor import Advisor, ADVISOR_SYSTEM_PROMPT
from core.models import ProviderResponse, Usage
from core.budget import BudgetTracker


# ── Fixtures ─────────────────────────────────────────────────────────────────

class SpyProvider:
    """Records calls and returns configured responses."""

    def __init__(self, model="advisor-model", response_content="do X"):
        self.model = model
        self.response_content = response_content
        self.calls: list[dict] = []
        self._usage = Usage(prompt_tokens=300, completion_tokens=200, total_tokens=500)

    def set_usage(self, u: Usage):
        self._usage = u

    def get_model(self, override: str | None = None) -> str:
        return override or self.model

    async def close(self) -> None:
        pass

    async def chat_completion(self, messages, tools=None, max_tokens=None, **kw):
        self.calls.append({
            "messages": messages,
            "max_tokens": max_tokens,
            "tools": tools,
            **kw,
        })
        return ProviderResponse(content=self.response_content, usage=self._usage)

    @property
    def call_count(self) -> int:
        return len(self.calls)


class ErrorProvider(SpyProvider):
    """Provider that always raises."""

    async def chat_completion(self, messages, tools=None, max_tokens=None, **kw):
        self.calls.append({})
        raise RuntimeError("provider down")


@pytest.fixture
def advisor_provider():
    return SpyProvider(response_content="Try using the search tool instead.")


@pytest.fixture
def tracker():
    return BudgetTracker(max_budget_usd=10.00)


# ── Advisor core ─────────────────────────────────────────────────────────────

class TestAdvisorCore:
    async def test_consult_returns_response(self, advisor_provider):
        advisor = Advisor(provider=advisor_provider)
        result = await advisor.consult("context: file not found")
        assert result == "Try using the search tool instead."
        assert advisor.total_consults == 1

    async def test_consult_passes_context(self, advisor_provider):
        advisor = Advisor(provider=advisor_provider)
        await advisor.consult("my test context")
        sent = advisor_provider.calls[0]["messages"]
        assert sent[0]["role"] == "system"
        assert sent[1]["content"] == "my test context"

    async def test_consult_uses_custom_max_tokens(self, advisor_provider):
        advisor = Advisor(provider=advisor_provider, max_tokens=200)
        await advisor.consult("x")
        assert advisor_provider.calls[0]["max_tokens"] == 200

    async def test_consult_counts_multiple_calls(self, advisor_provider):
        advisor = Advisor(provider=advisor_provider)
        await advisor.consult("a")
        await advisor.consult("b")
        assert advisor.total_consults == 2

    async def test_default_system_prompt(self, advisor_provider):
        advisor = Advisor(provider=advisor_provider)
        await advisor.consult("x")
        assert advisor_provider.calls[0]["messages"][0]["content"] == ADVISOR_SYSTEM_PROMPT

    async def test_provider_error_returns_none(self):
        advisor = Advisor(provider=ErrorProvider())
        result = await advisor.consult("context")
        assert result is None
        assert advisor.total_consults == 0  # error = no count


# ── Advisor + budget ─────────────────────────────────────────────────────────

class TestAdvisorBudget:
    async def test_budget_exhausted_returns_none(self, advisor_provider):
        tracker = BudgetTracker(max_budget_usd=0.0001)
        tracker.record("expensive", 1_000_000, 1_000_000)  # eat budget
        advisor = Advisor(provider=advisor_provider, budget_tracker=tracker)
        result = await advisor.consult("x")
        assert result is None
        assert advisor.total_consults == 0

    async def test_records_usage_after_consult(self, advisor_provider):
        tracker = BudgetTracker()
        advisor = Advisor(provider=advisor_provider, budget_tracker=tracker)
        await advisor.consult("x")
        assert tracker.total_input_tokens > 0
        assert tracker.total_output_tokens > 0

    async def test_no_budget_tracker_works(self, advisor_provider):
        advisor = Advisor(provider=advisor_provider, budget_tracker=None)
        result = await advisor.consult("x")
        assert result is not None
        assert advisor.total_consults == 1

    async def test_custom_system_prompt(self, advisor_provider):
        advisor = Advisor(provider=advisor_provider, system_prompt="Be brief.")
        await advisor.consult("x")
        assert advisor_provider.calls[0]["messages"][0]["content"] == "Be brief."


# ── Router advisor integration ───────────────────────────────────────────────

class TestRouterWithAdvisor:
    async def test_router_consults_advisor_on_error(self):
        from core.router import Router
        from core.tool_registry import ToolRegistry
        from core.base_provider import BaseProvider

        advisor_calls: list = []

        class ToolProvider(BaseProvider):
            def __init__(self):
                self._call = 0

            def get_model(self, override=None):
                return "executor"

            async def close(self):
                pass

            async def chat_completion(self, messages, tools=None, **kw):
                self._call += 1
                if self._call == 1:
                    # First call: return a tool call
                    return ProviderResponse(
                        content=None,
                        tool_calls=[{
                            "id": "tc1",
                            "type": "function",
                            "function": {
                                "name": "cmd",
                                "arguments": '{"cmd": "ls /nonexistent"}',
                            },
                        }],
                        usage=Usage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
                    )
                else:
                    # Second call: text response
                    return ProviderResponse(
                        content="I'll try a different approach.",
                        usage=Usage(prompt_tokens=30, completion_tokens=10, total_tokens=40),
                    )

        class SpyAdvisor:
            def __init__(self):
                self.consults: list[str] = []

            @property
            def total_consults(self):
                return len(self.consults)

            async def consult(self, context, model_override=None):
                self.consults.append(context)
                return "Try ls -la instead."

        advisor = SpyAdvisor()
        registry = ToolRegistry()

        # Register cmd tool that returns an error
        from core.tool_spec import ToolSpec
        async def cmd_handler(cmd: str):
            return f"error: cannot access '/nonexistent': No such file"
        registry.add(ToolSpec("cmd", "Run command", {"cmd": {"type": "string"}}, cmd_handler))

        router = Router(
            registry,
            providers=ToolProvider(),
            advisor=advisor,
        )
        result = await router.process("list files", session_id="test-adv")
        assert "different approach" in result
        assert len(advisor.consults) == 1
        assert "error" in advisor.consults[0]

    async def test_router_no_advisor_works_normally(self):
        from core.router import Router
        from core.tool_registry import ToolRegistry
        from core.base_provider import BaseProvider

        class SimpleProvider(BaseProvider):
            def get_model(self, override=None):
                return "simple"
            async def close(self):
                pass
            async def chat_completion(self, messages, tools=None, **kw):
                return ProviderResponse(content="ok")

        registry = ToolRegistry()
        router = Router(registry, providers=SimpleProvider())
        result = await router.process("hi", session_id="test-no-adv")
        assert result == "ok"

    async def test_successful_tool_no_advisor_call(self):
        from core.router import Router
        from core.tool_registry import ToolRegistry
        from core.base_provider import BaseProvider

        advisor_consults: list = []

        class SpyAdvisor:
            @property
            def total_consults(self):
                return len(advisor_consults)
            async def consult(self, context, model_override=None):
                advisor_consults.append(context)
                return "suggestion"

        class ToolProvider(BaseProvider):
            def __init__(self):
                self._call = 0
            def get_model(self, override=None):
                return "executor"
            async def close(self):
                pass
            async def chat_completion(self, messages, tools=None, **kw):
                self._call += 1
                if self._call == 1:
                    return ProviderResponse(
                        content=None,
                        tool_calls=[{
                            "id": "tc1", "type": "function",
                            "function": {"name": "cmd", "arguments": '{"cmd": "echo hello"}'},
                        }],
                        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                    )
                return ProviderResponse(content="Success!", usage=Usage())

        from core.tool_spec import ToolSpec
        async def cmd_handler_s(cmd: str):
            return "hello"

        advisor = SpyAdvisor()
        registry = ToolRegistry()
        registry.add(ToolSpec("cmd", "Run cmd", {"cmd": {"type": "string"}}, cmd_handler_s))

        router = Router(registry, providers=ToolProvider(), advisor=advisor)
        result = await router.process("say hello", session_id="test-ok")
        assert result == "Success!"
        assert len(advisor_consults) == 0  # no error → no advisor


# ── Uncertainty detection ────────────────────────────────────────────────────

class TestUncertaintyDetection:
    def test_error_detected(self):
        from core.router import _is_uncertain_tool_result
        assert _is_uncertain_tool_result("error: file not found")
        assert _is_uncertain_tool_result("command failed with exit code 1")
        assert _is_uncertain_tool_result("Permission denied")

    def test_json_success_not_detected(self):
        from core.router import _is_uncertain_tool_result
        # JSON response with error=null should not trigger
        assert not _is_uncertain_tool_result('{"status": "success", "error": null}')

    def test_success_not_detected(self):
        from core.router import _is_uncertain_tool_result
        assert not _is_uncertain_tool_result("OK: file written successfully")
        assert not _is_uncertain_tool_result("Search results: 5 items found")
        assert not _is_uncertain_tool_result("Memory search complete.")
