"""State-machine ReAct loop: wires ToolRegistry + BaseProvider together."""

from __future__ import annotations

import logging
import re
from typing import Any, TYPE_CHECKING

from .base_provider import BaseProvider
from .exceptions import RouterError
from .models import ProviderResponse
from .tool_registry import ToolRegistry

if TYPE_CHECKING:
    from soul.memory import SessionStore

# Regex that matches any lone surrogate character (U+D800–U+DFFF)
_SURROGATE_RE = re.compile(r"[" + "".join(chr(c) for c in range(0xD800, 0xE000)) + "]")

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. "
    "Use them when needed."
)

TURN_LIMIT_MESSAGE = (
    "I've reached the maximum number of turns and wasn't able to "
    "complete the request. Please try a more specific question."
)


def _clean(text: str | None) -> str:
    """Strip lone surrogates so json.dumps won't choke."""
    if not text:
        return ""
    return _SURROGATE_RE.sub("", text)


class Router:
    """ReAct loop that pairs providers with a tool registry.

    Parameters
    ----------
    tool_registry:
        Holds registered tools and dispatches execution.
    providers:
        One or more ``(provider, [model_override])`` tuples. The router
        tries them in order; if one fails it falls through to the next.
        At least one provider is required.
    system_prompt:
        System-level instruction prepended at the start of every
        session. Defaults to a short ReAct-flavoured prompt.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        providers: list[tuple[BaseProvider, str | None]] | BaseProvider,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        session_store: SessionStore | None = None,
    ) -> None:
        self._registry = tool_registry
        self._system_prompt = system_prompt
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._session_store = session_store

        # Normalise: single provider -> list of one
        if isinstance(providers, BaseProvider):
            self._providers: list[tuple[BaseProvider, str | None]] = [
                (providers, None)
            ]
        else:
            self._providers = providers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process(
        self,
        user_message: str,
        session_id: str = "default",
        max_turns: int = 10,
    ) -> str:
        """Run the ReAct loop for a single user message.

        Parameters
        ----------
        user_message:
            The natural-language request.
        session_id:
            Scope key for conversation history.
        max_turns:
            Max LLM round-trips before returning a turn-limit message.
        """
        messages = self._get_or_init_history(session_id)
        messages.append({"role": "user", "content": _clean(user_message)})
        tools = self._registry.get_openai_tools() or None

        for _turn in range(max_turns):
            # ------ call the model (with fallback) --------------------------
            response = None
            last_error = None
            for provider, _ in self._providers:
                try:
                    response = await provider.chat_completion(
                        messages=messages, tools=tools,
                    )
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Provider %s failed, trying next: %s",
                        type(provider).__name__, exc,
                    )
            if last_error is not None:
                return f"All providers failed. Last error: {last_error}"

            content: str | None = response.content
            tool_calls: list[dict[str, Any]] | None = response.tool_calls
            reasoning_content: str | None = response.reasoning_content

            # ------ text response -> done -----------------------------------
            if not tool_calls:
                text = _clean(content or "")
                assistant_msg: dict[str, Any] = {"role": "assistant", "content": text}
                if reasoning_content:
                    assistant_msg["reasoning_content"] = _clean(reasoning_content)
                messages.append(assistant_msg)
                self._save_history(session_id, messages)
                return text

            # ------ tool-call turn ------------------------------------------
            assistant_msg = {"role": "assistant", "content": _clean(content)}
            assistant_msg["tool_calls"] = tool_calls
            if reasoning_content:
                assistant_msg["reasoning_content"] = _clean(reasoning_content)
            messages.append(assistant_msg)

            for tc in tool_calls:
                tc_id: str = tc.get("id", "")
                fn: dict[str, Any] = tc.get("function", {})
                name: str = fn.get("name", "")
                arguments: dict[str, Any] = fn.get("arguments", {})

                if isinstance(arguments, str):
                    import json
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                try:
                    result_msg = await self._registry.execute(
                        tool_call_id=tc_id, name=name, arguments=arguments,
                    )
                except Exception as exc:
                    logger.exception("Tool execution error: %s", name)
                    import json
                    result_msg = {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps({"error": str(exc)}),
                    }

                messages.append(result_msg)

        self._save_history(session_id, messages)
        return TURN_LIMIT_MESSAGE

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------
    def _get_or_init_history(self, session_id: str) -> list[dict[str, Any]]:
        """Return (and lazily create) the message list for *session_id*."""
        if session_id not in self._history:
            # Try to restore from persistent store first
            if self._session_store is not None:
                stored = self._session_store.load(session_id)
                if stored:
                    self._history[session_id] = stored
                    return self._history[session_id]
            # Nothing stored — start fresh with system prompt
            self._history[session_id] = [
                {"role": "system", "content": self._system_prompt}
            ]
        return self._history[session_id]

    def _save_history(self, session_id: str, messages: list[dict]) -> None:
        """Persist messages if a SessionStore is configured."""
        if self._session_store is not None:
            self._session_store.save(session_id, messages)

    def clear_history(self, session_id: str) -> None:
        """Discard conversation history for *session_id*."""
        self._history.pop(session_id, None)
        if self._session_store is not None:
            self._session_store.save(session_id, [])
