"""P4c — Budget tracker for LLM API cost monitoring.

Tracks token usage across provider calls and accumulates estimated
USD cost.  When *max_budget_usd* is set (>0), ``is_exhausted()``
returns True once the budget is depleted.

Provider-level rates can be registered so that different models
(research, vision, coding) accrue cost at their real pricing tiers.

Usage::

    tracker = BudgetTracker(max_budget_usd=1.00)
    tracker.set_rate("deepseek-v4-flash", input_per_M=0.27, output_per_M=1.10)
    tracker.record("deepseek-v4-flash", 500, 200)
    if tracker.is_exhausted():
        raise BudgetExhaustedError(...)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Default rates (USD per 1M tokens) — fallback when no provider rate set ──
DEFAULT_INPUT_RATE_PER_1M = 0.27   # ~DeepSeek Flash input
DEFAULT_OUTPUT_RATE_PER_1M = 1.10  # ~DeepSeek Flash output


class BudgetExhaustedError(Exception):
    """Raised when a budget tracker reports exhaustion."""


class BudgetTracker:
    """Token-cost tracker with optional hard limit.

    Providers are registered with per-model pricing.  Calls to
    ``record()`` accumulate cost; ``is_exhausted()`` returns True
    when the cumulative total meets or exceeds *max_budget_usd*.

    Set *max_budget_usd* to 0 or leave it unset for monitoring-only
    mode (unlimited budget).
    """

    def __init__(self, max_budget_usd: float = 0.0) -> None:
        self.max_budget_usd = max_budget_usd
        self.total_cost: float = 0.0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        # model_name → (input_rate_per_1M, output_rate_per_1M)
        self._rates: dict[str, tuple[float, float]] = {}

    # ── Provider rate registry ──────────────────────────────────────

    def set_rate(
        self,
        model: str,
        input_per_M: float,
        output_per_M: float,
    ) -> None:
        """Register per-1M-token pricing for a model."""
        self._rates[model] = (input_per_M, output_per_M)

    def get_rate(self, model: str) -> tuple[float, float]:
        """Return (input, output) rates or defaults."""
        return self._rates.get(
            model,
            (DEFAULT_INPUT_RATE_PER_1M, DEFAULT_OUTPUT_RATE_PER_1M),
        )

    # ── Recording ───────────────────────────────────────────────────

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Record token usage and return the cost of this call.

        Raises :class:`BudgetExhaustedError` when the tracker has a
        hard limit and this call would exceed it (even partially).
        """
        input_rate, output_rate = self.get_rate(model)
        cost = (input_tokens / 1_000_000) * input_rate + \
               (output_tokens / 1_000_000) * output_rate

        self.total_cost += cost
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        return cost

    def is_exhausted(self) -> bool:
        """True when the hard budget is depleted."""
        return self.max_budget_usd > 0 and self.total_cost >= self.max_budget_usd

    @property
    def remaining(self) -> float:
        """USD remaining (0 when unlimited or exhausted)."""
        if self.max_budget_usd <= 0:
            return float("inf")
        return max(0.0, self.max_budget_usd - self.total_cost)

    # ── Summary ─────────────────────────────────────────────────────

    def summary(self) -> str:
        """Human-readable budget summary."""
        return (
            f"Budget: ${self.total_cost:.4f} / "
            f"${self.max_budget_usd:.2f}"
            if self.max_budget_usd > 0
            else f"Budget: ${self.total_cost:.4f} (unlimited)"
        )

    def reset(self) -> None:
        """Clear all counters (keep rates and limit)."""
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
