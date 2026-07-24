"""Tests for the web search tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class MockTavilyResponse:
    """Simulates httpx.Response with synchronous .json() and .raise_for_status()."""

    def __init__(self, status_code: int, json_data: dict, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self) -> dict:
        return self._json_data

    def raise_for_status(self) -> None:
        import httpx

        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code} error",
                request=MagicMock(),
                response=self,
            )


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")


class TestSearchRegistered:
    """Import and registration."""

    def test_search_tool_is_registered(self):
        """The @tool decorator registers web_search in the default registry."""
        import tools  # noqa: F401
        from core.tool_decorator import get_default_registry

        registry = get_default_registry()
        assert "web_search" in registry


class TestSearchErrors:
    """Error paths."""

    def test_missing_api_key_returns_error(self, monkeypatch):
        """When TAVILY_API_KEY is unset, return an error message."""
        import tools  # noqa: F401
        from core.tool_decorator import get_default_registry

        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        spec = get_default_registry().get("web_search")
        assert spec is not None

        import asyncio
        from inspect import iscoroutinefunction

        handler = spec.handler
        if iscoroutinefunction(handler):
            result = asyncio.run(handler(query="test"))
        else:
            result = handler(query="test")

        assert isinstance(result, str)
        assert "not configured" in result.lower()


class TestSearchWithMock:
    """Behaviour with a mocked Tavily API."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_key):
        import tools  # noqa: F401
        from core.tool_decorator import get_default_registry

        spec = get_default_registry().get("web_search")
        assert spec is not None
        self.handler = spec.handler

    @pytest.mark.asyncio
    async def test_formats_results(self):
        """Successful search produces readable formatted output."""
        mock_response = MockTavilyResponse(
            status_code=200,
            json_data={
                "results": [
                    {
                        "title": "Python Programming",
                        "url": "https://python.org",
                        "content": "Python is a programming language.",
                    },
                    {
                        "title": "OpenAI API",
                        "url": "https://openai.com",
                        "content": "OpenAI provides AI models.",
                    },
                ]
            },
        )

        with patch("tools.search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)
            MockClient.return_value = mock_client

            result = await self.handler(query="test", max_results=2)

        assert isinstance(result, str)
        assert "Python Programming" in result
        assert "OpenAI API" in result
        assert "python.org" in result

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """No results should return a clear message."""
        mock_response = MockTavilyResponse(
            status_code=200, json_data={"results": []}
        )

        with patch("tools.search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_response)
            MockClient.return_value = mock_client

            result = await self.handler(query="nonexistent")

        assert "No results" in result

    @pytest.mark.asyncio
    async def test_timeout_returns_graceful_error(self):
        """HTTP timeout returns a graceful error message."""
        import httpx

        with patch("tools.search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(
                side_effect=httpx.TimeoutException("timed out")
            )
            MockClient.return_value = mock_client

            result = await self.handler(query="test")

        assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_http_429_returns_error(self):
        """Rate-limit (429) should return an error message, not crash."""
        bad_response = MockTavilyResponse(
            status_code=429, json_data={}, text="Rate limit exceeded"
        )

        with patch("tools.search.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=bad_response)
            MockClient.return_value = mock_client

            result = await self.handler(query="test")

        assert isinstance(result, str)
        assert "error" in result.lower() or "429" in result
