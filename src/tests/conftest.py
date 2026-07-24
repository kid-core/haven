"""Pytest fixtures for Haven.

Shared fixtures and fake providers for deterministic testing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from core.models import ProviderResponse

sys.path.insert(0, "kid")


# ═══════════════════════════════════════════════════════════════════
# FakeProvider — controllable LLM simulator
# ═══════════════════════════════════════════════════════════════════

class FakeProvider:
    """Returns pre-recorded responses for deterministic testing.

    Unlike a mock, this is a state machine that simulates LLM behavior
    deterministically.  Preset the response sequence, then assert on
    call_count and last_messages.

    Example
    -------
    >>> provider = FakeProvider()
    >>> provider.add_response(content="Hello!")
    >>> resp = await provider.chat_completion([{"role": "user", "content": "Hi"}])
    >>> resp.content
    'Hello!'
    >>> provider.call_count
    1
    """

    def __init__(self, responses: list[ProviderResponse] | None = None) -> None:
        self.responses = list(responses) if responses else []
        self.call_count = 0
        self.last_messages: list[dict[str, Any]] | None = None
        self._should_fail: bool = False
        self._fail_error: Exception | None = None

    def add_response(
        self,
        content: str | None = None,
        tool_calls: list[dict] | None = None,
        reasoning: str | None = None,
    ) -> None:
        """Pre-set the next response (appended to queue)."""
        self.responses.append(
            ProviderResponse(
                content=content,
                tool_calls=tool_calls,
                reasoning_content=reasoning,
            )
        )

    def set_should_fail(self, enabled: bool = True, error: str = "Simulated failure") -> None:
        """Make the next chat_completion call raise an exception."""
        self._should_fail = enabled
        self._fail_error = RuntimeError(error)

    async def chat_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        self.call_count += 1
        self.last_messages = messages

        if self._should_fail:
            self._should_fail = False
            raise self._fail_error or RuntimeError("Simulated failure")

        if self.call_count <= len(self.responses):
            return self.responses[self.call_count - 1]
        return self.responses[-1] if self.responses else ProviderResponse(content="")

    def get_model(self, override: str | None = None) -> str:
        return "fake-model"

    async def close(self) -> None:
        pass

    async def ping(self) -> bool:
        return True


class FailingProvider:
    """Always raises an exception — used for fallback tests."""

    async def chat_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        raise RuntimeError("Simulated provider failure")

    def get_model(self, override: str | None = None) -> str:
        return "failing-model"

    async def close(self) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_provider() -> FakeProvider:
    """A clean FakeProvider with no preset responses."""
    return FakeProvider()


@pytest.fixture
async def router(fake_provider: FakeProvider) -> Any:
    """Router with one FakeProvider and the default tool registry.

    Imported lazily inside the fixture so conftest.py doesn't trigger
    eager tool registration on module load.
    """
    import tools  # noqa: F401 — triggers @tool registration
    from core.router import Router
    from core.tool_decorator import get_default_registry

    registry = get_default_registry()
    return Router(registry, providers=[(fake_provider, None)])


@pytest.fixture
def tmp_skill_store(tmp_path: Path) -> Any:
    """SkillStore backed by a temp directory — auto cleaned up."""
    from learning.skill_store import SkillStore

    return SkillStore(storage_dir=tmp_path / "skills")


@pytest.fixture
def crash_journal(tmp_path: Path) -> Any:
    """CrashJournal backed by a temp file."""
    from core.crash_journal import CrashJournal

    return CrashJournal(storage_path=str(tmp_path / "crash.json"))

