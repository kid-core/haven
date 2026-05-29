"""
Smoke tests for the Haven core modules — no API keys required.
"""

from __future__ import annotations

import pytest


class TestToolSpec:
    """Verify the ToolSpec dataclass."""

    def test_tool_spec_import_and_instantiation(self) -> None:
        from core.tool_spec import ToolSpec

        async def fake(**kwargs):
            return "ok"

        spec = ToolSpec(name="test", description="A test tool",
                        parameters={"type": "object", "properties": {}},
                        handler=fake)
        assert spec.name == "test"
        assert spec.description == "A test tool"


class TestToolDecorator:
    """Verify the @tool decorator and default registry."""

    def test_default_registry(self) -> None:
        from core.tool_decorator import get_default_registry, tool

        assert get_default_registry is not None
        assert tool is not None
        assert get_default_registry() is get_default_registry()


class TestToolRegistry:
    """Verify the tool registry boots and formats correctly."""

    def test_tools_register(self) -> None:
        import tools  # noqa: F401
        from core.tool_decorator import get_default_registry

        registry = get_default_registry()
        assert len(registry) > 0

    def test_get_openai_tools_format(self) -> None:
        import tools  # noqa: F401
        from core.tool_decorator import get_default_registry

        tools_list = get_default_registry().get_openai_tools()
        assert isinstance(tools_list, list)
        if tools_list:
            assert "type" in tools_list[0]
            assert "function" in tools_list[0]
            assert "name" in tools_list[0]["function"]

    @pytest.mark.asyncio
    async def test_registry_execute_unknown(self) -> None:
        import json
        import tools  # noqa: F401
        from core.tool_decorator import get_default_registry

        result = await get_default_registry().execute(
            tool_call_id="test", name="nonexistent", arguments={}
        )
        assert result["role"] == "tool"
        assert "error" in json.loads(result["content"])


class TestProviderImports:
    """Verify the config-driven HttpProvider module."""

    def test_http_provider_imports_and_interface(self) -> None:
        from core.http_provider import HttpProvider

        assert hasattr(HttpProvider, "chat_completion")
        assert hasattr(HttpProvider, "close")
        assert hasattr(HttpProvider, "get_model")

    def test_base_provider_imports(self) -> None:
        from core.base_provider import BaseProvider

        assert BaseProvider is not None


class TestPydanticModels:
    """Verify Pydantic v2 models."""

    def test_provider_response(self) -> None:
        from core.models import ProviderResponse

        resp = ProviderResponse()
        assert resp.content is None
        assert resp.tool_calls is None

        resp2 = ProviderResponse(content="hi", tool_calls=[{"id": "1"}])
        dump = resp2.model_dump()
        assert dump["content"] == "hi"
        assert dump["tool_calls"] == [{"id": "1"}]

    def test_tool_result(self) -> None:
        from core.models import ToolResult

        tr = ToolResult(tool_call_id="abc", content="done")
        dump = tr.model_dump()
        assert dump["role"] == "tool"
        assert dump["tool_call_id"] == "abc"
        assert dump["content"] == "done"


class TestExceptions:
    """Verify domain exceptions hierarchy."""

    def test_core_exceptions(self) -> None:
        from core.exceptions import HavenError, ProviderError, RouterError, RegistryError

        assert issubclass(ProviderError, HavenError)
        assert issubclass(RouterError, HavenError)
        assert issubclass(RegistryError, HavenError)

    def test_tool_and_transport_exceptions(self) -> None:
        from tools import ToolError
        from transport import TransportError

        assert issubclass(ToolError, Exception)
        assert issubclass(TransportError, Exception)


class TestRouter:
    """Verify the router module imports correctly."""

    def test_router_imports(self) -> None:
        from core.router import Router

        assert Router is not None


class TestSessionStore:
    """Verify the JSON-backed session store."""

    def test_session_store_save_load_trim(self, tmp_path) -> None:
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path, max_messages=3)

        assert store.load("nonexistent") == []

        messages = [{"role": "user", "content": str(i)} for i in range(10)]
        store.save("trim-test", messages)

        loaded = store.load("trim-test")
        assert len(loaded) == 3
        assert loaded[0]["content"] == "7"

    def test_session_store_roundtrip(self, tmp_path) -> None:
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path)
        messages = [{"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"}]
        store.save("test-session", messages)
        assert store.load("test-session") == messages
