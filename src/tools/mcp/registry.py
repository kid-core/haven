"""MCP registry — bridge MCP server tools into Haven's ToolRegistry."""

from __future__ import annotations

import logging
from typing import Any

from core.tool_registry import ToolRegistry

from tools.mcp.client import MCPClient, MCPSseClient, MCPStdioClient
from tools.mcp.discovery import discover_tools

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MCP server config
# ---------------------------------------------------------------------------

class MCPServerConfig:
    """Descriptor for one MCP server connection.

    Supports two transports:

    - stdio: ``command`` + ``args`` to spawn a process.
    - sse:   ``url`` to connect to an HTTP SSE endpoint.

    Example config (YAML-like):

        name: filesystem
        transport: stdio
        command: npx
        args: ["-y", "@anthropic/mcp-filesystem", "/mnt/z"]

        name: github
        transport: sse
        url: http://localhost:8765/mcp
    """

    def __init__(
        self,
        name: str,
        transport: str = "stdio",
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.name = name
        self.transport = transport
        self.command = command
        self.args = args or []
        self.url = url
        self.enabled = enabled

    def create_client(self) -> MCPClient:
        """Create the appropriate MCP client for this config."""
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(f"MCP stdio server {self.name!r} missing command")
            return MCPStdioClient(self.command, self.args)
        elif self.transport == "sse":
            if not self.url:
                raise ValueError(f"MCP SSE server {self.name!r} missing url")
            return MCPSseClient(self.url)
        raise ValueError(f"Unknown MCP transport: {self.transport!r}")


# ---------------------------------------------------------------------------
# MCP bridge
# ---------------------------------------------------------------------------

class MCPBridge:
    """Connects MCP servers to a ToolRegistry.

    Usage::

        bridge = MCPBridge(registry)
        await bridge.attach(MCPServerConfig(name="fs", command="npx",
                            args=["-y", "@anthropic/mcp-filesystem", "/mnt/z"]))
        # All MCP tools now available as mcp__fs__* in the registry
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._clients: dict[str, MCPClient] = {}

    async def attach(self, config: MCPServerConfig) -> list[str]:
        """Connect to an MCP server and register its tools.

        Returns the names of the tools that were registered.
        """
        if not config.enabled:
            logger.info("MCP %s: disabled, skipping", config.name)
            return []

        client = config.create_client()
        try:
            await client.connect()
        except Exception as exc:
            logger.error("MCP %s: connection failed — %s", config.name, exc)
            return []

        # Discover and register
        specs = await discover_tools(client, config.name)
        if not specs:
            logger.warning("MCP %s: no tools discovered, disconnecting", config.name)
            await client.disconnect()
            return []

        for spec in specs:
            self._registry.add(spec)

        self._clients[config.name] = client
        return [s.name for s in specs]

    async def attach_from_config(self, config: dict[str, Any]) -> list[str]:
        """Attach from a dict config (e.g. parsed from a YAML/JSON config file)."""
        server_config = MCPServerConfig(
            name=config["name"],
            transport=config.get("transport", "stdio"),
            command=config.get("command"),
            args=config.get("args", []),
            url=config.get("url"),
            enabled=config.get("enabled", True),
        )
        return await self.attach(server_config)

    async def detach_all(self) -> None:
        """Disconnect all MCP servers and remove their tools."""
        for name, client in self._clients.items():
            try:
                await client.disconnect()
            except Exception:
                logger.warning("MCP %s: error during disconnect", name, exc_info=True)
        self._clients.clear()

    def attached_servers(self) -> list[str]:
        """Return names of currently attached MCP servers."""
        return list(self._clients.keys())
