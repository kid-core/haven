"""State-machine ReAct loop: wires ToolRegistry + BaseProvider together (Phase 2a extended).

Inherits shared provider-fallback and tool-execution infrastructure from
BaseReActLoop (see base_react_loop.py).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .base_provider import BaseProvider
from .base_react_loop import BaseReActLoop, _clean, TURN_LIMIT_MESSAGE
from .category_router import CategoryRouter, ExecutionMode
from .paths import ltm_dir
from .prompt_assembler import SystemPromptAssembler
from .budget import BudgetTracker
import sys as _sys
_sys.path.insert(0, "/mnt/z/Haven")

from .tool_registry import PolicyBlockedError, ToolRegistry
from agent.tool_output import wrap_output
from .pending_file import PendingFileStore, set_pending_file_store, set_current_session

if TYPE_CHECKING:
    from learning.skill_store import SkillStore
    from soul.memory import LongTermMemory, SessionStore

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools. "
    "Use them when needed."
)

class Router(BaseReActLoop):
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
        prompt_assembler: SystemPromptAssembler | None = None,
        session_store: SessionStore | None = None,
        long_term_memory: LongTermMemory | None = None,
        skill_store: SkillStore | None = None,
        default_timeout: float = 30.0,
        category_router: CategoryRouter | None = None,
        transport_names: list[str] | None = None,
        budget_tracker: BudgetTracker | None = None,
    ) -> None:
        # Normalise: single provider -> list of one
        if isinstance(providers, BaseProvider):
            norm_providers: list[tuple[BaseProvider, str | None]] = [
                (providers, None)
            ]
        else:
            norm_providers = providers

        super().__init__(tool_registry, norm_providers)

        self._system_prompt = system_prompt
        self._prompt_assembler = prompt_assembler
        self._budget_tracker = budget_tracker
        self._transport_names = transport_names or []
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

        # Phase 6 — background task system
        from tools.background_task import set_task_manager, set_background_context

        from core.task_manager import TaskManager

        self.task_manager = TaskManager(
            max_concurrent=5,
            storage_path=str(ltm_dir() / "tasks.json"),
            archive_path=str(ltm_dir() / "tasks_archive.json"),
            auto_persist=True,
        )
        set_task_manager(self.task_manager)

        # Universal file delivery — PendingFileStore (Phase 11)
        self._pending_files = PendingFileStore()
        set_pending_file_store(self._pending_files)

        # Phase 7 — schedule orchestrator
        from tools.schedule_tool import set_scheduler

        from .scheduler import Scheduler

        self.scheduler = Scheduler(
            task_manager=self.task_manager,
            storage_path=str(ltm_dir() / "schedules.json"),
        )
        set_scheduler(self.scheduler)

        self._default_timeout = default_timeout  # Phase 0

        # ── Observability (P0) ───────────────────────────────────
        from .tracer import Tracer
        self._tracer = Tracer()

        # ── Circuit breakers per provider (P0) ──────────────────────
        from .circuit_breaker import CircuitBreaker
        self._breakers: dict[int, CircuitBreaker] = {}
        for p, _ in self._providers:
            model_name = getattr(p, "get_model", lambda: "unknown")()
            cb = CircuitBreaker(
                name=f"{type(p).__name__}:{model_name}",
                failure_threshold=3,
                cooldown_seconds=30.0,
            )
            self._breakers[id(p)] = cb

        # ── Startup health check (P1) ─────────────────────────────
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._health_check())
        except RuntimeError:
            pass  # no event loop yet (e.g. during tests)

        # Wire background agent context (Phase 10) — must be after self._providers
        set_background_context(
            providers=self._providers,
            tool_registry=self._registry,
        )

        # Wire model switching tool
        from tools.set_model import set_providers as _set_providers
        _set_providers(self._providers)

        # Phase 1b — category-aware routing
        self._cat_router = category_router or CategoryRouter()

    # ==================================================================
    # BaseReActLoop hooks — provider fallback
    # ==================================================================

    def _should_skip_provider(self, provider: BaseProvider) -> bool:
        """Skip provider if its circuit breaker is open."""
        breaker = self._breakers.get(id(provider))
        return breaker is not None and not breaker.allow_request()

    def _on_provider_start(self, provider: BaseProvider) -> None:
        """Open a tracer span for this provider call."""
        self._tracer.span(
            "provider",
            provider=type(provider).__name__,
            model=getattr(provider, "get_model", lambda: "?")(),
        )

    def _on_provider_success(self, provider: BaseProvider) -> None:
        """Record success to circuit breaker."""
        breaker = self._breakers.get(id(provider))
        if breaker:
            breaker.record_success()

    def _on_provider_error(self, provider: BaseProvider, exc: Exception) -> None:
        """Record failure to circuit breaker."""
        breaker = self._breakers.get(id(provider))
        if breaker:
            breaker.record_failure()

    # ==================================================================
    # BaseReActLoop hooks — tool execution
    # ==================================================================

    def _pre_tool_check(self, name: str, arguments: dict) -> dict | None:
        """Check if tool requires user confirmation; short-circuit if so."""
        if self._registry.is_confirm_required(name):
            import json
            return {
                "role": "tool",
                "tool_call_id": "",
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
        return None

    # ==================================================================
    # Public API
    # ==================================================================

    async def process(
        self,
        user_message: str,
        session_id: str = "default",
        max_turns: int = 30,
    ) -> str:
        """Run the ReAct loop for a single user message."""
        self._tracer.start()
        self._tracer.set_tag("session_id", session_id)

        messages = self._get_or_init_history(session_id)
        messages.append({"role": "user", "content": _clean(user_message)})
        tools = self._registry.get_openai_tools() or None

        for _turn in range(max_turns):
            # ------ call the model (with fallback + circuit breakers) ------
            response, err = await self._call_providers(messages, tools)
            if response is None:
                self._tracer.log_summary()
                return f"All providers failed. Last error: {err}" if err else "No providers configured."

            # P4c — record token usage for budget tracking
            if self._budget_tracker is not None and response.usage is not None:
                model = self._providers[0][0].get_model() if self._providers else "unknown"
                self._budget_tracker.record(
                    model,
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )

            content: str | None = response.content
            tool_calls: list[dict[str, Any]] | None = response.tool_calls
            reasoning_content: str | None = response.reasoning_content

            # ------ text response -> done -----------------------------------
            if not tool_calls:
                text = _clean(content or "")
                assistant_msg = self.build_assistant_msg(text)
                if reasoning_content:
                    assistant_msg["reasoning_content"] = _clean(reasoning_content)
                messages.append(assistant_msg)
                self._save_history(session_id, messages)
                self._tracer.log_summary()
                return text

            # ------ tool-call turn ------------------------------------------
            assistant_msg = self.build_assistant_msg(
                content, tool_calls=tool_calls,
            )
            if reasoning_content:
                assistant_msg["reasoning_content"] = _clean(reasoning_content)
            messages.append(assistant_msg)

            for tc in tool_calls:
                tc_id: str = tc.get("id", "")
                fn: dict[str, Any] = tc.get("function", {})
                name: str = fn.get("name", "")
                arguments: dict[str, Any] = fn.get("arguments", {})
                set_current_session(session_id)

                if isinstance(arguments, str):
                    import json
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                with self._tracer.span("tool", tool_name=name):
                    result_msg = await self._execute_tool(
                        tool_call_id=tc_id, name=name, arguments=arguments,
                    )
                messages.append(result_msg)

        self._save_history(session_id, messages)
        return TURN_LIMIT_MESSAGE

    # ==================================================================
    # Tool execution with Phase 0 + Phase 1b enforcement
    # ==================================================================

    async def _execute_tool(
        self, tool_call_id: str, name: str, arguments: dict,
    ) -> dict:
        """Execute a tool with policy checks, timeout, and category routing.

        Overrides the base _execute_tool() because Router needs:
        - 2-attempt smart retry
        - Category-aware routing (AI_PROXY mode)
        - Structured ToolOutput wrapping (wrap_output)
        - Skill observation (Phase 3)
        """
        import json

        # Pre-check hook — confirmation gate
        pre = self._pre_tool_check(name, arguments)
        if pre is not None:
            return pre

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

        # ── Smart retry: try once, retry once on transient errors ─────
        last_error: str | None = None
        error_code: str = "UNKNOWN"
        retryable: bool = False
        did_retry = False
        tool_result: dict | None = None

        for attempt in range(2):  # max 2 attempts
            try:
                raw = await asyncio.wait_for(
                    self._registry.execute(
                        tool_call_id=tool_call_id,
                        name=name,
                        arguments=arguments,
                    ),
                    timeout=timeout,
                )
                tool_result = raw
                last_error = None
                break
            except asyncio.TimeoutError:
                logger.warning(
                    "Tool %r timed out (attempt %d/2)", name, attempt + 1,
                )
                if attempt == 0:
                    continue
                last_error = f"Tool {name!r} timed out after {timeout}s."
                error_code = "TIMEOUT"
                retryable = True
                break
            except PolicyBlockedError as exc:
                logger.info("Tool %r blocked by policy: %s", name, exc.reason)
                last_error = f"Policy blocked: {exc.reason}"
                error_code = "PERMISSION_DENIED"
                retryable = False
                did_retry = True
                break
            except FileNotFoundError as exc:
                err_str = str(exc)
                logger.warning("Tool %r file not found: %s", name, err_str[:120])
                last_error = err_str
                error_code = "FILE_NOT_FOUND"
                retryable = False
                did_retry = True
                break
            except Exception as exc:
                err_str = str(exc)
                logger.warning(
                    "Tool %r error (attempt %d/2): %s",
                    name, attempt + 1, err_str[:120],
                )
                last_error = err_str
                error_code = "API_ERROR"
                retryable = True
                did_retry = True
                if attempt == 0:
                    continue
                break

        # ── Build ToolOutput-wrapped result ─────────────────────────
        if last_error is not None:
            logger.info(
                "Tool %r failed after 2 attempts: %s", name, last_error[:150],
            )
            output = wrap_output(
                status="failure",
                error={"code": error_code, "message": last_error, "retryable": retryable},
            )
        else:
            raw_content = tool_result.get("content") if isinstance(tool_result, dict) else str(tool_result)
            output = wrap_output(status="success", data=raw_content)
            if did_retry:
                logger.info("Tool %r succeeded on retry", name)

        result_msg = self.build_tool_result_msg(tool_call_id, json.dumps(output))

        # Phase 3: observe tool call for pattern learning
        if self._skill_factory is not None and spec is not None:
            success = output["status"] == "success"
            self._skill_factory.observe(
                tool_name=name,
                arguments=arguments,
                category=spec.category,
                success=success,
                session_id="",  # filled by caller if needed
                response_preview=json.dumps(output)[:200],
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

            # Build system prompt — use P4a assembler when available
            if self._prompt_assembler is not None:
                prompt = self._prompt_assembler.build(session_id=session_id)
            else:
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

            # Inject capability summary (fresh from Router state)
            prompt += self._build_capability_summary()

            self._history[session_id] = [
                {"role": "system", "content": prompt}
            ]
        return self._history[session_id]

    def _build_capability_summary(self) -> str:
        """Build a fresh capability summary from current Router state."""
        tools = [
            t["function"]["name"]
            for t in self._registry.get_openai_tools()
        ]
        models = []
        for p, _ in self._providers:
            try:
                models.append(p.get_model())
            except Exception:
                models.append(type(p).__name__)
        transports = self._transport_names or []

        lines = [
            "",
            "[Current Capabilities]",
        ]
        if tools:
            lines.append(f"Tools: {', '.join(sorted(tools))}")
        if models:
            lines.append(f"Models: {', '.join(models)}")
        if transports:
            lines.append(f"Platforms: {', '.join(transports)}")
        return "\n".join(lines)

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

    def pop_pending_files(self, session_id: str) -> list:
        """Dequeue and return pending file deliveries for *session_id*."""
        return self._pending_files.pop_all(session_id)

    # ── Startup health check (P1) ───────────────────────────────

    async def _health_check(self) -> None:
        """Ping each provider at startup to validate API keys."""
        for provider, _ in self._providers:
            name = type(provider).__name__
            try:
                async with asyncio.timeout(5):
                    ok = await provider.ping()
                if ok:
                    logger.info("Health check OK: %s", name)
                else:
                    logger.warning("Health check FAIL: %s — ping returned False", name)
            except asyncio.TimeoutError:
                logger.warning("Health check TIMEOUT: %s (5s)", name)
            except Exception as exc:
                logger.warning("Health check FAIL: %s — %s", name, exc)

    # ── Phase 7: Scheduler lifecycle ───────────────────────────────

    async def start_scheduler(self) -> None:
        """Start the schedule watcher (called after transports are ready)."""
        await self.scheduler.start()

    async def close_scheduler(self) -> None:
        """Graceful shutdown of the scheduler (persist + cancel watcher)."""
        await self.scheduler.close()

    # ── Phase 9: Task persistence ─────────────────────────────────

    async def restore_tasks(self) -> dict[str, int]:
        """Restore persisted task records after a restart.

        Returns a dict with "restored" and "interrupted" counts.
        """
        return await self.task_manager._restore()
