"""P5a — On-demand skill expansion tool.

Replaces the old "inject all skill content into system prompt" model
with a two-stage approach:

  1. Registration  — skills appear as brief summaries in the system prompt
  2. Expansion     — the model calls skill_tool(name) to load full content

This keeps the system prompt lean while making all skills accessible
on demand.  Each expansion is cached for the session lifetime.

Tool spec::

    skill_tool(name="deploy-check")
    → returns full skill content (str)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.tool_decorator import tool
from core.categories import ToolCategory
from core.policy import ToolPolicy

if TYPE_CHECKING:
    from learning.skill_store import SkillStore

logger = logging.getLogger(__name__)

# Per-session cache: skill_name → content (reset each new session)
_session_cache: dict[str, str] = {}
_current_store: SkillStore | None = None


def set_skill_store(store: SkillStore | None = None) -> None:
    """Bind the skill store for the skill_tool to query."""
    global _current_store
    _current_store = store


def clear_session_cache() -> None:
    """Clear the per-session expansion cache."""
    _session_cache.clear()


@tool(
    name="skill_tool",
    description="Load the full instructions for a learned skill. "
                "Use this when you need detailed guidance for a specific skill "
                "mentioned in [Learned Skills].",
    category=ToolCategory.MEMORY,
    policy=ToolPolicy(timeout=5.0, rate_limit=10.0),
)
async def skill_tool(name: str) -> str:
    """Return the full content of a learned skill by name.

    The result is cached per-session so repeated calls for the same
    skill avoid re-reading from the store.
    """
    if not _current_store:
        return "No skill store configured."

    if name in _session_cache:
        logger.debug("skill_tool cache hit: %s", name)
        return _session_cache[name]

    skill = _current_store.get_by_name(name)
    if skill is None:
        available = [s.name for s in _current_store.get_active()]
        return (
            f"Skill '{name}' not found. "
            f"Available skills: {', '.join(available) if available else 'none'}."
        )

    content = (
        f"# {skill.name}\n\n"
        f"{skill.content}\n\n"
        f"(version {skill.version}, success rate: {skill.success_rate:.0%})"
    )
    _session_cache[name] = content
    logger.info("skill_tool expanded: %s (%d chars)", skill.name, len(content))
    return content
