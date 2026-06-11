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
        """Send a chat-completion request and return a normalised dict.  # noqa: DAR101, DAR201
        """

    @abstractmethod
    def get_model(self, override: str | None = None) -> str:
        """Return the model name in use (optionally overridden)."""

    @abstractmethod
    async def close(self) -> None:
        """Release any resources held by the provider."""

    async def ping(self) -> bool:
        """Lightweight health-check placeholder.

        Override in concrete providers to verify API connectivity
        without consuming a chat slot (e.g. call a lightweight
        endpoint).  Default returns True.
        """
        return True
