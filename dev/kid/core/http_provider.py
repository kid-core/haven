"""
Single config-driven HTTP(S) provider for any OpenAI-compatible LLM API.

Replaces the duplicated DeepSeekProvider and OpenRouterProvider with one
class that accepts endpoint, model, API key, extra headers, and temperature
as constructor configuration.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv

from .base_provider import BaseProvider
from .exceptions import ProviderError
from .models import ProviderResponse

load_dotenv("/root/.openclaw/env")
load_dotenv("/mnt/z/Core/.env")


class HttpProvider(BaseProvider):
    """Single httpx-based provider for any OpenAI-compatible LLM API."""

    def __init__(
        self,
        *,
        name: str,
        model: str,
        base_url: str,
        api_key_env: str,
        timeout: float = 120.0,
        default_temperature: float = 0.3,
        headers_extra: dict[str, str] | None = None,
    ) -> None:
        self._name = name
        self._model = model
        self._default_temperature = default_temperature
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise ProviderError(
                f"{api_key_env} not found in environment. "
                "Set it in .env or export it directly."
            )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if headers_extra:
            headers.update(headers_extra)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout),
            headers=headers,
        )

    def get_model(self, override: str | None = None) -> str:
        return override or self._model

    # ------------------------------------------------------------------
    # Guard clause pattern: each step raises on failure
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        payload = self._build_payload(messages, tools, temperature, max_tokens)
        data = await self._do_request(payload)
        choice = self._parse_choice(data)
        return ProviderResponse(
            content=choice.get("content"),
            tool_calls=choice.get("tool_calls"),
            reasoning_content=choice.get("reasoning_content"),
        )

    def _build_payload(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """Assemble the request body — no side effects."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._default_temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        return payload

    async def _do_request(self, payload: dict) -> dict:
        """POST the payload and parse JSON.  Guard clause: raises on any failure."""
        try:
            response = await self._client.post("", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"{self._name} HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(f"{self._name} request timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderError(f"{self._name} request failed: {exc}") from exc

        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(
                f"{self._name} returned invalid JSON: {exc}"
            ) from exc

    def _parse_choice(self, data: dict) -> dict:
        """Extract the first-choice message.  Guard clause: raises on unexpected shape."""
        if "choices" not in data or not data["choices"]:
            raise ProviderError(
                f"Unexpected {self._name} response structure: no choices"
            )
        try:
            choice = data["choices"][0]
            return choice.get("message", {})
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"Unexpected {self._name} response structure: {data}"
            ) from exc

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HttpProvider:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
