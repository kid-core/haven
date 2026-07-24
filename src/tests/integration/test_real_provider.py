"""
Integration tests — real LLM API calls.

These tests are marked ``@pytest.mark.integration`` and skipped in CI.
Run manually with::

    cd dev && python -m pytest kid/tests/integration/ -m integration -v
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


def _has_real_api_key() -> bool:
    """Check if at least one real API key is available."""
    return bool(
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("HAVEN_DISCORD_TOKEN")
        or os.getenv("ARK_API_KEY")
    )


# ======================================================================
# Infrastructure check
# ======================================================================

class TestInfrastructure:
    """Integration test scaffolding — verify the test infra works."""

    def test_marker_working(self):
        """This test should only run when -m integration is passed."""
        pass

    def test_skip_no_api_key(self):
        """If no API key, integration tests are skipped with a clear message."""
        if not _has_real_api_key():
            pytest.skip("No real API key available — set DEEPSEEK_API_KEY or ARK_API_KEY")


# ======================================================================
# Router integration — real LLM
# ======================================================================

@pytest.mark.skipif(not _has_real_api_key(), reason="Requires DEEPSEEK_API_KEY or ARK_API_KEY")
class TestRealRouter:
    """Router using a real LLM provider — minimal token usage."""

    @pytest.fixture
    def real_router(self):
        """Router with real HttpProvider (DeepSeek or Ark)."""
        import tools  # noqa: F401
        from core.http_provider import HttpProvider
        from core.router import Router
        from core.tool_decorator import get_default_registry

        registry = get_default_registry()
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("ARK_API_KEY")
        base_url = (
            "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"
            if os.getenv("ARK_API_KEY")
            else "https://api.deepseek.com/v1/chat/completions"
        )
        model = (
            os.getenv("HAVEN_TERTIARY_MODEL", "seed-2-0-lite")
            if os.getenv("ARK_API_KEY")
            else os.getenv("HAVEN_PRIMARY_MODEL", "deepseek-v4-flash")
        )

        provider = HttpProvider(
            name="Integration",
            model=model,
            base_url=base_url,
            api_key=api_key or "",
            default_temperature=0.1,
        )
        router = Router(registry, providers=[(provider, None)])
        yield router

    async def test_simple_text_response(self, real_router):
        """Real LLM should return text for a trivial question."""
        result = await real_router.process("Say 'hello' and nothing else")
        assert "hello" in result.lower()

    async def test_simple_tool_call(self, real_router):
        """Real LLM should call read_file when asked to read a file."""
        import tempfile
        from pathlib import Path

        # Create a temp file to read
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("integration test content 42")
            tmp = Path(f.name)

        result = await real_router.process(f"Read this file and tell me what's in it: {tmp}")
        assert "42" in result or "integration" in result.lower()
        assert "error" not in result.lower()

        tmp.unlink(missing_ok=True)

    async def test_fallback_works_end_to_end(self):
        """Two providers, primary fails → secondary succeeds."""
        import tools  # noqa: F401
        from core.http_provider import HttpProvider
        from core.router import Router
        from core.tool_decorator import get_default_registry

        registry = get_default_registry()

        # Primary — will fail (bad key)
        primary = HttpProvider(
            name="Broken",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com/v1/chat/completions",
            api_key="sk-bad-key-that-will-fail-12345",
        )

        # Secondary — real provider
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("ARK_API_KEY")
        base_url = (
            "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"
            if os.getenv("ARK_API_KEY")
            else "https://api.deepseek.com/v1/chat/completions"
        )
        model = (
            os.getenv("HAVEN_TERTIARY_MODEL", "seed-2-0-lite")
            if os.getenv("ARK_API_KEY")
            else os.getenv("HAVEN_PRIMARY_MODEL", "deepseek-v4-flash")
        )

        secondary = HttpProvider(
            name="Integration",
            model=model,
            base_url=base_url,
            api_key=api_key or "",
        )

        router = Router(registry, providers=[(primary, None), (secondary, None)])
        result = await router.process("Say 'fallback-success'")
        assert "fallback" in result.lower() or "success" in result.lower()


# ======================================================================
# Expanded integration tests
# ======================================================================

class TestRealProviderEdgeCases:
    """Real provider — edge cases and failure modes."""

    @pytest.mark.skipif(not _has_real_api_key(), reason="Requires real API key")
    async def test_provider_timeout_fast(self):
        """Provider with 0.001s timeout should fail fast."""
        import tools  # noqa: F401
        from core.http_provider import HttpProvider
        from core.router import Router
        from core.tool_decorator import get_default_registry

        registry = get_default_registry()
        # A tiny timeout will trigger provider failure
        fast_fail = HttpProvider(
            name="FastFail",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com/v1/chat/completions",
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            timeout=0.001,
        )

        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("ARK_API_KEY")
        base_url = (
            "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"
            if os.getenv("ARK_API_KEY")
            else "https://api.deepseek.com/v1/chat/completions"
        )
        model = (
            os.getenv("HAVEN_TERTIARY_MODEL", "seed-2-0-lite")
            if os.getenv("ARK_API_KEY")
            else os.getenv("HAVEN_PRIMARY_MODEL", "deepseek-v4-flash")
        )

        fallback = HttpProvider(
            name="Fallback", model=model, base_url=base_url,
            api_key=api_key or "", timeout=30,
        )

        router = Router(registry, providers=[(fast_fail, None), (fallback, None)])
        result = await router.process("Say 'fallback-reached' in 3 words")
        assert result is not None
        assert len(result) > 0

    @pytest.mark.skipif(not _has_real_api_key(), reason="Requires real API key")
    async def test_concurrent_real_sessions(self):
        """Two concurrent real provider sessions — both complete."""
        import tools  # noqa: F401
        from core.http_provider import HttpProvider
        from core.router import Router
        from core.tool_decorator import get_default_registry
        import asyncio

        registry = get_default_registry()
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("ARK_API_KEY")
        base_url = (
            "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"
            if os.getenv("ARK_API_KEY")
            else "https://api.deepseek.com/v1/chat/completions"
        )
        model = (
            os.getenv("HAVEN_TERTIARY_MODEL", "seed-2-0-lite")
            if os.getenv("ARK_API_KEY")
            else os.getenv("HAVEN_PRIMARY_MODEL", "deepseek-v4-flash")
        )

        p1 = HttpProvider(name="P1", model=model, base_url=base_url, api_key=api_key or "")
        p2 = HttpProvider(name="P2", model=model, base_url=base_url, api_key=api_key or "")

        r1 = Router(registry, providers=[(p1, None)])
        r2 = Router(registry, providers=[(p2, None)])

        async def session_a():
            return await r1.process("Say 'from-a'", session_id="sess_a")

        async def session_b():
            return await r2.process("Say 'from-b'", session_id="sess_b")

        ra, rb = await asyncio.gather(session_a(), session_b())
        assert "from-a" in ra.lower() or "a" in ra.lower()
        assert "from-b" in rb.lower() or "b" in rb.lower()
