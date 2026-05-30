"""State-machine ReAct loop: wires ToolRegistry + BaseProvider together (Phase 2a extended)."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, TYPE_CHECKING

from .base_provider import BaseProvider
from .category_router import CategoryRouter, ExecutionMode
from .tool_registry import PolicyBlockedError, ToolRegistry

if TYPE_CHECKING:
    from soul.memory import SessionStore, LongTermMemory
    from learning.skill_factory import SkillFactory
    from learning.skill_store import SkillStore

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

    Phase 2a additions:
        long_term_memory:  injects relevant memories at session start,
                           auto-summarises at session end.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        providers: list[tuple[BaseProvider, str | None]] | BaseProvider,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        session_store: SessionStore | None = None,
        long_term_memory: LongTermMemory | None = None,
        skill_store: SkillStore | None = None,
        default_timeout: float = 30.0,
        category_router: CategoryRouter | None = None,
    ) -> None:
        self._registry = tool_registry
        self._system_prompt = system_prompt
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._session_store = session_store
        self._long_term_memory = long_term_memory  # Phase 2a
        self._skill_store = skill_store              # Phase 3
        self._skill_factory = None                   # created lazily
        if skill_store is not None:
            from learning.skill_factory import SkillFactory
            self._skill_factory = SkillFactory(skill_store)

        # Phase 4 — sub-task delegation
        self._spawn_manager = None
        from tools.spawn_child import SpawnManager
        self._spawn_manager = SpawnManager(router=self, parent_id="main")
        from tools.spawn_tool import set_spawn_manager
        set_spawn_manager(self._spawn_manager)

        self._default_timeout = default_timeout  # Phase 0

        # Normalise: single provider -> list of one
        if isinstance(providers, BaseProvider):
            self._providers: list[tuple[BaseProvider, str | None]] = [
                (providers, None)
            ]
        else:
            self._providers = providers

        # Phase 1b — category-aware routing
        self._cat_router = category_router or CategoryRouter()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process(
        self,
        user_message: str,
        session_id: str = "default",
        max_turns: int = 10,
    ) -> str:
        """Run the ReAct loop for a single user message."""
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

                result_msg = await self._execute_tool(
                    tool_call_id=tc_id, name=name, arguments=arguments,
                )
                messages.append(result_msg)

        self._save_history(session_id, messages)
        return TURN_LIMIT_MESSAGE

    # ------------------------------------------------------------------
    # Tool execution with Phase 0 + Phase 1b enforcement
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, tool_call_id: str, name: str, arguments: dict,
    ) -> dict:
        """Execute a tool with policy checks, timeout, and category routing."""
        import json

        # Check if tool requires confirmation
        if self._registry.is_confirm_required(name):
            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({
                    "requires_confirmation": True,
                    "tool": name,
                    "arguments": arguments,
                    "message": (
                        f"⚠️ Tool {name!r} requires confirmation before execution. "
                        f"Please review and approve the following call:\n"
                        f"Arguments: {json.dumps(arguments, indent=2)}"
                    ),
                }),
            }

        # Resolve tool spec and category (Phase 1b)
        spec = self._registry.get(name)
        category = spec.category if spec else None

        # Determine timeout — tool policy first, then category default, then router fallback
        timeout = self._default_timeout
        if spec is not None and spec.policy.timeout is not None:
            timeout = spec.policy.timeout

        # Category-aware routing (Phase 1b)
        if category is not None:
            rule = self._cat_router.get_rule(category)
            logger.debug(
                "Tool %r → category=%s mode=%s timeout=%.1fs",
                name, category.name, rule.mode.name, timeout,
            )

            # AI_PROXY mode — inject provider context into tool arguments
            if rule.mode == ExecutionMode.AI_PROXY:
                provider = self._cat_router.get_provider_for(category)
                if provider is not None:
                    arguments["_provider"] = provider
                    logger.debug("Tool %r → injected AI provider", name)

        try:
            result_msg = await asyncio.wait_for(
                self._registry.execute(
                    tool_call_id=tool_call_id, name=name, arguments=arguments,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Tool %r timed out after %ss", name, timeout)
            result_msg = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({
                    "error": f"Tool {name!r} timed out after {timeout}s."
                }),
            }
        except PolicyBlockedError as exc:
            logger.info("Tool %r blocked by policy: %s", name, exc.reason)
            result_msg = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({
                    "error": f"Policy blocked: {exc.reason}"
                }),
            }
        except Exception as exc:
            logger.exception("Tool execution error: %s", name)
            result_msg = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({"error": str(exc)}),
            }

        # Phase 3: observe tool call for pattern learning
        if self._skill_factory is not None and spec is not None:
            success = '"error"' not in result_msg.get("content", "")
            self._skill_factory.observe(
                tool_name=name,
                arguments=arguments,
                category=spec.category,
                success=success,
                session_id="",  # filled by caller if needed
                response_preview=result_msg.get("content", "")[:200],
            )

        return result_msg

    # ------------------------------------------------------------------
    # History management (Phase 2a: memory injection + auto-summarise)
    # ------------------------------------------------------------------

    def _get_or_init_history(self, session_id: str) -> list[dict[str, Any]]:
        """Return (and lazily create) the message list for *session_id*.

        Phase 2a: injects relevant long-term memories into the system prompt
        when starting a fresh session.
        """
        if session_id not in self._history:
            if self._session_store is not None:
                stored = self._session_store.load(session_id)
                if stored:
                    self._history[session_id] = stored
                    return self._history[session_id]

            # Build system prompt with memory + learned skills context
            prompt = self._system_prompt
            if self._long_term_memory is not None:
                important = self._long_term_memory.get_important(limit=8)
                if important:
                    lines = ["\n[Relevant Long-Term Memory]"]
                    for e in important:
                        lines.append(f"- [{e.type}] {e.content[:200]}")
                    prompt += "\n".join(lines)
            # Inject active learned skills (Phase 3)
            if self._skill_store is not None:
                from learning.skill_factory import inject_active_skills
                prompt = inject_active_skills(self._skill_store, prompt)

            self._history[session_id] = [
                {"role": "system", "content": prompt}
            ]
        return self._history[session_id]

    def _save_history(self, session_id: str, messages: list[dict]) -> None:
        """Persist messages + auto-summarise to long-term memory (Phase 2a)."""
        if self._session_store is not None:
            self._session_store.save(session_id, messages)

        # Auto-summarise to long-term memory
        if self._long_term_memory is not None and len(messages) > 5:
            try:
                from soul.memory.summarizer import summarize_session
                summary = summarize_session(session_id, messages)
                if summary.decisions or summary.facts_learned or summary.preferences_mentioned:
                    self._long_term_memory.add(
                        "session_summary",
                        summary.to_text(),
                        tags=summary.tags,
                    )
            except Exception:
                logger.debug("Auto-summarise skipped for %s", session_id, exc_info=True)

    def clear_history(self, session_id: str) -> None:
        """Discard conversation history for *session_id*."""
        self._history.pop(session_id, None)
        if self._session_store is not None:
            self._session_store.save(session_id, [])
