"""P4b — Tool category definitions with simplified grouping.

Categories are aligned with the P4b reorg:
  FILE    — filesystem tools (read, write, edit)
  ENV     — environment tools (bash, search, fetch, ollama)
  MEDIA   — media generation (image, music, video)
  SESSION — session interaction (ask_user, plan_mode, todo_write)
  COLLAB  — collaboration tools (sub_agent, MCP, messaging)
  MEMORY  — memory operations (memory_search, memory_write)
"""

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

    FILE = auto()       # read, write, edit, send_file
    ENV = auto()        # bash, search, fetch, ollama, set_model
    MEDIA = auto()      # image, music, video generation
    SESSION = auto()    # ask_user, plan_mode, todo_write (reserved)
    COLLAB = auto()     # sub_agent, MCP, messaging, notifications
    MEMORY = auto()     # memory operations

    def default_policy(self) -> ToolPolicy:
        """Return the recommended ToolPolicy for this category."""
        from .policy import ToolPolicy

        _defaults = {
            ToolCategory.FILE:     ToolPolicy(require_confirm=True, timeout=10.0, rate_limit=0.8),
            ToolCategory.ENV:      ToolPolicy(require_confirm=True, timeout=30.0, rate_limit=1.5),
            ToolCategory.MEDIA:    ToolPolicy(timeout=60.0, rate_limit=15.0),
            ToolCategory.SESSION:  ToolPolicy(require_confirm=True, timeout=30.0, rate_limit=1.5),
            ToolCategory.COLLAB:   ToolPolicy(require_confirm=True, timeout=30.0, rate_limit=1.5),
            ToolCategory.MEMORY:   ToolPolicy(timeout=10.0, rate_limit=0.8),
        }
        return _defaults.get(self, ToolPolicy())
