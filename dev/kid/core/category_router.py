"""Category-based tool routing — execution strategies and provider mapping (Phase 1b)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from .categories import ToolCategory

if TYPE_CHECKING:
    from .base_provider import BaseProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Execution mode
# ---------------------------------------------------------------------------

class ExecutionMode(Enum):
    """How a tool category should be executed."""

    INLINE = auto()
    """Call the tool handler directly.  Used for FILES, SYSTEM, MEMORY, WEB, etc."""

    AI_PROXY = auto()
    """Execution is proxied through an AI provider.  
    The tool handler receives provider context for sub-LLM calls.
    Used for AI-category tools that need model access (image gen, etc)."""

    EXTERNAL = auto()
    """Execution is delegated to an external service / MCP bridge.
    Used for EXTERNAL-category tools."""


# ---------------------------------------------------------------------------
# Category routing rules
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CategoryRule:
    """Routing rule for a single tool category."""

    mode: ExecutionMode
    provider_role: str | None = None
    """If mode is AI_PROXY, which provider role to use (e.g. "vision", "default")."""
    supports_fallback: bool = True
    """Whether execution errors trigger provider fallback."""


# ---------------------------------------------------------------------------
# Default rules — matching the roadmap design
# ---------------------------------------------------------------------------

DEFAULT_RULES: dict[ToolCategory, CategoryRule] = {
    # Files  → inline handler, no LLM needed
    ToolCategory.FILES: CategoryRule(
        mode=ExecutionMode.INLINE,
        supports_fallback=False,
    ),
    # System (cmd) → inline handler, no LLM needed
    ToolCategory.SYSTEM: CategoryRule(
        mode=ExecutionMode.INLINE,
        supports_fallback=False,
    ),
    # Web → inline (Tavily handled inside the tool handler itself)
    ToolCategory.WEB: CategoryRule(
        mode=ExecutionMode.INLINE,
        supports_fallback=False,
    ),
    # AI → proxy through an AI provider (vision models, etc.)
    ToolCategory.AI: CategoryRule(
        mode=ExecutionMode.AI_PROXY,
        provider_role="default",
        supports_fallback=True,
    ),
    # Communication → inline
    ToolCategory.COMMUNICATION: CategoryRule(
        mode=ExecutionMode.INLINE,
        supports_fallback=False,
    ),
    # Memory → inline handler
    ToolCategory.MEMORY: CategoryRule(
        mode=ExecutionMode.INLINE,
        supports_fallback=False,
    ),
    # External (MCP) → external delegate
    ToolCategory.EXTERNAL: CategoryRule(
        mode=ExecutionMode.EXTERNAL,
        supports_fallback=False,
    ),
}


# ---------------------------------------------------------------------------
# CategoryRouter
# ---------------------------------------------------------------------------

class CategoryRouter:
    """Routes tool execution based on category metadata.

    Integrated into the main Router to provide category-aware execution
    decisions and provider hints.

    Usage::

        cat_router = CategoryRouter()
        cat_router.set_provider("default", deepseek)
        cat_router.set_provider("vision", vision_model)

        rule = cat_router.get_rule(tool_spec.category)
        if rule.mode == ExecutionMode.AI_PROXY:
            provider = cat_router.get_provider_for(rule.provider_role)
    """

    def __init__(self) -> None:
        self._rules: dict[ToolCategory, CategoryRule] = dict(DEFAULT_RULES)
        self._providers: dict[str, "BaseProvider"] = {}

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def get_rule(self, category: ToolCategory) -> CategoryRule:
        """Return the routing rule for a category. Falls back to INLINE."""
        return self._rules.get(category, CategoryRule(mode=ExecutionMode.INLINE))

    def set_rule(self, category: ToolCategory, rule: CategoryRule) -> None:
        """Override the default routing rule for a category."""
        self._rules[category] = rule

    # ------------------------------------------------------------------
    # Provider management
    # ------------------------------------------------------------------

    def set_provider(self, role: str, provider: "BaseProvider") -> None:
        """Register a provider for a named role (e.g. "default", "vision")."""
        self._providers[role] = provider
        logger.info("CategoryRouter: provider %r registered for role %r",
                    type(provider).__name__, role)

    def get_provider(self, role: str | None) -> "BaseProvider | None":
        """Retrieve a provider by role name, or None."""
        if role is None:
            return None
        return self._providers.get(role)

    # ------------------------------------------------------------------
    # Execution helpers used by Router
    # ------------------------------------------------------------------

    def should_inline(self, category: ToolCategory) -> bool:
        """Whether this category executes inline (no provider proxy needed)."""
        return self.get_rule(category).mode in (
            ExecutionMode.INLINE, ExecutionMode.EXTERNAL
        )

    def needs_provider(self, category: ToolCategory) -> bool:
        """Whether this category needs an AI provider for execution."""
        return self.get_rule(category).mode == ExecutionMode.AI_PROXY

    def get_provider_for(self, category: ToolCategory) -> "BaseProvider | None":
        """Get the provider to use for AI_PROXY categories."""
        rule = self.get_rule(category)
        if rule.mode != ExecutionMode.AI_PROXY:
            return None
        return self.get_provider(rule.provider_role)
