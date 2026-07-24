"""Provider registry — load and manage LLM providers from TOML config."""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from core.base_provider import BaseProvider
from core.http_provider import HttpProvider

logger = logging.getLogger(__name__)

# ── provider type → factory ──────────────────────────────────
_PROVIDER_FACTORIES: dict[str, Any] = {}


def _register_factory(type_name: str):
    """Decorator: register a provider factory for a given type string."""

    def decorator(fn):
        _PROVIDER_FACTORIES[type_name] = fn
        return fn

    return decorator


@_register_factory("http")
def _build_http(key: str, cfg: dict) -> HttpProvider:
    return HttpProvider(
        name=cfg.get("name", key),
        model=str(_resolve_model(cfg)),
        base_url=str(cfg["base_url"]),
        api_key_env=str(cfg["api_key_env"]),
        default_temperature=float(cfg.get("temperature", 0.3)),
        headers_extra=cfg.get("headers"),
    )


@_register_factory("ollama")
def _build_ollama(key: str, cfg: dict) -> BaseProvider:
    from tools.ollama_provider import create_ollama_provider

    host = cfg.get("host", "localhost")
    port = cfg.get("port", 11434)
    # create_ollama_provider uses config.ollama_base_url internally,
    # but we can override via OLLAMA_BASE_URL env for custom host/port
    if host != "localhost" or port != 11434:
        os.environ.setdefault(
            "OLLAMA_BASE_URL", f"http://{host}:{port}"
        )

    provider = create_ollama_provider(
        model=_resolve_model(cfg),
        name=cfg.get("name", key),
    )
    if provider is None:
        raise RuntimeError(
            f"Ollama provider '{key}': create_ollama_provider returned None. "
            f"Check that Ollama is running at {host}:{port}"
        )
    return provider


def _resolve_model(cfg: dict) -> str:
    """Resolve model name: env var > fallback."""
    model_env = cfg.get("model_env", "")
    model_fallback = cfg.get("model_fallback", "")
    if model_env:
        return os.getenv(model_env, model_fallback)
    return model_fallback


# ── Registry ─────────────────────────────────────────────────


class ProviderRegistry:
    """Central registry for LLM providers loaded from TOML config.

    Usage::

        registry = ProviderRegistry.from_toml("config/providers.toml")

        # pass to Router
        router = Router(registry=registry, providers=list(registry), ...)

        # register category-specific providers
        registry.setup_category_router(cat_router)

        # lookup
        primary = registry.get("deepseek")
        vision  = registry.by_category("vision")

        # shutdown
        await registry.close_all()
    """

    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}
        self._meta: dict[str, dict] = {}  # key → raw config
        self._order: list[str] = []  # sorted by priority

    # ── factory ──────────────────────────────────────────

    @classmethod
    def from_toml(cls, path: str | Path) -> ProviderRegistry:
        """Create a ProviderRegistry from a TOML config file."""
        raw = _read_toml(path)
        providers_section = raw.get("providers", {})
        if not providers_section:
            raise RuntimeError(f"No [providers.*] sections found in {path}")

        registry = cls()
        entries: list[tuple[int, str, dict]] = []

        for key, cfg in providers_section.items():
            if not isinstance(cfg, dict):
                continue

            api_key_env = cfg.get("api_key_env", "")
            optional = cfg.get("optional", False)

            # optional + missing API key (only for http type) → skip
            if api_key_env and optional and not os.getenv(api_key_env):
                logger.debug(
                    "Skipping optional provider %r (no %s)", key, api_key_env
                )
                continue

            model_name = _resolve_model(cfg)
            if not model_name and not optional:
                raise ValueError(
                    f"provider '{key}': no model name "
                    f"(env {cfg.get('model_env')} not set, no fallback)"
                )
            if not model_name:
                logger.debug("Skipping optional provider %r (no model)", key)
                continue

            # build provider via type factory
            ptype = cfg.get("type", "http")
            factory = _PROVIDER_FACTORIES.get(ptype)
            if factory is None:
                raise ValueError(
                    f"provider '{key}': unknown type {ptype!r}. "
                    f"Available: {list(_PROVIDER_FACTORIES)}"
                )

            try:
                provider = factory(key, cfg)
            except Exception as exc:
                if optional:
                    logger.warning(
                        "Skipping optional provider %r: %s", key, exc
                    )
                    continue
                raise

            priority = cfg.get("priority", 99)
            entries.append((priority, key, cfg))
            registry._providers[key] = provider
            registry._meta[key] = cfg

        entries.sort(key=lambda x: x[0])
        registry._order = [key for _, key, _ in entries]
        return registry

    # ── lookup ───────────────────────────────────────────

    def get(self, name: str) -> BaseProvider | None:
        """Look up a provider by registry key."""
        return self._providers.get(name)

    def primary(self) -> BaseProvider:
        """Return the highest-priority non-category provider."""
        for key in self._order:
            if not self._meta.get(key, {}).get("category"):
                return self._providers[key]
        raise RuntimeError("No non-category providers loaded")

    def fallback(
        self, skip: BaseProvider | None = None
    ) -> BaseProvider | None:
        """Return the next available non-category provider after *skip*."""
        start = False
        for key in self._order:
            # skip category-only providers in general fallback
            if self._meta.get(key, {}).get("category"):
                continue
            provider = self._providers[key]
            if skip is not None and provider is skip:
                start = True
                continue
            if start or skip is None:
                return provider
        return None

    def by_category(self, category: str) -> list[BaseProvider]:
        """Return all providers tagged with *category*."""
        return [
            self._providers[key]
            for key in self._order
            if self._meta.get(key, {}).get("category") == category
        ]

    def to_list(
        self,
    ) -> list[tuple[BaseProvider, str | None]]:
        """Export non-category providers for Router's main fallback list."""
        return [
            (self._providers[key], None)
            for key in self._order
            if not self._meta.get(key, {}).get("category")
        ]

    def setup_category_router(self, cat_router) -> None:
        """Register category-tagged providers with a CategoryRouter."""
        from core.category_router import CategoryRouter as CR

        if not isinstance(cat_router, CR):
            raise TypeError(
                f"Expected CategoryRouter, got {type(cat_router).__name__}"
            )

        for key in self._order:
            category = self._meta.get(key, {}).get("category")
            if category:
                provider = self._providers[key]
                cat_router.set_provider(category, provider)
                logger.info(
                    "Provider %r registered for category %r via CategoryRouter",
                    key,
                    category,
                )

    def __iter__(self):
        return iter(self.to_list())

    def __len__(self) -> int:
        return len([k for k in self._order if not self._meta.get(k, {}).get("category")])

    def __contains__(self, name: str) -> bool:
        return name in self._providers

    @property
    def all_keys(self) -> list[str]:
        """Return all provider keys in priority order (including category-only)."""
        return list(self._order)

    # ── lifecycle ────────────────────────────────────────

    async def close_all(self) -> None:
        """Close all managed providers."""
        for key, provider in self._providers.items():
            try:
                await provider.close()
            except Exception:
                logger.exception("Error closing provider %r", key)


# ── helpers ──────────────────────────────────────────────────


def _read_toml(path: str | Path) -> dict:
    """Read TOML file, with helpful error messages."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Provider registry not found: {path}")

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(
            f"Invalid TOML in {path}: {e}\n"
            f"Hint: check for missing quotes, brackets, or invalid syntax."
        ) from e
