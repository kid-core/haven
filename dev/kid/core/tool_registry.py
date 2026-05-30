"""ToolRegistry: holds tools and dispatches OpenAI-format tool calls (Phase 0 extended)."""

from __future__ import annotations

import json
from typing import Any

from .policy import RateLimitTracker
from .models import ToolResult
from .tool_spec import ToolSpec


class PolicyBlockedError(Exception):
    """Raised when a tool call is blocked by policy."""

    def __init__(self, tool_name: str, reason: str) -> None:
        super().__init__(f"Tool {tool_name!r} blocked: {reason}")
        self.tool_name = tool_name
        self.reason = reason


class ToolRegistry:
    """Holds registered tools and dispatches OpenAI-format tool calls.

    Phase 0 additions:
        - Policy enforcement (enabled, require_confirm, rate_limit).
        - RateLimitTracker for per-tool cooldown.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._rate_tracker = RateLimitTracker()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add(self, spec: ToolSpec) -> ToolSpec:
        """Register a pre-built ToolSpec."""
        self._tools[spec.name] = spec
        return spec

    def get_openai_tools(self) -> list[dict]:
        """Return tool definitions in OpenAI format (enabled tools only)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
            if spec.policy.enabled
        ]

    # ------------------------------------------------------------------
    # Policy check (public, usable by Router)
    # ------------------------------------------------------------------

    def check_policy(self, name: str) -> tuple[bool, str]:
        """Check if *name* passes all policy gates.

        Returns (allowed, reason).
        """
        spec = self._tools.get(name)
        if spec is None:
            return False, f"Unknown tool: {name!r}"

        policy = spec.policy

        # Gate 1: enabled
        if not policy.enabled:
            return False, f"Tool {name!r} is disabled by policy."

        # Gate 2: rate limit
        if policy.rate_limit is not None:
            ok, wait = self._rate_tracker.check(name, policy.rate_limit)
            if not ok:
                return False, f"Rate limited — wait {wait}s before calling {name!r} again."

        # Gate 3: require_confirm handled by Router, not here
        return True, "ok"

    def is_confirm_required(self, name: str) -> bool:
        """Whether this tool requires confirmation before execution."""
        spec = self._tools.get(name)
        if spec is None:
            return False
        return spec.policy.require_confirm

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        tool_call_id: str,
        name: str,
        arguments: dict,
    ) -> dict:
        """Look up *name*, enforce policy, call its handler.

        Returns an OpenAI-compatible result.
        Raises PolicyBlockedError when the tool is blocked.
        """
        spec = self._tools.get(name)
        if spec is None:
            content = json.dumps({"error": f"Unknown tool: {name!r}"})
        else:
            # Policy gates
            ok, reason = self.check_policy(name)
            if not ok:
                raise PolicyBlockedError(name, reason)

            # Record rate limit
            if spec.policy.rate_limit is not None:
                self._rate_tracker.record(name)

            try:
                result = await spec.handler(**arguments)
                content = json.dumps(result) if not isinstance(result, str) else result
            except Exception as exc:
                content = json.dumps({"error": str(exc)})

        return ToolResult(tool_call_id=tool_call_id, content=content).model_dump()

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> ToolSpec | None:
        """Retrieve a ToolSpec by name, or None."""
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self):
        return iter(self._tools.values())
