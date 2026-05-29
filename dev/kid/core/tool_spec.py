"""ToolSpec: pure data container for tool metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Awaitable


@dataclass
class ToolSpec:
    """Describes a single tool that can be exposed to an LLM."""

    name: str
    description: str
    parameters: dict  # JSON Schema describing the arguments
    handler: Callable[..., Awaitable[Any]]
