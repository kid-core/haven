"""
Mock-based tests for HttpProvider error handling.

Uses unittest.mock to patch httpx.AsyncClient so no real HTTP
calls are made, and no API keys need to be present in the env.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from core.exceptions import ProviderError


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    """Inject a fake API key so HttpProvider doesn't fail at init."""
    monkeypatch.setenv("TEST_API_KEY", "sk-fake-key-for-testing")


@pytest.fixture
def provider():
    """Return a fully-configured HttpProvider (uses fake API key)."""
    from core.http_provider import HttpProvider

    return HttpProvider(
        name="TestProvider",
        model="test-model",
        base_url="https://api.test.com/v1/chat/completions",
        api_key_env="TEST_API_KEY",
        timeout=5.0,
    )


class TestHttpProvider:
    """Mock-based tests covering success and all error paths."""

    # -- helpers -------------------------------------------------------

    def _fake_resp(self, status_code: int = 200, json_data: dict | None = None):
        """Build a mock httpx.Response (sync .json(), sync .raise_for_status())."""
        mock = Mock(spec=httpx.Response)
        mock.status_code = status_code
        mock.text = json.dumps(json_data) if json_data else ""

        if json_data is not None:
            mock.json.return_value = json_data
        else:
            mock.json.side_effect = json.JSONDecodeError("empty body", "", 0)

        if status_code >= 400:
            mock.raise_for_status.side_effect = httpx.HTTPStatusError(
                message="HTTP error",
                request=Mock(),
                response=mock,
            )
        else:
            mock.raise_for_status.return_value = None

        return mock

    # -- success -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_chat_completion_success(self, provider):
        """Happy path: provider returns a valid choice message."""
        mock_data = {
            "choices": [
                {
                    "message": {
                        "content": "Hello from mock!",
                        "tool_calls": None,
                    }
                }
            ]
        }
        mock_resp = self._fake_resp(200, mock_data)

        with patch.object(provider._client, "post", new=AsyncMock(return_value=mock_resp)):
            response = await provider.chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
            )
        assert response.content == "Hello from mock!"
        assert response.tool_calls is None

    # -- HTTP errors ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_http_401_error(self, provider):
        """HTTP 401 (unauthorized) → ProviderError."""
        mock_resp = self._fake_resp(401, {"error": "unauthorized"})

        with patch.object(provider._client, "post", new=AsyncMock(return_value=mock_resp)):
            with pytest.raises(ProviderError) as exc:
                await provider.chat_completion(
                    messages=[{"role": "user", "content": "Hi"}],
                )
        assert "401" in str(exc.value)
        assert "unauthorized" in str(exc.value)

    @pytest.mark.asyncio
    async def test_http_429_rate_limit(self, provider):
        """HTTP 429 (rate-limited) → ProviderError."""
        mock_resp = self._fake_resp(429, {"error": "rate limited"})

        with patch.object(provider._client, "post", new=AsyncMock(return_value=mock_resp)):
            with pytest.raises(ProviderError) as exc:
                await provider.chat_completion(
                    messages=[{"role": "user", "content": "Hi"}],
                )
        assert "429" in str(exc.value)

    # -- network errors ------------------------------------------------

    @pytest.mark.asyncio
    async def test_timeout_error(self, provider):
        """httpx.TimeoutException → ProviderError."""
        with patch.object(
            provider._client,
            "post",
            new=AsyncMock(side_effect=httpx.TimeoutException("Connection timed out")),
        ), pytest.raises(ProviderError) as exc:
            await provider.chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
            )
        assert "timed out" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_request_error(self, provider):
        """Generic httpx.RequestError → ProviderError."""
        with patch.object(
            provider._client,
            "post",
            new=AsyncMock(side_effect=httpx.RequestError("Connection refused")),
        ), pytest.raises(ProviderError) as exc:
            await provider.chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
            )
        assert "Connection refused" in str(exc.value)

    # -- malformed response -------------------------------------------

    @pytest.mark.asyncio
    async def test_malformed_json_response(self, provider):
        """Non-JSON response body → ProviderError."""
        mock_resp = self._fake_resp(200, None)  # triggers JSONDecodeError

        with patch.object(provider._client, "post", new=AsyncMock(return_value=mock_resp)):
            with pytest.raises(ProviderError) as exc:
                await provider.chat_completion(
                    messages=[{"role": "user", "content": "Hi"}],
                )
        assert "invalid json" in str(exc.value).lower()

    # -- unexpected structure -----------------------------------------

    @pytest.mark.asyncio
    async def test_unexpected_response_structure(self, provider):
        """Valid JSON but missing 'choices' key → ProviderError."""
        mock_data = {"id": "123", "object": "chat.completion"}
        mock_resp = self._fake_resp(200, mock_data)

        with patch.object(provider._client, "post", new=AsyncMock(return_value=mock_resp)):
            with pytest.raises(ProviderError) as exc:
                await provider.chat_completion(
                    messages=[{"role": "user", "content": "Hi"}],
                )
        assert "no choices" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_empty_choices_list(self, provider):
        """Valid JSON but empty choices list → ProviderError."""
        mock_data = {"choices": []}
        mock_resp = self._fake_resp(200, mock_data)

        with patch.object(provider._client, "post", new=AsyncMock(return_value=mock_resp)):
            with pytest.raises(ProviderError) as exc:
                await provider.chat_completion(
                    messages=[{"role": "user", "content": "Hi"}],
                )
        assert "no choices" in str(exc.value).lower()

    # -- missing API key ----------------------------------------------

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_provider_error(self, monkeypatch):
        """Clearing the API key at instantiation time should raise ProviderError."""
        monkeypatch.delenv("TEST_API_KEY", raising=False)
        from core.http_provider import HttpProvider

        with pytest.raises(ProviderError) as exc:
            HttpProvider(
                name="NoKeyProvider",
                model="test-model",
                base_url="https://api.test.com/v1",
                api_key_env="TEST_API_KEY",
            )
        assert "not found" in str(exc.value).lower()

    # -- reasoning content ---------------------------------------------

    @pytest.mark.asyncio
    async def test_reasoning_content_preserved(self, provider):
        """When the response includes reasoning_content, it should be carried through."""
        mock_data = {
            "choices": [
                {
                    "message": {
                        "content": "Final answer",
                        "tool_calls": None,
                        "reasoning_content": "Step-by-step reasoning",
                    }
                }
            ]
        }
        mock_resp = self._fake_resp(200, mock_data)

        with patch.object(provider._client, "post", new=AsyncMock(return_value=mock_resp)):
            response = await provider.chat_completion(
                messages=[{"role": "user", "content": "Think step by step"}],
            )
        assert response.content == "Final answer"
        assert response.reasoning_content == "Step-by-step reasoning"

    # -- tool calls ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_tool_calls_in_response(self, provider):
        """When the response includes tool_calls, they should be carried through."""
        tool_calls_data = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "execute_command", "arguments": '{"cmd": "ls"}'},
            }
        ]
        mock_data = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": tool_calls_data,
                    }
                }
            ]
        }
        mock_resp = self._fake_resp(200, mock_data)

        with patch.object(provider._client, "post", new=AsyncMock(return_value=mock_resp)):
            response = await provider.chat_completion(
                messages=[{"role": "user", "content": "Run ls"}],
                tools=[{"type": "function", "function": {"name": "execute_command"}}],
            )
        assert response.content is None
        assert response.tool_calls == tool_calls_data

    # -- cleanup -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_close_aclient(self, provider):
        """Closing the provider should close the underlying httpx client."""
        with patch.object(provider._client, "aclose", new=AsyncMock()) as mock_close:
            await provider.close()
        mock_close.assert_awaited_once()
