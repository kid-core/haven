"""ToolRegistry: holds tools and dispatches OpenAI-format tool calls."""

from __future__ import annotations

import json
from typing import Any

from .models import ToolResult
from .tool_spec import ToolSpec


class ToolRegistry:
    """Holds registered tools and dispatches OpenAI-format tool calls."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def add(self, spec: ToolSpec) -> ToolSpec:
        """Register a pre-built ToolSpec."""
        self._tools[spec.name] = spec
        return spec

    def get_openai_tools(self) -> list[dict]:
        """Return tool definitions in OpenAI format."""
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
        ]

    async def execute(
        self,
        tool_call_id: str,
        name: str,
        arguments: dict,
    ) -> dict:
        """Look up *name*, call its handler, return an OpenAI-compatible result."""
        spec = self._tools.get(name)
        if spec is None:
            content = json.dumps({"error": f"Unknown tool: {name!r}"})
        else:
            try:
                result = await spec.handler(**arguments)
                content = json.dumps(result) if not isinstance(result, str) else result
            except Exception as exc:
                content = json.dumps({"error": str(exc)})

        return ToolResult(tool_call_id=tool_call_id, content=content).model_dump()

    def get(self, name: str) -> ToolSpec | None:
        """Retrieve a ToolSpec by name, or None."""
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self):
        return iter(self._tools.values())
