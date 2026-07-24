"""Phase 10 — Autonomous background agent with its own ReAct loop.

A BackgroundAgent is spawned by ``background_task`` and executes a
goal-driven ReAct loop autonomously.  It has its own:
- Message history (with the goal as system prompt)
- Full tool registry access
- Provider calls (same fallback chain as the main Router)
- Task context for progress reporting via the MessageBus

Lifecycle:
1. ``spawn()`` creates the agent and starts its loop as a TaskManager task.
2. Agent runs: goal → tool calls → observe → next turn.
3. Agent terminates when goal is reached, max_turns exhausted, or timeout.
4. The parent (or any task) can query status via ``query_task`` and
   receive progress messages via ``check_task_messages``.

Inherits shared provider-fallback and tool-execution infrastructure from
BaseReActLoop (see base_react_loop.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from .base_react_loop import BaseReActLoop, _clean, TURN_LIMIT_MESSAGE
from .base_provider import BaseProvider
from .task_complexity import TaskComplexityEstimator
from .tool_registry import ToolRegistry

if TYPE_CHECKING:
    from .message_bus import TaskContext
    from .router import Router

logger = logging.getLogger(__name__)


class BackgroundAgent(BaseReActLoop):
    """Autonomous goal-driven ReAct agent that runs in a background task.

    Args:
        goal: The natural-language goal this agent should accomplish.
        tool_registry: The shared ToolRegistry (all tools available).
        providers: The same provider fallback chain as the main Router.
        task_context: A TaskContext for sending/receiving messages via MessageBus.
        system_prompt_extra: Extra system instructions for this agent.
        tools_allow: If set, restrict tool access to these tool names only.
        max_turns: Maximum ReAct iterations before auto-termination.
        timeout: Max wall-clock seconds for the entire run.
    """

    def __init__(
        self,
        goal: str,
        tool_registry: ToolRegistry,
        providers: list[tuple[BaseProvider, str | None]],
        task_context: TaskContext | None = None,
        system_prompt_extra: str = "",
        tools_allow: list[str] | None = None,
        max_turns: int | None = None,
        timeout: float = 600.0,
        complexity_estimator: TaskComplexityEstimator | None = None,
    ) -> None:
        super().__init__(tool_registry, providers)

        # ── 決定 max_turns ──
        if max_turns is None:
            if complexity_estimator is not None:
                max_turns = complexity_estimator.estimate_turns(goal)
            else:
                max_turns = 60  # fallback

        self._goal = goal
        self._ctx = task_context
        self._tools_allow = set(tools_allow) if tools_allow else None
        self._max_turns = max_turns
        self._timeout = timeout

        # Build system prompt
        parts = [
            "You are an autonomous background agent running in Haven.",
            f"Your goal: {goal}",
            "Work step by step. Call tools as needed. Analyse results and continue.",
            "When you believe the goal is complete, respond with a final summary.",
            "Do not ask for user input — you must work autonomously.",
        ]
        if system_prompt_extra:
            parts.append(system_prompt_extra)
        self._system_prompt = "\n\n".join(parts)

        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt}
        ]
        self._is_done = False
        self._result: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_done(self) -> bool:
        return self._is_done

    @property
    def result(self) -> str | None:
        return self._result

    def to_dict(self) -> dict[str, Any]:
        """Metadata snapshot for the TaskRecord."""
        return {
            "goal": self._goal[:200],
            "max_turns": self._max_turns,
            "turns_used": max(0, len(self._messages) - 1),  # minus system
        }

    async def run(self) -> str:
        """Execute the autonomous ReAct loop.

        Returns the final response string.
        """
        logger.info("Background agent starting: goal=%s", self._goal[:80])

        try:
            result = await asyncio.wait_for(
                self._run_loop(), timeout=self._timeout,
            )
        except TimeoutError:
            logger.warning("Background agent timed out after %ss: %s", self._timeout, self._goal[:60])
            result = f"[timeout] Agent did not complete within {self._timeout}s."

        self._is_done = True
        self._result = result

        # Send completion message if we have a context
        if self._ctx:
            await self._ctx.send_message(
                self._ctx.task_id,
                f"[agent_complete] {result[:500]}",
                subject="agent_complete",
                priority="alert",
            )

        logger.info("Background agent done: goal=%s → %s", self._goal[:60], result[:80])
        return result

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> str:
        """The actual ReAct loop — called by run() with timeout wrapping."""
        # Initial user message to kick off
        self._messages.append({
            "role": "user",
            "content": f"Your goal is: {self._goal}\n\nWork autonomously to complete this goal.",
        })

        # Resolve allowed tools
        if self._tools_allow:
            tools = [
                t for t in (self._registry.get_openai_tools() or [])
                if t.get("function", {}).get("name") in self._tools_allow
            ] or None
        else:
            tools = self._registry.get_openai_tools() or None

        for turn in range(self._max_turns):
            # -------- Send progress heartbeat --------
            if self._ctx and turn % 5 == 0 and turn > 0:
                progress = f"[progress] Turn {turn}/{self._max_turns}: still working on: {self._goal[:100]}"
                await self._ctx.send_message(
                    self._ctx.task_id,
                    progress,
                    subject="__progress__",
                )

            # -------- LLM call with fallback --------
            response, err = await self._call_providers(self._messages, tools)
            if response is None:
                return f"All providers failed. Last error: {err}"

            content: str | None = response.content
            tool_calls: list[dict[str, Any]] | None = response.tool_calls
            reasoning_content: str | None = response.reasoning_content

            # -------- Text response → goal complete --------
            if not tool_calls:
                self._messages.append(
                    self.build_assistant_msg(content)
                )
                return content or "(no response)"

            # -------- Tool-call turn --------
            assistant_msg = self.build_assistant_msg(
                content, tool_calls=tool_calls,
                reasoning_content=reasoning_content,
            )
            self._messages.append(assistant_msg)

            for tc in tool_calls:
                tc_id: str = tc.get("id", "")
                fn: dict[str, Any] = tc.get("function", {})
                name: str = fn.get("name", "")
                arguments: dict[str, Any] = fn.get("arguments", {})

                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                result_msg = await self._execute_tool(tc_id, name, arguments)
                self._messages.append(result_msg)

        return TURN_LIMIT_MESSAGE

    # ==================================================================
    # BaseReActLoop hooks — tool execution
    # ==================================================================

    def _pre_tool_check(self, name: str, arguments: dict) -> dict | None:
        """Enforce tool allowlist + block confirmation tools.

        Background agents are autonomous and cannot:
        - use tools outside their allowlist
        - ask for user confirmation
        """
        # Check tool allowlist
        if self._tools_allow and name not in self._tools_allow:
            return {
                "role": "tool",
                "tool_call_id": "",
                "content": json.dumps({
                    "error": f"Tool {name!r} is not in the allowed list for this agent.",
                }),
            }

        # Skip confirmation tools (background agents must be autonomous)
        if self._registry.is_confirm_required(name):
            return {
                "role": "tool",
                "tool_call_id": "",
                "content": json.dumps({
                    "error": f"Tool {name!r} requires user confirmation and cannot be used autonomously.",
                }),
            }

        return None

    # ------------------------------------------------------------------
    # Tool execution (uses base class version via hooks only)
    # ------------------------------------------------------------------

    # _execute_tool is inherited from BaseReActLoop — just the hooks above
    # provide the BackgroundAgent-specific checks.
