"""Memory search and management tool for long-term memory access."""

from __future__ import annotations

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.tool_decorator import tool
from soul.memory import LongTermMemory

# Single shared instance — created lazily
_ltm: LongTermMemory | None = None


def get_ltm() -> LongTermMemory:
    global _ltm
    if _ltm is None:
        _ltm = LongTermMemory()
    return _ltm


@tool(
    category=ToolCategory.MEMORY,
    policy=ToolPolicy(timeout=10.0, rate_limit=2.0),
)
async def memory_search(
    action: str,
    query: str | None = None,
    content: str | None = None,
    tags: str | None = None,
    entry_type: str | None = None,
    limit: int = 10,
) -> str:
    """Access and manage long-term memory.

    Actions:
      search  — Find memories matching the query string.
      add     — Store a new memory. Requires content and optional tags (comma-separated).
      recent  — List recently added memories.
      delete  — Remove a memory by id. Requires query to be the memory id.

    Args:
        action:  One of: search, add, recent, delete.
        query:   Search keyword, or memory id for delete action.
        content: Text content of the memory (for add action).
        tags:    Comma-separated tags (for add action).
        entry_type: Memory type: fact, preference, skill, or session_summary.
        limit:   Max results to return (1-50).

    Returns:
        Formatted search results or confirmation message.
    """
    ltm = get_ltm()
    limit = max(1, min(limit, 50))

    if action == "search":
        if not query:
            return "[error] 'query' parameter required for search action."
        _type = entry_type if entry_type in ("fact", "preference", "skill", "session_summary") else None
        results = ltm.search(query, limit=limit, type_filter=_type)
        return _format_results(results, f"Search results for: {query}")

    elif action == "add":
        if not content:
            return "[error] 'content' parameter required for add action."
        _type = entry_type if entry_type in ("fact", "preference", "skill", "session_summary") else "fact"
        _tags: list[str] = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        entry = ltm.add(type_=_type, content=content, tags=_tags)  # type: ignore[arg-type]
        return f"[ok] Memory stored (id={entry.id}, type={_type}): {content[:100]}"

    elif action == "recent":
        results = ltm.get_recent(limit=limit)
        return _format_results(results, f"Recent memories (last {limit})")

    elif action == "delete":
        if not query:
            return "[error] 'query' (memory id) required for delete action."
        if ltm.remove(query):
            return f"[ok] Memory {query} deleted."
        return f"[error] Memory {query} not found."

    return f"[error] Unknown action: {action!r}.  Valid actions: search, add, recent, delete."


def _format_results(entries: list, title: str) -> str:
    """Format memory entries as a readable string."""
    if not entries:
        return f"No memories found for: {title}"

    from soul.memory.long_term import MemoryEntry

    lines = [f"## {title}", ""]
    for i, e in enumerate(entries, 1):
        if not isinstance(e, MemoryEntry):
            continue
        tag_str = f" [{', '.join(e.tags)}]" if e.tags else ""
        lines.append(f"**{i}. [{e.type}]** {e.content[:200]}")
        lines.append(f"   id={e.id}  accessed={e.access_count}×{tag_str}")
        lines.append("")
    return "\n".join(lines).strip()
