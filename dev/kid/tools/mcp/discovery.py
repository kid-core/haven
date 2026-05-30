"""MCP tool discovery — list and convert MCP tools to ToolSpec."""

from __future__ import annotations

import json
import logging
from typing import Any

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.tool_spec import ToolSpec

from tools.mcp.client import MCPClient, MCPError

logger = logging.getLogger(__name__)


async def discover_tools(client: MCPClient, server_name: str) -> list[ToolSpec]:
    """Query an MCP server for its tool list and convert to Haven ToolSpecs.

    All MCP tools are:
    - Prefixed with ``mcp__{server_name}__`` to avoid name clashes.
    - Assigned ``ToolCategory.EXTERNAL``.
    - Default to ``require_confirm=True`` (safe-by-default).

    Returns an empty list if the server returns no tools or fails.
    """
    try:
        resp = await client.call("tools/list")
    except MCPError as exc:
        logger.warning("MCP %s: tools/list failed: %s", server_name, exc)
        return []

    tools = resp.get("tools", [])
    if not tools:
        logger.info("MCP %s: no tools available", server_name)
        return []

    specs: list[ToolSpec] = []
    for raw in tools:
        name = raw.get("name", "unknown")
        prefixed = f"mcp__{server_name}__{name}"

        desc = raw.get("description", f"MCP tool: {name} (from {server_name})")
        input_schema = raw.get("inputSchema", {
            "type": "object", "properties": {}, "required": [],
        })

        spec = ToolSpec(
            name=prefixed,
            description=desc,
            parameters=input_schema,
            handler=_build_handler(client, name),
            category=ToolCategory.EXTERNAL,
            policy=ToolPolicy(require_confirm=True, timeout=30.0, rate_limit=10.0),
        )
        specs.append(spec)

    logger.info(
        "MCP %s: discovered %d tools: %s",
        server_name, len(specs),
        [raw.get("name") for raw in tools],
    )
    return specs


def _build_handler(client: MCPClient, tool_name: str):
    """Build an async handler that calls the MCP tool and returns its result."""

    async def _handler(**kwargs: Any) -> str:
        try:
            resp = await client.call("tools/call", {
                "name": tool_name,
                "arguments": kwargs,
            })
            # MCP tool results can be a list of content blocks
            content = resp.get("content", [])
            if isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        texts.append(block["text"])
                    elif isinstance(block, str):
                        texts.append(block)
                return "\n".join(texts) if texts else json.dumps(resp)
            return json.dumps(resp) if not isinstance(resp, str) else resp
        except MCPError as exc:
            return f"[MCP error] {tool_name}: {exc}"
        except Exception as exc:
            return f"[MCP error] {tool_name}: {exc}"

    return _handler
