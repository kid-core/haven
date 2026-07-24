"""P4d-B — Advisor abstraction for multi-tier decision-making.

The Advisor is a higher-cost / higher-capability LLM that the Router
can consult when the primary Executor is uncertain about a tool result
or needs help decomposing a complex request.

Architecture::

    Executor (primary provider, cheap)
        │
        ├── processes user message
        ├── calls tool
        └── if uncertain ──→ Advisor (expensive provider)
                                │
                                ├── analyses tool result
                                ├── provides recommendation
                                └── cost tracked via P4c BudgetTracker

Usage::

    advisor = Advisor(
        provider=expensive_provider,
        budget_tracker=budget,
        max_tokens=500,
    )
    suggestion = await advisor.consult(executor_context)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.budget import BudgetExhaustedError
from core.models import ProviderResponse, Usage

if TYPE_CHECKING:
    from core.base_provider import BaseProvider
    from core.budget import BudgetTracker

logger = logging.getLogger(__name__)

# Default max tokens for advisor calls — keeps cost ~$0.02 per consult
DEFAULT_ADVISOR_MAX_TOKENS = 500

ADVISOR_SYSTEM_PROMPT = (
    "You are a strategic advisor reviewing an AI assistant's execution. "
    "Given the conversation context and tool result below, provide a "
    "concise recommendation for the next action. Keep your response "
    "under 200 characters."
)


class Advisor:
    """High-capability decision-support provider.

    Wraps an expensive LLM provider with budget tracking and a
    specialised system prompt.  Each ``consult()`` call is a single
    chat-completion request that costs ~$0.02 at typical rates.
    """

    def __init__(
        self,
        provider: BaseProvider,
        budget_tracker: BudgetTracker | None = None,
        max_tokens: int = DEFAULT_ADVISOR_MAX_TOKENS,
        system_prompt: str = ADVISOR_SYSTEM_PROMPT,
    ) -> None:
        self._provider = provider
        self._budget_tracker = budget_tracker
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
        self._total_consults = 0

    @property
    def total_consults(self) -> int:
        """Number of consult calls made so far."""
        return self._total_consults

    async def consult(
        self,
        context: str,
        model_override: str | None = None,
    ) -> str | None:
        """Ask the Advisor for a recommendation.

        Returns the advisor's text response, or ``None`` if the budget
        is exhausted or the call fails.

        The *context* should include the recent conversation and the
        tool result that triggered uncertainty.
        """
        if self._budget_tracker is not None and self._budget_tracker.is_exhausted():
            logger.warning("Advisor skipped — budget exhausted")
            return None

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": context},
        ]

        try:
            response = await self._provider.chat_completion(
                messages=messages,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            logger.warning("Advisor consult failed: %s", exc)
            return None

        self._total_consults += 1

        # Track cost via P4c budget
        if self._budget_tracker is not None and response.usage is not None:
            self._budget_tracker.record(
                self._provider.get_model(model_override or ""),
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )

        return response.content
