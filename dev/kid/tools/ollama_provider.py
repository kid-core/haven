"""Ollama integration — embedding + chat providers for local models.

Provides:
- OllamaEmbedding:  lightweight embedding via ollama /api/embeddings
- OllamaChat:       OpenAI-compatible chat via ollama /v1 (supports minicpm-v, etc.)

Both use httpx with graceful fallback when ollama is unavailable.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

class OllamaEmbedding:
    """Lightweight ollama embedding client.

    Usage::

        emb = OllamaEmbedding(model="nomic-embed-text:latest")
        if await emb.available():
            vec = await emb.embed("some text")
    """

    def __init__(self, model: str = "nomic-embed-text:latest") -> None:
        self.model = model
        self._available: bool | None = None

    async def available(self) -> bool:
        """Check if ollama is reachable. Results cached after first call."""
        if self._available is not None:
            return self._available
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{OLLAMA_BASE}/api/tags")
                self._available = resp.status_code == 200
        except Exception:
            self._available = False
        if self._available:
            logger.info("Ollama embedding: %s ready", self.model)
        return self._available

    async def embed(self, text: str) -> list[float] | None:
        """Get embedding vector from ollama."""
        if not await self.available():
            return None
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{OLLAMA_BASE}/api/embeddings",
                    json={"model": self.model, "prompt": text[:1000]},
                )
                if resp.status_code != 200:
                    return None
                return resp.json().get("embedding")
        except Exception as exc:
            logger.debug("Ollama embed failed: %s", exc)
            self._available = False
            return None


# ---------------------------------------------------------------------------
# Chat (OpenAI-compatible via ollama /v1)
# ---------------------------------------------------------------------------

def create_ollama_provider(
    model: str = "minicpm-v:latest",
    name: str = "Ollama-minicpm",
) -> "HttpProvider | None":
    """Create an HttpProvider for ollama's OpenAI-compatible endpoint.

    Returns None if ollama isn't configured or available.
    Intended for use in main.py alongside DeepSeek/OpenRouter providers.

    Usage in main.py::

        ollama_minicpm = create_ollama_provider("minicpm-v:latest")
        if ollama_minicpm:
            providers.append((ollama_minicpm, None))
            cat_router.set_provider("vision", ollama_minicpm)
    """
    try:
        from core.http_provider import HttpProvider
    except ImportError:
        return None

    api_key = os.getenv("OLLAMA_API_KEY", "ollama")  # ollama doesn't require real key
    os.environ.setdefault("OLLAMA_API_KEY", api_key)

    try:
        return HttpProvider(
            name=name,
            model=model,
            base_url=f"{OLLAMA_BASE}/v1/chat/completions",
            api_key_env="OLLAMA_API_KEY",
            timeout=120.0,
            default_temperature=0.7,
        )
    except Exception as exc:
        logger.warning("Ollama chat provider not created: %s", exc)
        return None
