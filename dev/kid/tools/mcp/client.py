"""MCP (Model Context Protocol) client — stdio and SSE transports."""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# JSON-RPC 2.0
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"


# ---------------------------------------------------------------------------
# MCP error
# ---------------------------------------------------------------------------

class MCPError(Exception):
    """MCP protocol error."""


# ---------------------------------------------------------------------------
# Abstract client
# ---------------------------------------------------------------------------

class MCPClient(ABC):
    """Abstract MCP client — JSON-RPC over a transport."""

    def __init__(self) -> None:
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict]] = {}

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    # ------------------------------------------------------------------
    # JSON-RPC request
    # ------------------------------------------------------------------

    async def call(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC request and wait for the response."""
        self._next_id += 1
        msg_id = self._next_id

        request = {
            "jsonrpc": JSONRPC_VERSION,
            "id": msg_id,
            "method": method,
            "params": params or {},
        }

        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future

        payload = json.dumps(request)
        await self._send_bytes(payload + "\n")

        return await future

    @abstractmethod
    async def _send_bytes(self, raw: str) -> None:
        """Send a raw string to the transport."""
        ...

    async def _notify(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no id, no response)."""
        msg = {"jsonrpc": JSONRPC_VERSION, "method": method, "params": params}
        await self._send_bytes(json.dumps(msg) + "\n")

    # ------------------------------------------------------------------
    # Response routing (called by subclasses when a JSON-RPC message arrives)
    # ------------------------------------------------------------------

    def _on_message(self, msg: dict) -> None:
        """Route an incoming JSON-RPC message to the right pending future."""
        if "id" in msg and msg.get("id") is not None:
            msg_id = msg["id"]
            future = self._pending.pop(msg_id, None)
            if future is None or future.done():
                return
            if "error" in msg:
                future.set_exception(
                    MCPError(msg["error"].get("message", "Unknown MCP error"))
                )
            else:
                future.set_result(msg.get("result", {}))
        elif "method" in msg:
            logger.debug("MCP notification: %s", msg["method"])

    def _fail_pending(self, reason: str) -> None:
        """Reject all outstanding futures (used on disconnect / transport failure)."""
        err = MCPError(reason)
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(err)
        self._pending.clear()


# ---------------------------------------------------------------------------
# Stdio transport
# ---------------------------------------------------------------------------

class MCPStdioClient(MCPClient):
    """MCP client over stdio (subprocess stdin/stdout)."""

    def __init__(self, command: str, args: list[str] | None = None) -> None:
        super().__init__()
        self.command = command
        self.args = args or []
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        # MCP handshake
        init = await self.call("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "Haven", "version": "0.1.0"},
        })
        logger.info("MCP stdio initialized: %s", init.get("serverInfo", {}))
        await self._notify("notifications/initialized", {})

    async def disconnect(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except TimeoutError:
                self._proc.kill()
                await self._proc.wait()
            except ProcessLookupError:
                pass
            self._proc = None
        self._fail_pending("MCP stdio disconnected")

    async def _send_bytes(self, raw: str) -> None:
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(raw.encode("utf-8"))
            await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            try:
                line_bytes = await self._proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    self._on_message(json.loads(line))
                except json.JSONDecodeError:
                    pass
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("MCP stdio read error")
                break
        self._fail_pending("MCP stdio stream closed")


# ---------------------------------------------------------------------------
# SSE transport (simplified — single-endpoint mode)
# ---------------------------------------------------------------------------

class MCPSseClient(MCPClient):
    """MCP client over SSE.

    POST JSON-RPC requests to *url*, receive responses as SSE stream.
    """

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url.rstrip("/")
        self._http: Any = None
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        import httpx
        self._http = httpx.AsyncClient(timeout=30.0)
        self._reader_task = asyncio.create_task(self._sse_loop())

        init = await self.call("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "Haven", "version": "0.1.0"},
        })
        logger.info("MCP SSE initialized: %s", init.get("serverInfo", {}))
        await self._notify("notifications/initialized", {})

    async def disconnect(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._http:
            await self._http.aclose()
            self._http = None
        self._fail_pending("MCP SSE disconnected")

    async def _send_bytes(self, raw: str) -> None:
        if not self._http:
            raise MCPError("SSE client not connected")
        # POST JSON-RPC request — response comes back on SSE stream
        await self._http.post(
            self.url,
            content=raw.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    async def _sse_loop(self) -> None:
        if not self._http:
            return
        try:
            async with self._http.stream("GET", self.url) as resp:
                line_buffer = ""
                async for chunk in resp.aiter_text():
                    line_buffer += chunk
                    while "\n" in line_buffer:
                        line, line_buffer = line_buffer.split("\n", 1)
                        if line.startswith("data: "):
                            data = line[6:]
                            try:
                                msg = json.loads(data)
                                self._on_message(msg)
                            except json.JSONDecodeError:
                                pass
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("MCP SSE stream error")
        self._fail_pending("MCP SSE stream closed")
