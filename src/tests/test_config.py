"""
Tests for core/config.py — typed configuration singleton.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestConfigDefaults:
    """Default values when no env vars are set."""

    def test_import_config(self):
        from core.config import config, HavenConfig
        assert isinstance(config, HavenConfig)

    def test_primary_model_default(self):
        from core.config import config
        assert config.primary_model == "deepseek-v4-flash"

    def test_fallback_model_default(self):
        from core.config import config
        assert config.fallback_model == "google/gemma-4-26b-a4b-it"

    def test_tertiary_model_default(self):
        from core.config import config
        assert config.tertiary_model == "seed-2-0-lite"

    def test_embed_model_default(self):
        from core.config import config
        assert config.embed_model == "nomic-embed-text:latest"

    def test_no_terminal_default(self):
        from core.config import config
        assert config.no_terminal is False

    def test_use_vector_default(self):
        from core.config import config
        assert config.use_vector is False

    def test_allowed_prefix_default(self):
        from core.config import config
        assert config.allowed_prefix == "/mnt/z/haven"

    def test_ollama_base_url_default(self):
        from core.config import config
        assert config.ollama_base_url == "http://localhost:11434"

    def test_heartbeat_defaults(self):
        from core.config import config
        assert config.heartbeat_interval == 30.0
        assert config.heartbeat_threshold == 3
        assert config.heartbeat_discord_channel == 0
        assert config.heartbeat_discord_user == 0
        assert config.heartbeat_telegram_chat == 0


class TestConfigEnvOverrides:
    """Config reads env vars at import time via default_factory."""

    def test_primary_model_from_env(self):
        with patch.dict(os.environ, {"HAVEN_PRIMARY_MODEL": "custom-model"}, clear=False):
            # Re-import to pick up env (fresh module)
            import importlib
            from core import config as cfg_module
            importlib.reload(cfg_module)
            from core.config import config
            assert config.primary_model == "custom-model"

    def test_no_terminal_flag(self):
        with patch.dict(os.environ, {"HAVEN_NO_TERMINAL": "true"}, clear=False):
            import importlib
            from core import config as cfg_module
            importlib.reload(cfg_module)
            from core.config import config
            assert config.no_terminal is True

    def test_use_vector_flag(self):
        with patch.dict(os.environ, {"HAVEN_USE_VECTOR": "1"}, clear=False):
            import importlib
            from core import config as cfg_module
            importlib.reload(cfg_module)
            from core.config import config
            assert config.use_vector is True

    def test_allowed_prefix_override(self):
        with patch.dict(os.environ, {"HAVEN_ALLOWED_PREFIX": "/custom/prefix"}, clear=False):
            import importlib
            from core import config as cfg_module
            importlib.reload(cfg_module)
            from core.config import config
            assert config.allowed_prefix == "/custom/prefix"

    def test_heartbeat_float_conversion(self):
        with patch.dict(os.environ, {"HAVEN_HEARTBEAT_INTERVAL": "60"}, clear=False):
            import importlib
            from core import config as cfg_module
            importlib.reload(cfg_module)
            from core.config import config
            assert config.heartbeat_interval == 60.0


class TestConfigTokenProperties:
    """Token properties read from env (secrets)."""

    def test_discord_token_none_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            from core import config as cfg_module
            importlib.reload(cfg_module)
            from core.config import config
            assert config.discord_token == ""

    def test_discord_token_reads_primary(self):
        with patch.dict(os.environ, {"HAVEN_DISCORD_TOKEN": "primary_tok"}, clear=True):
            import importlib
            from core import config as cfg_module
            importlib.reload(cfg_module)
            from core.config import config
            assert config.discord_token == "primary_tok"

    def test_discord_token_ignores_legacy(self):
        with patch.dict(os.environ, {"DISCORD_TOKEN": "legacy_tok"}, clear=True):
            import importlib
            from core import config as cfg_module
            importlib.reload(cfg_module)
            from core.config import config
            assert config.discord_token == ""

    def test_telegram_token_none_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            from core import config as cfg_module
            importlib.reload(cfg_module)
            from core.config import config
            assert config.telegram_token == ""

    def test_telegram_token_ignores_legacy(self):
        with patch.dict(os.environ, {"TELEGRAM_TOKEN": "legacy_tg"}, clear=True):
            import importlib
            from core import config as cfg_module
            importlib.reload(cfg_module)
            from core.config import config
            assert config.telegram_token == ""


class TestConfigIsFrozen:
    """HavenConfig is frozen — no mutation."""

    def test_cannot_set_attr(self):
        from core.config import HavenConfig
        c = HavenConfig()
        with pytest.raises(Exception, match="cannot assign"):
            c.primary_model = "other"
