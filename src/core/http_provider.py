"""
Single config-driven HTTP(S) provider for any OpenAI-compatible LLM API.

Replaces the duplicated DeepSeekProvider and OpenRouterProvider with one
class that accepts endpoint, model, API key, extra headers, and temperature
as constructor configuration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx

from .base_provider import BaseProvider
from .exceptions import ProviderError
from .models import ProviderResponse

logger = logging.getLogger(__name__)

# 429 retry limits
_MAX_429_RETRIES = 3
_MAX_RETRY_AFTER_SECONDS = 30.0
_DEFAULT_429_BACKOFF = 2.0


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
        # NOTE: httpx base_url always appends trailing slash to post(""),
        # which breaks OpenRouter (returns 404). Store endpoint separately.
        self._api_url = base_url
        self._client = httpx.AsyncClient(
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
        usage = self._parse_usage(data)
        return ProviderResponse(
            content=choice.get("content"),
            tool_calls=choice.get("tool_calls"),
            reasoning_content=choice.get("reasoning_content"),
            usage=usage,
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

    async def _do_request(self, payload: dict, _retry_count: int = 0) -> dict:
        """POST the payload and parse JSON with smart retry.

        429 (rate limit): retry up to 3 times with Retry-After header.
            Does NOT count toward circuit breaker — these are transient.
        502/503 (server hiccup): one quick retry after 2s.
        5xx (other): raises ProviderError immediately — circuit breaker handles it.
        """
        try:
            response = await self._client.post(self._api_url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            text = exc.response.text

            # ── 429: rate limited — retry with backoff ──────────────
            if status == 429:
                retry_after = self._parse_retry_after(exc.response)

                if _retry_count >= _MAX_429_RETRIES:
                    raise ProviderError(
                        f"{self._name} HTTP 429 after {_retry_count} retries: {text}"
                    ) from exc

                wait = retry_after if retry_after is not None else _DEFAULT_429_BACKOFF
                if retry_after is not None and retry_after > _MAX_RETRY_AFTER_SECONDS:
                    raise ProviderError(
                        f"{self._name} HTTP 429 Retry-After {retry_after}s exceeds max {_MAX_RETRY_AFTER_SECONDS}s: {text}"
                    ) from exc

                logger.info(
                    "%s HTTP 429 — retry %d/%d in %.1fs",
                    self._name, _retry_count + 1, _MAX_429_RETRIES, wait,
                )
                await asyncio.sleep(wait)
                return await self._do_request(payload, _retry_count + 1)

            # ── 502/503: brief server hiccup, one retry ─────────────
            if status in (502, 503) and _retry_count == 0:
                logger.info(
                    "%s HTTP %d — one quick retry in 2s",
                    self._name, status,
                )
                await asyncio.sleep(2.0)
                return await self._do_request(payload, _retry_count + 1)

            # ── Other 4xx/5xx: let circuit breaker handle ───────────
            raise ProviderError(
                f"{self._name} HTTP {status}: {text}"
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

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        """Extract Retry-After from response headers.

        Supports both integer seconds and HTTP-date formats.
        Returns None if header is absent or unparseable.
        """
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            # Could be an HTTP-date (RFC 7231) — parse it
            try:
                from email.utils import parsedate_to_datetime
                retry_time = parsedate_to_datetime(raw)
                import datetime
                now = datetime.datetime.now(datetime.timezone.utc)
                diff = (retry_time - now).total_seconds()
                return max(0.0, diff)
            except Exception:
                logger.debug("Failed to parse Retry-After header: %r", raw)
                return None

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

    def _parse_usage(self, data: dict) -> Usage | None:
        """Extract token usage from the response, or None if absent."""
        from core.models import Usage  # noqa: F811
        u = data.get("usage")
        if not isinstance(u, dict):
            return None
        return Usage(
            prompt_tokens=u.get("prompt_tokens", 0),
            completion_tokens=u.get("completion_tokens", 0),
            total_tokens=u.get("total_tokens", 0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HttpProvider:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
