"""Web search tool using the Tavily API."""

from __future__ import annotations

import os

import httpx
from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.tool_decorator import tool

TAVILY_URL = "https://api.tavily.com/search"


@tool(
    category=ToolCategory.WEB,
    policy=ToolPolicy(timeout=15.0, rate_limit=5.0),
)
async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for current information via Tavily.

    Parameters
    ----------
    query:
        The search query.
    max_results:
        Number of results to return (1-10).

    Returns
    -------
    Formatted search results or an error message string.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Error: TAVILY_API_KEY not configured."

    max_results = max(1, min(max_results, 10))

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "include_answer": False,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(TAVILY_URL, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        return f"Web search timed out for: {query}"
    except httpx.HTTPStatusError as exc:
        return f"Search API error ({exc.response.status_code}): {exc.response.text[:200]}"
    except Exception as exc:
        return f"Search failed: {exc}"

    results = data.get("results", [])
    if not results:
        return f"No results found for: {query}"

    lines: list[str] = [
        f"## Web search results: {query}",
        "",
    ]
    for i, r in enumerate(results[:max_results], 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        snippet = r.get("content", r.get("snippet", ""))
        lines.append(f"**{i}. {title}**")
        lines.append(f"   {snippet[:250]}")
        lines.append(f"   <{url}>")
        lines.append("")

    return "\n".join(lines).strip()
