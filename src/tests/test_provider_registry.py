"""Tests for ProviderRegistry."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.provider_registry import (
    ProviderRegistry,
    _read_toml,
    _resolve_model,
)


# ── helpers ──────────────────────────────────────────────────


def _write_toml(content: str) -> str:
    """Write TOML content to a temp file, return path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".toml", delete=False
    )
    tmp.write(content)
    tmp.close()
    return tmp.name


# ── _resolve_model ───────────────────────────────────────────


class TestResolveModel:
    def test_uses_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("TEST_MODEL", "gpt-5")
        cfg = {"model_env": "TEST_MODEL", "model_fallback": "fallback"}
        assert _resolve_model(cfg) == "gpt-5"

    def test_falls_back_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("NO_SUCH_VAR", raising=False)
        cfg = {"model_env": "NO_SUCH_VAR", "model_fallback": "fallback-model"}
        assert _resolve_model(cfg) == "fallback-model"

    def test_no_env_var_uses_fallback_directly(self):
        cfg = {"model_fallback": "claude-sonnet"}
        assert _resolve_model(cfg) == "claude-sonnet"


# ── _read_toml ───────────────────────────────────────────────


class TestReadToml:
    def test_valid_toml(self):
        path = _write_toml("[a]\nkey = 1\n")
        try:
            data = _read_toml(path)
            assert data == {"a": {"key": 1}}
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            _read_toml("/nonexistent/providers.toml")

    def test_invalid_toml_syntax(self):
        path = _write_toml("[a\nkey = 1\n")
        try:
            with pytest.raises(RuntimeError, match="Invalid TOML"):
                _read_toml(path)
        finally:
            os.unlink(path)


# ── from_toml — basic loading ────────────────────────────────


class TestFromTomlBasic:
    def test_load_two_http_providers(self, monkeypatch):
        """Load two non-optional HTTP providers with API keys set."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        monkeypatch.setenv("HAVEN_PRIMARY_MODEL", "deepseek-v4")
        monkeypatch.setenv("HAVEN_FALLBACK_MODEL", "gemma-4")

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false

[providers.openrouter]
name = "OpenRouter"
model_env = "HAVEN_FALLBACK_MODEL"
model_fallback = "google/gemma-4-26b-a4b-it"
base_url = "https://openrouter.ai/api/v1/chat/completions"
api_key_env = "OPENROUTER_API_KEY"
temperature = 0.7
priority = 2
optional = false
""")
        try:
            registry = ProviderRegistry.from_toml(path)
            assert len(registry) == 2
            assert "deepseek" in registry
            assert "openrouter" in registry
            assert registry.get("deepseek").get_model() == "deepseek-v4"
            assert registry.get("openrouter").get_model() == "gemma-4"
        finally:
            os.unlink(path)

    def test_optional_provider_skipped_when_no_key(self, monkeypatch):
        """Optional provider with missing API key is silently skipped."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.delenv("ARK_API_KEY", raising=False)
        monkeypatch.setenv("HAVEN_PRIMARY_MODEL", "deepseek-v4")

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false

[providers.ark]
name = "Ark"
model_env = "HAVEN_TERTIARY_MODEL"
model_fallback = "seed-2-0-lite"
base_url = "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"
api_key_env = "ARK_API_KEY"
temperature = 0.3
priority = 4
optional = true
""")
        try:
            registry = ProviderRegistry.from_toml(path)
            assert len(registry) == 1
            assert "deepseek" in registry
            assert "ark" not in registry._providers
        finally:
            os.unlink(path)

    def test_optional_provider_present_when_key_exists(self, monkeypatch):
        """Optional provider with API key set is loaded."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("ARK_API_KEY", "sk-ark")
        monkeypatch.setenv("HAVEN_PRIMARY_MODEL", "deepseek-v4")
        monkeypatch.setenv("HAVEN_TERTIARY_MODEL", "seed-lite")

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false

[providers.ark]
name = "Ark"
model_env = "HAVEN_TERTIARY_MODEL"
model_fallback = "seed-2-0-lite"
base_url = "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"
api_key_env = "ARK_API_KEY"
temperature = 0.3
priority = 4
optional = true
""")
        try:
            registry = ProviderRegistry.from_toml(path)
            assert len(registry) == 2
            assert "ark" in registry
        finally:
            os.unlink(path)

    def test_missing_api_key_env_for_non_optional_raises(self, monkeypatch):
        """Non-optional HTTP provider without api_key_env fails at HttpProvider level."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("HAVEN_PRIMARY_MODEL", "deepseek-v4")

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false
""")
        try:
            with pytest.raises(Exception):  # ProviderError or RuntimeError
                ProviderRegistry.from_toml(path)
        finally:
            os.unlink(path)

    def test_priority_sorting(self, monkeypatch):
        """Providers are ordered by priority ascending."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        monkeypatch.setenv("HAVEN_FALLBACK_MODEL", "gemma")
        monkeypatch.setenv("HAVEN_PRIMARY_MODEL", "deepseek-v4")

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 99
optional = false

[providers.openrouter]
name = "OpenRouter"
model_env = "HAVEN_FALLBACK_MODEL"
model_fallback = "gemma"
base_url = "https://openrouter.ai/api/v1/chat/completions"
api_key_env = "OPENROUTER_API_KEY"
temperature = 0.7
priority = 1
optional = false
""")
        try:
            registry = ProviderRegistry.from_toml(path)
            provider_list = registry.to_list()
            # openrouter has priority=1, deepseek has priority=99
            # → openrouter should be first
            assert provider_list[0][0].get_model() == "gemma"
            assert provider_list[1][0].get_model() == "deepseek-v4"
        finally:
            os.unlink(path)

    def test_empty_registry_raises(self):
        path = _write_toml("# empty\n")
        try:
            with pytest.raises(
                RuntimeError, match="No .*providers.* sections"
            ):
                ProviderRegistry.from_toml(path)
        finally:
            os.unlink(path)

    def test_invalid_toml_raises_helpful_error(self):
        path = _write_toml("[bad\n")
        try:
            with pytest.raises(RuntimeError, match="Invalid TOML"):
                ProviderRegistry.from_toml(path)
        finally:
            os.unlink(path)

    def test_model_fallback_when_env_not_set(self, monkeypatch):
        """Model name falls back to model_fallback when env var is missing."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.delenv("HAVEN_PRIMARY_MODEL", raising=False)

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false
""")
        try:
            registry = ProviderRegistry.from_toml(path)
            assert registry.get("deepseek").get_model() == "deepseek-v4-flash"
        finally:
            os.unlink(path)


# ── category support ─────────────────────────────────────────


class TestCategorySupport:
    def test_by_category_filters_correctly(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("HAVEN_PRIMARY_MODEL", "deepseek-v4")

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false

[providers.ollama_vision]
type = "ollama"
name = "Ollama Vision"
model_fallback = "minicpm-v:latest"
category = "vision"
priority = 5
optional = true
""")
        try:
            with patch(
                "tools.ollama_provider.create_ollama_provider"
            ) as mock_create:
                mock_provider = MagicMock()
                mock_provider.get_model.return_value = "minicpm-v:latest"
                mock_create.return_value = mock_provider

                registry = ProviderRegistry.from_toml(path)

                vision_providers = registry.by_category("vision")
                assert len(vision_providers) == 1

                # non-category provider not matched
                assert registry.by_category("general") == []
        finally:
            os.unlink(path)

    def test_to_list_excludes_category_providers(self, monkeypatch):
        """to_list() only returns providers without a category."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("HAVEN_PRIMARY_MODEL", "deepseek-v4")

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false

[providers.ollama_vision]
type = "ollama"
name = "Ollama Vision"
model_fallback = "minicpm-v:latest"
category = "vision"
priority = 5
optional = true
""")
        try:
            with patch(
                "tools.ollama_provider.create_ollama_provider"
            ) as mock_create:
                mock_provider = MagicMock()
                mock_provider.get_model.return_value = "minicpm-v:latest"
                mock_create.return_value = mock_provider

                registry = ProviderRegistry.from_toml(path)
                provider_list = registry.to_list()
                assert len(provider_list) == 1
                assert registry.get("deepseek") is not None
                assert registry.get("ollama_vision") is not None
                # len excludes category providers
                assert len(registry) == 1
                # all_keys includes everyone
                assert registry.all_keys == ["deepseek", "ollama_vision"]
        finally:
            os.unlink(path)

    def test_primary_skips_category_providers(self, monkeypatch):
        """primary() returns the first non-category provider."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("HAVEN_PRIMARY_MODEL", "deepseek-v4")

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false
""")
        try:
            registry = ProviderRegistry.from_toml(path)
            p = registry.primary()
            assert p.get_model() == "deepseek-v4"
        finally:
            os.unlink(path)

    def test_setup_category_router_registers_providers(self, monkeypatch):
        """setup_category_router() registers category providers."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("HAVEN_PRIMARY_MODEL", "deepseek-v4")

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false

[providers.ollama_vision]
type = "ollama"
name = "Ollama Vision"
model_fallback = "minicpm-v:latest"
category = "vision"
priority = 5
optional = true
""")
        try:
            with patch(
                "tools.ollama_provider.create_ollama_provider"
            ) as mock_create:
                mock_provider = MagicMock()
                mock_provider.get_model.return_value = "minicpm-v:latest"
                mock_create.return_value = mock_provider

                registry = ProviderRegistry.from_toml(path)

                # Create a mock CategoryRouter and patch isinstance check
                from core.category_router import CategoryRouter
                mock_cat_router = MagicMock(spec=CategoryRouter)

                registry.setup_category_router(mock_cat_router)

                mock_cat_router.set_provider.assert_called_once_with(
                    "vision", mock_provider
                )
        finally:
            os.unlink(path)


# ── factory dispatch ─────────────────────────────────────────


class TestFactoryDispatch:
    def test_unknown_type_raises(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        monkeypatch.setenv("HAVEN_PRIMARY_MODEL", "deepseek-v4")

        path = _write_toml("""\
[providers.deepseek]
name = "DeepSeek"
model_env = "HAVEN_PRIMARY_MODEL"
model_fallback = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/v1/chat/completions"
api_key_env = "DEEPSEEK_API_KEY"
temperature = 0.3
priority = 1
optional = false

[providers.unknown_type]
type = "custom_llm"
name = "Custom"
model_fallback = "custom-model"
priority = 6
optional = true
""")
        try:
            with pytest.raises(ValueError, match="unknown type"):
                ProviderRegistry.from_toml(path)
        finally:
            os.unlink(path)


# ── integration-style: real config file ──────────────────────


class TestRealConfig:
    def test_real_providers_toml_exists_and_parsable(self):
        """Smoke test: the real config/providers.toml is valid TOML."""
        import tomllib

        config_path = (
            Path(__file__).resolve().parents[2]
            / "config"
            / "providers.toml"
        )
        if not config_path.exists():
            pytest.skip(f"{config_path} not found")

        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        assert "providers" in data
        assert "deepseek" in data["providers"]
        assert data["providers"]["deepseek"]["name"] == "DeepSeek"
