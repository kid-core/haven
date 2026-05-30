"""
Behavior tests for the tool modules (cmd, read, write).

Tests real pure-logic functions directly — no mocking of filesystem
operations; uses tmp_path with HAVEN_ALLOWED_PREFIX for CI compatibility.
"""

from __future__ import annotations

import pytest

# ======================================================================
# CMD tool
# ======================================================================

class TestCmdSafety:
    """Test _is_safe() and _translate_path() from tools/cmd.py."""

    # -- helpers -------------------------------------------------------

    def _import_functions(self):
        """Import private functions from tools/cmd for isolated testing."""
        from tools.cmd import DANGEROUS_COMMANDS, SHELL_METACHARS, _is_safe, _translate_path
        self._is_safe = _is_safe
        self._translate_path = _translate_path
        self.DANGEROUS_COMMANDS = DANGEROUS_COMMANDS
        self.SHELL_METACHARS = SHELL_METACHARS

    # -- _is_safe tests ------------------------------------------------

    def test_rejects_empty_command(self):
        self._import_functions()
        safe, _ = self._is_safe("")
        assert not safe
        safe, _ = self._is_safe("   ")
        assert not safe

    def test_allows_simple_command(self):
        self._import_functions()
        safe, _ = self._is_safe("ls -la /tmp")
        assert safe

    def test_rejects_dangerous_command(self):
        self._import_functions()
        for bad in ["rm -rf /", "sudo echo hi", "mkfs.ext4 /dev/sda", "dd if=/dev/zero of=/dev/sda"]:
            safe, _ = self._is_safe(bad)
            assert not safe, f"Should reject: {bad}"

    def test_rejects_shell_metacharacters(self):
        self._import_functions()
        for meta in self.SHELL_METACHARS:
            cmd = f"ls {meta}"
            safe, _ = self._is_safe(cmd)
            assert not safe, f"Should reject metachar: {cmd}"

    # -- _translate_path tests -----------------------------------------

    def test_translate_windows_path_backslash(self):
        self._import_functions()
        result = self._translate_path(r"Z:\path\to\file.txt")
        assert "/mnt/z/path/to/file.txt" in result

    def test_translate_windows_path_forwardslash(self):
        self._import_functions()
        result = self._translate_path(r"Z:/path/to/file.txt")
        assert "/mnt/z/path/to/file.txt" in result

    def test_translate_drive_c(self):
        self._import_functions()
        result = self._translate_path(r"C:\Users\test")
        assert "/mnt/c/Users/test" in result

    def test_leave_linux_path_untouched(self):
        self._import_functions()
        result = self._translate_path("/home/user/file.txt")
        assert result == "/home/user/file.txt"

    # -- execute_command integration -----------------------------------

    @pytest.mark.asyncio
    async def test_rejects_empty_command(self):
        from tools.cmd import execute_command
        result = await execute_command("")
        assert "[blocked]" in result

    @pytest.mark.asyncio
    async def test_rejects_dangerous_command(self):
        from tools.cmd import execute_command
        result = await execute_command("rm -rf /")
        assert "[blocked]" in result

    @pytest.mark.asyncio
    async def test_shell_metachars_blocked(self):
        from tools.cmd import execute_command
        result = await execute_command("ls ; echo hi")
        assert "[blocked]" in result


# ======================================================================
# READ tool
# ======================================================================

class TestReadTool:
    """Test the read_file tool function."""

    @pytest.fixture
    def work_dir(self, tmp_path, monkeypatch):
        """Set HAVEN_ALLOWED_PREFIX to tmp_path and return it."""
        monkeypatch.setenv("HAVEN_ALLOWED_PREFIX", str(tmp_path) + "/")
        return tmp_path

    # -- path restrictions ---------------------------------------------

    @pytest.mark.asyncio
    async def test_rejects_path_outside_prefix(self):
        from tools.read import read_file
        result = await read_file("/etc/passwd")
        assert "[error]" in result

    # -- symlink escape -------------------------------------------------

    @pytest.mark.asyncio
    async def test_rejects_symbolic_link_escape(self, work_dir):
        from tools.read import read_file
        link = work_dir / "escape_link"
        link.symlink_to("/etc/passwd")
        result = await read_file(str(link))
        assert "[error]" in result

    # -- file not found -------------------------------------------------

    @pytest.mark.asyncio
    async def test_file_not_found(self, work_dir):
        from tools.read import read_file
        result = await read_file(str(work_dir / "nonexistent.txt"))
        assert "[error]" in result
        assert "not found" in result.lower()

    # -- binary detection -----------------------------------------------

    def test_detects_binary_file(self, tmp_path):
        """_is_binary should detect null bytes — pure function."""
        from tools.read import _is_binary
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02")
        assert _is_binary(str(f)) is True

    def test_skips_non_binary(self, tmp_path):
        from tools.read import _is_binary
        f = tmp_path / "text.txt"
        f.write_text("Hello")
        assert _is_binary(str(f)) is False

    @pytest.mark.asyncio
    async def test_read_binary_warns(self, work_dir):
        from tools.read import read_file
        f = work_dir / "binary.bin"
        f.write_bytes(b"\x00\x01\x02")
        result = await read_file(str(f))
        assert "[warning]" in result
        assert "Binary" in result

    # -- text file read -------------------------------------------------

    @pytest.mark.asyncio
    async def test_reads_text_file_success(self, work_dir):
        from tools.read import read_file
        f = work_dir / "hello.txt"
        f.write_text("Hello, world!")
        result = await read_file(str(f))
        assert "Hello, world!" in result


# ======================================================================
# WRITE tool
# ======================================================================

class TestWriteTool:
    """Test the write_file tool function."""

    @pytest.fixture
    def work_dir(self, tmp_path, monkeypatch):
        """Set HAVEN_ALLOWED_PREFIX to tmp_path and return it."""
        monkeypatch.setenv("HAVEN_ALLOWED_PREFIX", str(tmp_path) + "/")
        return tmp_path

    @pytest.mark.asyncio
    async def test_rejects_path_outside_prefix(self):
        from tools.write import write_file
        result = await write_file("/etc/evil.conf", "pwned")
        assert "[error]" in result

    @pytest.mark.asyncio
    async def test_rejects_protected_file_by_name(self, work_dir):
        from tools.write import write_file
        result = await write_file(str(work_dir / ".env"), "SECRET=1")
        assert "[error]" in result
        assert "protected" in result.lower()

    @pytest.mark.asyncio
    async def test_rejects_protected_file_by_extension(self, work_dir):
        from tools.write import write_file
        result = await write_file(str(work_dir / "secret.key"), "xxx")
        assert "[error]" in result
        assert "protected" in result.lower()

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, work_dir):
        from tools.write import write_file
        path = work_dir / "newdir" / "nested" / "file.txt"
        result = await write_file(str(path), "nested content")
        assert "[ok]" in result
        assert path.is_file()
        assert path.read_text() == "nested content"

    @pytest.mark.asyncio
    async def test_writes_and_overwrites(self, work_dir):
        from tools.read import read_file
        from tools.write import write_file

        path = work_dir / "rw.txt"

        result1 = await write_file(str(path), "first version")
        assert "[ok]" in result1

        content1 = await read_file(str(path))
        assert content1 == "first version"

        result2 = await write_file(str(path), "second version")
        assert "[ok]" in result2

        content2 = await read_file(str(path))
        assert content2 == "second version"
