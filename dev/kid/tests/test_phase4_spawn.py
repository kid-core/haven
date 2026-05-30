"""Phase 4 tests — SpawnManager, spawn_child tool."""

import asyncio

import pytest
from core.tool_registry import ToolRegistry
from core.tool_spec import ToolSpec
from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.router import Router
from tools.spawn_child import SpawnManager, MAX_NESTING


async def _echo(**kw):
    return "ok"


class EchoProvider:
    """Provider that echoes the last user message."""
    async def chat_completion(self, messages, tools=None, temperature=None, max_tokens=None):
        from core.models import ProviderResponse
        last = [m["content"] for m in messages if m["role"] == "user"]
        return ProviderResponse(content=last[-1] if last else "echo")
    def get_model(self, o=None):
        return "echo"
    async def close(self):
        pass


def _make_registry():
    reg = ToolRegistry()
    reg.add(ToolSpec("cmd", "", {}, _echo, ToolCategory.SYSTEM,
                     ToolPolicy(require_confirm=False)))
    return reg


class TestSpawnManager:
    @pytest.mark.asyncio
    async def test_basic_spawn(self):
        reg = _make_registry()
        import tools
        router = Router(reg, [(EchoProvider(), None)])
        mgr = SpawnManager(router=router)
        result = await mgr.spawn("Hello world", timeout=5)
        assert "Hello world" in result

    @pytest.mark.asyncio
    async def test_nesting_limit(self):
        reg = _make_registry()
        import tools
        router = Router(reg, [(EchoProvider(), None)])
        mgr = SpawnManager(router=router, nesting_level=MAX_NESTING)
        result = await mgr.spawn("test", timeout=5)
        assert "Max nesting depth" in result

    @pytest.mark.asyncio
    async def test_timeout(self):
        reg = _make_registry()

        class SlowProvider:
            async def chat_completion(self, messages, tools=None, **kw):
                await asyncio.sleep(3)
                from core.models import ProviderResponse
                return ProviderResponse(content="too slow")
            def get_model(self, o=None):
                return "slow"
            async def close(self):
                pass

        import tools
        router = Router(reg, [(SlowProvider(), None)])
        mgr = SpawnManager(router=router)
        result = await mgr.spawn("test", timeout=0.5)
        assert "timed out" in result.lower()
