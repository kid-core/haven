"""ToolSpec: pure data container for tool metadata (Phase 0 extended)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from .categories import ToolCategory
from .policy import ToolPolicy


@dataclass
class ToolSpec:
    """Describes a single tool that can be exposed to an LLM.

    Phase 0 additions:
        category:  ToolCategory enum for grouping and routing.
        policy:    Per-tool gates (confirm, rate_limit, timeout, enabled).
    """

    name: str
    description: str
    parameters: dict  # JSON Schema describing the arguments
    handler: Callable[..., Awaitable[Any]]
    category: ToolCategory = ToolCategory.SYSTEM
    policy: ToolPolicy = field(default_factory=ToolPolicy)
