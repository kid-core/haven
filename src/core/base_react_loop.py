"""Shared ReAct loop foundation — extracted from Router and BackgroundAgent.

Provides the common provider-fallback iteration, tool execution skeleton,
message helpers, and the ``_clean()`` surrogate-stripping utility.

Router and BackgroundAgent both inherit from BaseReActLoop to eliminate
~70% duplication between their ReAct loops.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from .base_provider import BaseProvider
from .tool_registry import PolicyBlockedError, ToolRegistry

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Regex to strip lone surrogate characters (U+D800–U+DFFF)
_SURROGATE_RE = re.compile(
    "[" + "".join(chr(c) for c in range(0xD800, 0xE000)) + "]"
)

DEFAULT_MAX_TURNS = 60
TURN_LIMIT_MESSAGE = (
    "I've reached the maximum number of turns and wasn't able to "
    "complete the request. You can resume by spawning a new agent."
)


def _clean(text: str | None) -> str:
    """Strip lone surrogates so json.dumps won't choke."""
    if not text:
        return ""
    return _SURROGATE_RE.sub("", text)


class BaseReActLoop:
    """Shared foundation for ReAct-loop agents.

    Subclasses: Router (interactive), BackgroundAgent (autonomous).

    Provides:
    - ``_call_providers()`` — provider fallback with subclass hooks
      (circuit breaker, tracing)
    - ``_execute_tool()`` — time-boxed tool execution with
      TimeoutError / PolicyBlockedError handling and subclass hooks
      (allowlist, confirmation gate, retry, category routing)
    - ``build_assistant_msg()`` / ``build_tool_result_msg()`` —
      message construction helpers

    Subclasses override the ``_xxx_provider`` and ``_pre/_post_tool`` hooks
    to add their own behaviour without duplicating the core loop structure.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        providers: list[tuple[BaseProvider, str | None]],
    ) -> None:
        self._registry = tool_registry
        self._providers = providers

    # ==================================================================
    # Provider fallback
    # ==================================================================

    async def _call_providers(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None,
    ) -> tuple[Any | None, str | None]:
        """Iterate providers in order; return (response, error_message).

        Subclass hooks (all optional):
        - ``_should_skip_provider(provider) → bool``
        - ``_on_provider_start(provider)``
        - ``_on_provider_success(provider)``
        - ``_on_provider_error(provider, exc)``
        """
        last_error: Exception | None = None
        for provider, _ in self._providers:
            if self._should_skip_provider(provider):
                continue

            self._on_provider_start(provider)
            try:
                response = await provider.chat_completion(
                    messages=messages, tools=tools,
                )
                self._on_provider_success(provider)
                return response, None
            except Exception as exc:
                self._on_provider_error(provider, exc)
                last_error = exc
                logger.warning(
                    "Provider %s failed: %s",
                    type(provider).__name__, exc,
                )

        err = str(last_error) if last_error else "All providers failed."
        return None, err

    def _should_skip_provider(self, provider: BaseProvider) -> bool:
        """Hook: return True to skip a provider (e.g. open circuit breaker)."""
        return False

    def _on_provider_start(self, provider: BaseProvider) -> None:
        """Hook: before a provider call (e.g. open a tracer span)."""

    def _on_provider_success(self, provider: BaseProvider) -> None:
        """Hook: after a successful provider call (e.g. record circuit-breaker success)."""

    def _on_provider_error(self, provider: BaseProvider, exc: Exception) -> None:
        """Hook: on provider failure (e.g. record circuit-breaker failure)."""

    # ==================================================================
    # Tool execution skeleton
    # ==================================================================

    async def _execute_tool(
        self,
        tool_call_id: str,
        name: str,
        arguments: dict,
    ) -> dict:
        """Execute a tool with timeout, error handling, and subclass hooks.

        Hook: ``_pre_tool_check(name, args) → dict | None``
            Return a dict to short-circuit execution (e.g. blocked by policy).
            Return ``None`` to proceed normally.

        Hook: ``_post_tool_result(name, args, result_msg) → dict | None``
            Transform/enrich the result after execution.
            Return the (possibly modified) dict, or ``None`` for no-op.
        """
        # Pre-check hook
        pre = self._pre_tool_check(name, arguments)
        if pre is not None:
            return pre

        spec = self._registry.get(name)
        timeout = (
            spec.policy.timeout
            if spec and spec.policy.timeout is not None
            else 30.0
        )

        try:
            result_msg = await asyncio.wait_for(
                self._registry.execute(
                    tool_call_id=tool_call_id,
                    name=name,
                    arguments=arguments,
                ),
                timeout=timeout,
            )
        except TimeoutError:
            result_msg = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({
                    "error": f"Tool {name!r} timed out after {timeout}s.",
                }),
            }
        except PolicyBlockedError as exc:
            result_msg = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({
                    "error": f"Policy blocked: {exc.reason}",
                }),
            }
        except Exception as exc:
            logger.exception("Tool error: %s", name)
            result_msg = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({"error": str(exc)}),
            }

        # Post-execution hook
        post = self._post_tool_result(name, arguments, result_msg)
        return post if post is not None else result_msg

    def _pre_tool_check(
        self, name: str, arguments: dict,
    ) -> dict | None:
        """Hook: short-circuit tool execution. Return a dict or None."""
        return None

    def _post_tool_result(
        self, name: str, arguments: dict, result_msg: dict,
    ) -> dict | None:
        """Hook: transform tool result after execution. Return dict or None."""
        return None

    # ==================================================================
    # Message helpers
    # ==================================================================

    @staticmethod
    def build_assistant_msg(
        content: str | None,
        tool_calls: list[dict] | None = None,
        reasoning_content: str | None = None,
    ) -> dict[str, Any]:
        """Build a standard assistant message dict."""
        msg: dict[str, Any] = {
            "role": "assistant",
            "content": _clean(content or ""),
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content:
            msg["reasoning_content"] = _clean(reasoning_content)
        return msg

    @staticmethod
    def build_tool_result_msg(
        tool_call_id: str,
        content: str,
    ) -> dict[str, Any]:
        """Build a standard tool-result message dict."""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        }
