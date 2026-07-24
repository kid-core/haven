"""P6 tests — MCP protocol client, discovery, bridge, and lifecycle.

Uses a FakeMCPClient for most protocol tests and a real stdio
subprocess for one end-to-end integration test.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from core.categories import ToolCategory
from core.tool_registry import ToolRegistry
from tools.mcp.client import MCPClient, MCPError, MCPSseClient, MCPStdioClient
from tools.mcp.discovery import discover_tools, _build_handler
from tools.mcp.registry import MCPBridge, MCPServerConfig


# ── Fake MCP Client ─────────────────────────────────────────────────────────

class FakeMCPClient(MCPClient):
    """In-memory MCP client that returns canned responses."""

    def __init__(self, tools_response=None):
        super().__init__()
        self._connected = False
        if tools_response is not None:
            self._tools = tools_response
        else:
            self._tools = [
            {"name": "read_file", "description": "Read a file",
             "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
            {"name": "write_file", "description": "Write a file",
             "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}},
        ]
        self._call_results: dict[str, str] = {}

    async def connect(self):
        self._connected = True

    async def disconnect(self):
        self._connected = False

    async def _send_bytes(self, raw: str):
        pass  # handled by call override

    async def call(self, method: str, params: dict | None = None):
        if method == "initialize":
            return {"protocolVersion": "2024-11-05", "serverInfo": {"name": "fake", "version": "1.0"}}
        if method == "tools/list":
            return {"tools": self._tools}
        if method == "tools/call" and params:
            name = params.get("name", "")
            args = params.get("arguments", {})
            if name in self._call_results:
                return {"content": [{"type": "text", "text": self._call_results[name]}]}
            return {"content": [{"type": "text", "text": "OK"}]}
        return {"ok": True}


# ── MCPServerConfig ─────────────────────────────────────────────────────────

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

    def test_unknown_transport(self):
        c = MCPServerConfig(name="bad", transport="grpc", command="x")
        with pytest.raises(ValueError, match="Unknown MCP transport"):
            c.create_client()

    def test_defaults(self):
        c = MCPServerConfig(name="simple", command="echo")
        assert c.args == []
        assert c.enabled is True
        assert c.transport == "stdio"


# ── MCPError ────────────────────────────────────────────────────────────────

class TestMCPError:
    def test_basic(self):
        err = MCPError("something went wrong")
        assert "something went wrong" in str(err)


# ── Discovery with FakeMCPClient ────────────────────────────────────────────

@pytest.mark.asyncio
class TestMCPDiscovery:
    async def test_discover_tools(self):
        client = FakeMCPClient()
        await client.connect()
        specs = await discover_tools(client, "mock")
        assert len(specs) == 2
        assert specs[0].name == "mcp__mock__read_file"
        assert specs[1].name == "mcp__mock__write_file"
        assert all(s.category == ToolCategory.COLLAB for s in specs)
        await client.disconnect()

    async def test_discover_tool_spec_params(self):
        client = FakeMCPClient()
        await client.connect()
        specs = await discover_tools(client, "test")
        assert specs[0].parameters["required"] == ["path"]
        await client.disconnect()

    async def test_discover_empty_tools(self):
        client = FakeMCPClient(tools_response=[])
        await client.connect()
        specs = await discover_tools(client, "empty")
        assert specs == []
        await client.disconnect()

    async def test_tool_prefixing(self):
        client = FakeMCPClient()
        await client.connect()
        specs = await discover_tools(client, "prod")
        names = [s.name for s in specs]
        assert all(n.startswith("mcp__prod__") for n in names)
        await client.disconnect()


# ── Tool handler ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestMCPHandler:
    async def test_handler_executes_tool(self):
        client = FakeMCPClient()
        await client.connect()
        handler = _build_handler(client, "read_file")
        result = await handler(path="/etc/hosts")
        assert "OK" in result
        await client.disconnect()

    async def test_handler_error_string(self):
        """Handler returns [MCP error] string when client fails."""
        client = FakeMCPClient()
        # Override call to raise MCPError
        async def _failing_call(method, params=None):
            raise MCPError("simulated failure")
        client.call = _failing_call
        await client.connect()
        handler = _build_handler(client, "bad_tool")
        result = await handler()
        assert "[MCP error]" in result
        await client.disconnect()


# ── MCPBridge lifecycle ────────────────────────────────────────────────────

class TestMCPBridgeLifecycle:
    def test_empty_bridge(self):
        reg = ToolRegistry()
        bridge = MCPBridge(reg)
        assert bridge.attached_servers() == []

    def test_disabled_server_skipped(self):
        reg = ToolRegistry()
        bridge = MCPBridge(reg)
        result = asyncio.run(bridge.attach(
            MCPServerConfig(name="off", enabled=False)
        ))
        assert result == []

    def test_attach_from_config_dict(self):
        reg = ToolRegistry()
        bridge = MCPBridge(reg)
        result = asyncio.run(bridge.attach_from_config({
            "name": "disabled-server",
            "transport": "stdio",
            "command": "echo",
            "enabled": False,
        }))
        assert result == []

    def test_detach_all_idempotent(self):
        reg = ToolRegistry()
        bridge = MCPBridge(reg)
        assert bridge.attached_servers() == []
        # detach on empty bridge — should not crash
        asyncio.run(bridge.detach_all())
        assert bridge.attached_servers() == []


# ── E2E: stdio subprocess ───────────────────────────────────────────────────

_MOCK_SERVER_SCRIPT = '''
import json, sys
def serve():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        req = json.loads(line.strip())
        mid = req.get("id")
        method = req.get("method","")
        resp = None
        if method == "initialize":
            resp = {"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05","serverInfo":{"name":"mock","version":"1.0"},"capabilities":{}}}
        elif method == "tools/list":
            resp = {"jsonrpc":"2.0","id":mid,"result":{"tools":[{"name":"ping","description":"Ping","inputSchema":{"type":"object","properties":{}}}]}}
        elif method == "tools/call":
            resp = {"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":"pong"}]}}
        elif mid is not None:
            resp = {"jsonrpc":"2.0","id":mid,"result":{"ok":True}}
        if resp:
            sys.stdout.write(json.dumps(resp)+"\\n")
            sys.stdout.flush()
serve()
'''


@pytest.mark.asyncio
class TestMCPStdioE2E:
    async def test_end_to_end(self, tmp_path: Path):
        """Full E2E: spawn mock server, connect, list tools, call tool, disconnect."""
        script = tmp_path / "mock.py"
        script.write_text(_MOCK_SERVER_SCRIPT)

        client = MCPStdioClient(sys.executable, [str(script)])
        await client.connect()

        # tools/list
        result = await client.call("tools/list")
        assert len(result.get("tools", [])) == 1
        assert result["tools"][0]["name"] == "ping"

        # tools/call
        result = await client.call("tools/call", {"name": "ping", "arguments": {}})
        content = result.get("content", [])
        assert content[0]["text"] == "pong"

        # disconnect
        await client.disconnect()
        assert client._proc is None or client._proc.returncode is not None
