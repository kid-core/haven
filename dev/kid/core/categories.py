"""Tool category definitions for Phase 0 policy layer."""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .policy import ToolPolicy


class ToolCategory(Enum):
    """Categories for tool classification and routing.

    Used by the policy layer to group tools by their domain,
    enabling per-category rate limits, routing decisions, and profiles.
    """

    FILES = auto()          # read, write, edit
    SYSTEM = auto()         # cmd, process
    WEB = auto()            # search, fetch
    AI = auto()             # image, music, video generation
    COMMUNICATION = auto()  # message, notification
    MEMORY = auto()         # memory operations
    EXTERNAL = auto()       # MCP tools, third-party integrations

    def default_policy(self) -> "ToolPolicy":
        """Return the recommended ToolPolicy for this category.

        Used as a sensible default when registering new tools.
        Tool authors can override via @tool(policy=...).
        """
        # Lazy import to avoid circular deps at module level
        from .policy import ToolPolicy

        _defaults = {
            ToolCategory.FILES:         ToolPolicy(require_confirm=True, timeout=10.0, rate_limit=2.0),
            ToolCategory.SYSTEM:        ToolPolicy(require_confirm=True, timeout=30.0, rate_limit=10.0),
            ToolCategory.WEB:           ToolPolicy(timeout=15.0, rate_limit=5.0),
            ToolCategory.AI:            ToolPolicy(timeout=60.0, rate_limit=30.0),
            ToolCategory.COMMUNICATION: ToolPolicy(require_confirm=True, timeout=20.0, rate_limit=5.0),
            ToolCategory.MEMORY:        ToolPolicy(timeout=10.0, rate_limit=2.0),
            ToolCategory.EXTERNAL:      ToolPolicy(require_confirm=True, timeout=30.0, rate_limit=10.0),
        }
        return _defaults.get(self, ToolPolicy())
