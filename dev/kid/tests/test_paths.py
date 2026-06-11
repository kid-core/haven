"""Test core/paths.py — path resolution with HAVEN_ROOT / CORE_ROOT env vars."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Module-under-test must be reloaded per test since it reads env at import ──
@pytest.fixture
def paths():
    """Reload paths module with controlled env."""
    import importlib
    mod_name = "core.paths"

    # Remove cached module so importlib.reload picks up a fresh copy
    for key in list(sys.modules.keys()):
        if key == mod_name or key.startswith(mod_name + "."):
            del sys.modules[key]

    import core.paths as p
    return p


class TestDefaultPaths:
    """When no env vars are set, all paths match current WSL2 layout."""

    def test_haven_root_default(self, monkeypatch):
        monkeypatch.delenv("HAVEN_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.haven_dir() == Path("/mnt/z/Haven")

    def test_core_root_default(self, monkeypatch):
        monkeypatch.delenv("CORE_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.core_dir() == Path("/mnt/z/Core")

    def test_code_dir_default(self, monkeypatch):
        monkeypatch.delenv("HAVEN_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.code_dir() == Path("/mnt/z/Haven/dev/kid")

    def test_config_dir_default(self, monkeypatch):
        monkeypatch.delenv("HAVEN_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.config_dir() == Path("/mnt/z/Haven/config")

    def test_data_dir_default(self, monkeypatch):
        monkeypatch.delenv("HAVEN_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.data_dir() == Path("/mnt/z/Haven/data")

    def test_session_dir_default(self, monkeypatch):
        monkeypatch.delenv("HAVEN_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.session_dir() == Path("/mnt/z/Haven/data/sessions")

    def test_venv_dir_default(self, monkeypatch):
        monkeypatch.delenv("HAVEN_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.venv_dir() == Path("/mnt/z/Haven/.venv")

    def test_haven_env_default(self, monkeypatch):
        monkeypatch.delenv("HAVEN_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        # falls back to HAVEN_ROOT/.env when config/.env doesn't exist
        assert core.paths.haven_env() == Path("/mnt/z/Haven/.env")

    def test_core_env_default(self, monkeypatch):
        monkeypatch.delenv("CORE_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.core_env() == Path("/mnt/z/Core/.env")

    def test_openclaw_env_default(self, monkeypatch):
        monkeypatch.delenv("OPENCLAW_ENV", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.openclaw_env() == Path("/root/.openclaw/env")

    def test_log_file_default(self, monkeypatch):
        monkeypatch.delenv("HAVEN_LOG_FILE", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.log_file() == Path("/tmp/haven.log")

    def test_pid_file_default(self, monkeypatch):
        monkeypatch.delenv("HAVEN_PID_FILE", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.pid_file() == Path("/tmp/haven.pid")

    def test_identity_file_default(self, monkeypatch):
        monkeypatch.delenv("HAVEN_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.identity_file() == Path("/mnt/z/Haven/IDENTITY.md")

    def test_chronicle_file_default(self, monkeypatch):
        monkeypatch.delenv("CORE_ROOT", raising=False)
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.chronicle_file() == Path("/mnt/z/Core/Soul/Chronicle.md")


class TestCustomPaths:
    """When env vars are set, paths resolve to the custom locations."""

    def test_haven_root_custom(self, monkeypatch):
        monkeypatch.setenv("HAVEN_ROOT", "/opt/haven")
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.haven_dir() == Path("/opt/haven")
        assert core.paths.code_dir() == Path("/opt/haven/dev/kid")
        assert core.paths.venv_dir() == Path("/opt/haven/.venv")

    def test_core_root_custom(self, monkeypatch):
        monkeypatch.setenv("CORE_ROOT", "/opt/core")
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.core_dir() == Path("/opt/core")
        assert core.paths.core_env() == Path("/opt/core/.env")

    def test_openclaw_env_custom(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_ENV", "/custom/openclaw/env")
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.openclaw_env() == Path("/custom/openclaw/env")

    def test_log_file_custom(self, monkeypatch):
        monkeypatch.setenv("HAVEN_LOG_FILE", "/var/log/haven.log")
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert core.paths.log_file() == Path("/var/log/haven.log")

    def test_all_derived_from_haven_root(self, monkeypatch):
        """Every Haven-scoped path stays under HAVEN_ROOT."""
        monkeypatch.setenv("HAVEN_ROOT", "/opt/haven")
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        p = core.paths
        for fn in [p.code_dir, p.config_dir, p.data_dir, p.venv_dir]:
            result = fn()
            assert str(result).startswith("/opt/haven"), \
                f"{fn.__name__}() = {result} — not under /opt/haven"


class TestBackwardCompatibility:
    """Backward compat: unset HAVEN_ROOT → behavior identical to pre-refactor."""

    def test_paths_unchanged_when_no_env(self, monkeypatch):
        monkeypatch.delenv("HAVEN_ROOT", raising=False)
        monkeypatch.delenv("CORE_ROOT", raising=False)
        monkeypatch.delenv("OPENCLAW_ENV", raising=False)
        monkeypatch.delenv("HAVEN_LOG_FILE", raising=False)
        monkeypatch.delenv("HAVEN_PID_FILE", raising=False)

        import importlib, sys, core.paths
        importlib.reload(core.paths)
        p = core.paths

        assert str(p.haven_dir()) == "/mnt/z/Haven"
        assert str(p.core_dir()) == "/mnt/z/Core"
        assert str(p.code_dir()) == "/mnt/z/Haven/dev/kid"
        assert str(p.venv_dir()) == "/mnt/z/Haven/.venv"
        assert str(p.log_file()) == "/tmp/haven.log"
        assert str(p.pid_file()) == "/tmp/haven.pid"


class TestIdentitySources:
    """Soul / identity paths resolve from HAVEN_ROOT and CORE_ROOT."""

    def test_identity_from_haven(self, monkeypatch):
        monkeypatch.setenv("HAVEN_ROOT", "/opt/haven")
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert str(core.paths.identity_file()).startswith("/opt/haven")

    def test_chronicle_from_core(self, monkeypatch):
        monkeypatch.setenv("CORE_ROOT", "/opt/core")
        import importlib, sys, core.paths
        importlib.reload(core.paths)
        assert str(core.paths.chronicle_file()).startswith("/opt/core")
