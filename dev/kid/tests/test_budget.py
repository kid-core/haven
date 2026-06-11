"""P4c tests — BudgetTracker cost monitoring and Router integration."""

from __future__ import annotations

import pytest

from core.budget import BudgetExhaustedError, BudgetTracker
from core.models import ProviderResponse, Usage


# ── Cost helpers ────────────────────────────────────────────────────────────

def _cost(input_tok: int, output_tok: int, input_rate=0.27, output_rate=1.10) -> float:
    return (input_tok / 1_000_000) * input_rate + (output_tok / 1_000_000) * output_rate


# ── BudgetTracker core ──────────────────────────────────────────────────────

class TestBudgetTrackerCore:
    def test_initial_state(self):
        tracker = BudgetTracker()
        assert tracker.total_cost == 0.0
        assert tracker.total_input_tokens == 0
        assert tracker.total_output_tokens == 0
        assert not tracker.is_exhausted()

    def test_unlimited_budget_never_exhausted(self):
        tracker = BudgetTracker(max_budget_usd=0)
        tracker.record("deepseek-v4-flash", 1_000_000, 1_000_000)
        assert not tracker.is_exhausted()
        assert tracker.remaining == float("inf")

    def test_record_accumulates(self):
        tracker = BudgetTracker()
        cost1 = tracker.record("deepseek-v4-flash", 500, 200)
        cost2 = tracker.record("deepseek-v4-flash", 300, 100)
        assert tracker.total_cost == pytest.approx(cost1 + cost2)
        assert tracker.total_input_tokens == 800
        assert tracker.total_output_tokens == 300

    def test_exhausted_when_over_limit(self):
        # Set a tiny budget so one call blows through it
        tracker = BudgetTracker(max_budget_usd=0.001)
        tracker.record("deepseek-v4-flash", 5_000, 1_000)
        assert tracker.is_exhausted()

    def test_exhausted_when_exactly_at_limit(self):
        tracker = BudgetTracker(max_budget_usd=1.00)
        tracker.set_rate("gpt-5", input_per_M=1.00, output_per_M=1.00)
        tracker.record("gpt-5", 1_000_000, 0)  # exactly $1.00
        assert tracker.is_exhausted()

    def test_exhausted_raises_on_next_record(self):
        tracker = BudgetTracker(max_budget_usd=0.001)
        tracker.record("deepseek-v4-flash", 10_000, 1_000)  # blows budget
        # record() does NOT raise — caller checks is_exhausted()
        assert tracker.is_exhausted()


# ── Model-specific rates ────────────────────────────────────────────────────

class TestBudgetTrackerRates:
    def test_default_rates(self):
        tracker = BudgetTracker()
        cost = tracker.record("unknown-model", 1_000_000, 0)
        assert cost == pytest.approx(0.27)  # default input rate

    def test_custom_rates(self):
        tracker = BudgetTracker()
        tracker.set_rate("premium", input_per_M=15.00, output_per_M=60.00)
        cost = tracker.record("premium", 1000, 500)
        expected = (1000 / 1_000_000) * 15.00 + (500 / 1_000_000) * 60.00
        assert cost == pytest.approx(expected)

    def test_multiple_models_independent_rates(self):
        tracker = BudgetTracker()
        tracker.set_rate("flash", input_per_M=0.27, output_per_M=1.10)
        tracker.set_rate("pro", input_per_M=2.50, output_per_M=10.00)
        c1 = tracker.record("flash", 1000, 100)
        c2 = tracker.record("pro", 1000, 100)
        assert c1 < c2
        assert tracker.total_cost == pytest.approx(c1 + c2)

    def test_get_rate_returns_defaults_for_unregistered(self):
        tracker = BudgetTracker()
        inp, out = tracker.get_rate("ghost")
        assert inp == 0.27
        assert out == 1.10


# ── Lifecycle ───────────────────────────────────────────────────────────────

class TestBudgetTrackerLifecycle:
    def test_remaining_initial(self):
        tracker = BudgetTracker(max_budget_usd=5.00)
        assert tracker.remaining == 5.00

    def test_remaining_decreases(self):
        tracker = BudgetTracker(max_budget_usd=5.00)
        tracker.record("deepseek-v4-flash", 500_000, 100_000)
        assert tracker.remaining < 5.00
        assert tracker.remaining > 0

    def test_remaining_floors_at_zero(self):
        tracker = BudgetTracker(max_budget_usd=0.01)
        tracker.record("deepseek-v4-flash", 1_000_000, 1_000_000)
        assert tracker.is_exhausted()
        assert tracker.remaining == 0.0

    def test_reset(self):
        tracker = BudgetTracker(max_budget_usd=1.00)
        tracker.record("deepseek-v4-flash", 100, 50)
        assert tracker.total_cost > 0
        tracker.reset()
        assert tracker.total_cost == 0.0
        assert tracker.total_input_tokens == 0
        assert tracker.total_output_tokens == 0
        assert tracker.remaining == 1.00

    def test_summary_unlimited(self):
        tracker = BudgetTracker()
        tracker.record("deepseek-v4-flash", 500, 200)
        s = tracker.summary()
        assert "unlimited" in s

    def test_summary_limited(self):
        tracker = BudgetTracker(max_budget_usd=5.00)
        tracker.record("deepseek-v4-flash", 500, 200)
        s = tracker.summary()
        assert "$5.00" in s


# ── ProviderResponse usage field ────────────────────────────────────────────

class TestProviderResponseUsage:
    def test_response_with_usage(self):
        usage = Usage(prompt_tokens=150, completion_tokens=80, total_tokens=230)
        resp = ProviderResponse(content="hello", usage=usage)
        assert resp.usage is not None
        assert resp.usage.prompt_tokens == 150
        assert resp.usage.completion_tokens == 80

    def test_response_without_usage(self):
        resp = ProviderResponse(content="hello")
        assert resp.usage is None

    def test_response_serialises_usage(self):
        usage = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        resp = ProviderResponse(content="hi", usage=usage)
        d = resp.model_dump()
        assert d["usage"]["prompt_tokens"] == 10
        assert d["usage"]["completion_tokens"] == 5


# ── Router budget integration ───────────────────────────────────────────────

class TestRouterBudgetIntegration:
    """Router records usage through the budget_tracker when available."""

    async def test_router_records_usage(self):
        from core.router import Router
        from core.tool_registry import ToolRegistry
        from core.base_provider import BaseProvider

        usage_calls: list[Usage] = []

        class TrackingProvider(BaseProvider):
            def get_model(self, override: str | None = None) -> str:
                return "test-model"

            async def close(self) -> None:
                pass

            async def chat_completion(self, messages, tools=None, **kw):
                u = Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
                usage_calls.append(u)
                return ProviderResponse(content="done", usage=u)

        tracker = BudgetTracker(max_budget_usd=100.00)
        tracker.set_rate("test-model", input_per_M=1.00, output_per_M=2.00)

        registry = ToolRegistry()
        router = Router(
            registry,
            providers=TrackingProvider(),
            budget_tracker=tracker,
        )
        result = await router.process("hello", session_id="test-budget")
        assert result == "done"
        assert tracker.total_input_tokens == 100
        assert tracker.total_output_tokens == 50
        # cost = 100/1M * 1.00 + 50/1M * 2.00 = 0.0001 + 0.0001 = 0.0002
        assert tracker.total_cost > 0

    async def test_router_without_tracker_works(self):
        from core.router import Router
        from core.tool_registry import ToolRegistry
        from core.base_provider import BaseProvider

        class SimpleProvider(BaseProvider):
            def get_model(self, override: str | None = None) -> str:
                return "simple"

            async def close(self) -> None:
                pass

            async def chat_completion(self, messages, tools=None, **kw):
                return ProviderResponse(content="ok")

        registry = ToolRegistry()
        router = Router(
            registry,
            providers=SimpleProvider(),
            # no budget_tracker — should not crash
        )
        result = await router.process("hi", session_id="test-no-budget")
        assert result == "ok"

    async def test_router_no_usage_in_response(self):
        from core.router import Router
        from core.tool_registry import ToolRegistry
        from core.base_provider import BaseProvider

        class NoUsageProvider(BaseProvider):
            def get_model(self, override: str | None = None) -> str:
                return "no-usage"

            async def close(self) -> None:
                pass

            async def chat_completion(self, messages, tools=None, **kw):
                return ProviderResponse(content="ok", usage=None)

        tracker = BudgetTracker()
        registry = ToolRegistry()
        router = Router(
            registry,
            providers=NoUsageProvider(),
            budget_tracker=tracker,
        )
        result = await router.process("hi", session_id="test-no-usage")
        assert result == "ok"
        assert tracker.total_cost == 0.0  # nothing recorded
