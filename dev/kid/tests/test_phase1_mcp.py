"""Phase 1a tests — MCP client, config, discovery, bridging."""

import pytest
from tools.mcp.client import MCPError, MCPStdioClient, MCPSseClient
from tools.mcp.registry import MCPServerConfig, MCPBridge
from core.tool_registry import ToolRegistry


class TestMCPServerConfig:
    def test_stdio_config(self):
        c = MCPServerConfig(name="fs", transport="stdio", command="echo", args=["hello"])
        assert c.name == "fs"
        client = c.create_client()
        assert isinstance(client, MCPStdioClient)

    def test_sse_config(self):
        c = MCPServerConfig(name="gh", transport="sse", url="http://localhost:8765/mcp")
        client = c.create_client()
        assert isinstance(client, MCPSseClient)

    def test_disabled_config(self):
        c = MCPServerConfig(name="off", transport="stdio", command="echo", enabled=False)
        assert c.enabled is False

    def test_missing_command(self):
        c = MCPServerConfig(name="bad", transport="stdio")
        with pytest.raises(ValueError, match="missing command"):
            c.create_client()

    def test_missing_url(self):
        c = MCPServerConfig(name="bad", transport="sse")
        with pytest.raises(ValueError, match="missing url"):
            c.create_client()


class TestMCPError:
    def test_basic(self):
        err = MCPError("something went wrong")
        assert "something went wrong" in str(err)


class TestMCPBridge:
    def test_empty_bridge(self):
        reg = ToolRegistry()
        bridge = MCPBridge(reg)
        assert bridge.attached_servers() == []

    def test_disabled_server_skipped(self):
        reg = ToolRegistry()
        bridge = MCPBridge(reg)
        import asyncio
        result = asyncio.run(bridge.attach(
            MCPServerConfig(name="off", transport="stdio", command="echo", enabled=False)
        ))
        assert result == []
