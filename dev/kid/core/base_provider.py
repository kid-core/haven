"""Abstract LLM provider interface.

All concrete providers inherit from ``BaseProvider`` and must implement
``chat_completion()`` and ``get_model()``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import ProviderResponse


class BaseProvider(ABC):
    """Abstract async LLM provider."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Send a chat-completion request and return a normalised dict.

        Returns
        -------
        dict with keys:
            content    : str | None   — text response (None when tool_calls present)
            tool_calls : list | None  — tool-call dicts (None when text present)
        """

    @abstractmethod
    def get_model(self, override: str | None = None) -> str:
        """Return the model name in use (optionally overridden)."""

    @abstractmethod
    async def close(self) -> None:
        """Release any resources held by the provider."""
