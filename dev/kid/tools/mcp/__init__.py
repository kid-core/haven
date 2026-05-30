"""MCP (Model Context Protocol) integration for Haven — Phase 1a."""

from tools.mcp.client import MCPClient, MCPStdioClient, MCPSseClient, MCPError
from tools.mcp.discovery import discover_tools
from tools.mcp.registry import MCPBridge, MCPServerConfig

__all__ = [
    "MCPBridge",
    "MCPClient",
    "MCPError",
    "MCPServerConfig",
    "MCPSseClient",
    "MCPStdioClient",
    "discover_tools",
]
