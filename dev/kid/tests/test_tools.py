"""
Behavior tests for the tool modules (cmd, read, write).

Tests real pure-logic functions directly — no mocking of filesystem
operations; uses tmp_path for temporary file scenarios.
"""

from __future__ import annotations

import os

import pytest


# ======================================================================
# CMD tool
# ======================================================================

class TestCmdSafety:
    """Test _is_safe() and _translate_path() from tools/cmd.py."""

    # -- helpers -------------------------------------------------------

    def _import_functions(self):
        """Import private functions from tools/cmd for isolated testing."""
        from tools.cmd import _is_safe, _translate_path, DANGEROUS_COMMANDS, SHELL_METACHARS
        self._is_safe = _is_safe
        self._translate_path = _translate_path
        self.DANGEROUS_COMMANDS = DANGEROUS_COMMANDS
        self.SHELL_METACHARS = SHELL_METACHARS

    # -- dangerous commands --------------------------------------------

    def test_rejects_dangerous_commands(self):
        self._import_functions()
        for cmd in ("rm", "mv", "dd", "mkfs", "shutdown", "reboot", "sudo"):
            safe, reason = self._is_safe(cmd + " -rf /")
            assert not safe, f"Command '{cmd}' should be blocked"
            assert cmd in reason

    # -- shell metacharacters ------------------------------------------

    def test_rejects_semicolon(self):
        self._import_functions()
        safe, _ = self._is_safe("echo hi ; ls")
        assert not safe

    def test_rejects_pipe(self):
        self._import_functions()
        safe, _ = self._is_safe("ls | grep foo")
        assert not safe

    def test_rejects_ampersand(self):
        self._import_functions()
        safe, _ = self._is_safe("sleep 1 &")
        assert not safe

    def test_rejects_backtick(self):
        self._import_functions()
        safe, _ = self._is_safe("echo `whoami`")
        assert not safe

    def test_rejects_dollar_subshell(self):
        self._import_functions()
        safe, _ = self._is_safe("echo $(whoami)")
        assert not safe

    def test_rejects_parentheses(self):
        self._import_functions()
        safe, _ = self._is_safe("(echo hi)")
        assert not safe

    def test_accepts_safe_command(self):
        self._import_functions()
        safe, _ = self._is_safe("ls -la /tmp")
        assert safe

    # -- Windows path translation --------------------------------------

    def test_translates_z_drive_backslash(self):
        self._import_functions()
        translated = self._translate_path("cat Z:\\path\\to\\file.txt")
        assert "/mnt/z/path/to/file.txt" in translated

    def test_translates_z_drive_forward_slash(self):
        self._import_functions()
        translated = self._translate_path("cat Z:/path/to/file.txt")
        assert "/mnt/z/path/to/file.txt" in translated

    def test_translates_c_drive(self):
        self._import_functions()
        translated = self._translate_path("cat C:/Users/test")
        assert "/mnt/c/Users/test" in translated

    def test_standalone_backslash_to_forward(self):
        self._import_functions()
        translated = self._translate_path("dir\\subdir")
        assert "/" in translated
        assert "\\" not in translated

    def test_rejects_empty_command(self):
        self._import_functions()
        safe, reason = self._is_safe("")
        assert not safe
        assert "No command" in reason

    # -- execute_command invokes subprocess ----------------------------
    # Use a simple safe command that actually works on any Unix.

    @pytest.mark.asyncio
    async def test_execute_simple_command(self):
        from tools.cmd import execute_command
        result = await execute_command("echo hello_tool_test")
        assert "hello_tool_test" in result

    @pytest.mark.asyncio
    async def test_file_not_found_returns_error(self):
        from tools.cmd import execute_command
        result = await execute_command("nonexistent_command_xyz123")
        assert "[error]" in result
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_blocked_command_returns_error(self):
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
    def safe_file(self, request):
        """Create a temporary text file under /mnt/z/."""
        import tempfile
        d = f"/mnt/z/.tmp_test_{request.node.name}"
        os.makedirs(d, exist_ok=True)
        f = os.path.join(d, "hello.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("Hello, world!")
        yield f
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    @pytest.fixture
    def binary_file(self, request):
        """Create a temp binary file under /mnt/z/."""
        import tempfile
        d = f"/mnt/z/.tmp_test_{request.node.name}"
        os.makedirs(d, exist_ok=True)
        f = os.path.join(d, "binary.bin")
        with open(f, "wb") as fh:
            fh.write(b"\x00\x01\x02")
        yield f
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    # -- path restrictions ---------------------------------------------

    @pytest.mark.asyncio
    async def test_rejects_path_outside_prefix(self):
        from tools.read import read_file

        result = await read_file("/etc/passwd")
        assert "[error]" in result

    # -- symlink escape -------------------------------------------------

    @pytest.mark.asyncio
    async def test_rejects_symbolic_link_escape(self, request):
        from tools.read import read_file
        d = f"/mnt/z/.tmp_test_{request.node.name}"
        os.makedirs(d, exist_ok=True)
        link = os.path.join(d, "escape_link")
        os.symlink("/etc/passwd", link)
        result = await read_file(link)
        assert "[error]" in result
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    # -- file not found -------------------------------------------------

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        from tools.read import read_file
        result = await read_file("/mnt/z/.tmp_test_nonexistent_xyz.txt")
        assert "[error]" in result
        assert "not found" in result.lower()

    # -- binary detection -----------------------------------------------

    def test_detects_binary_file(self, tmp_path):
        """_is_binary should detect null bytes — pure function, no prefix check."""
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
    async def test_read_binary_warns(self, binary_file):
        from tools.read import read_file
        result = await read_file(binary_file)
        assert "[warning]" in result
        assert "Binary" in result

    # -- text file read -------------------------------------------------

    @pytest.mark.asyncio
    async def test_reads_text_file_success(self, safe_file):
        from tools.read import read_file
        result = await read_file(safe_file)
        assert "Hello, world!" in result


# ======================================================================
# WRITE tool
# ======================================================================

class TestWriteTool:
    """Test the write_file tool function."""



    @pytest.mark.asyncio
    async def test_rejects_path_outside_prefix(self):
        from tools.write import write_file
        result = await write_file("/etc/evil.conf", "pwned")
        assert "[error]" in result

    @pytest.mark.asyncio
    async def test_rejects_protected_file_by_name(self):
        from tools.write import write_file
        result = await write_file("/mnt/z/project/.env", "SECRET=1")
        assert "[error]" in result
        assert "protected" in result.lower()

    @pytest.mark.asyncio
    async def test_rejects_protected_file_by_extension(self):
        from tools.write import write_file
        result = await write_file("/mnt/z/project/secret.key", "xxx")
        assert "[error]" in result
        assert "protected" in result.lower()

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, request):
        from tools.write import write_file
        path = f"/mnt/z/.tmp_test_{request.node.name}/newdir/nested/file.txt"
        result = await write_file(path, "nested content")
        assert "[ok]" in result
        assert os.path.isfile(path)

    @pytest.mark.asyncio
    async def test_writes_and_overwrites(self, request):
        from tools.write import write_file
        from tools.read import read_file
        d = f"/mnt/z/.tmp_test_{request.node.name}"
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "rw.txt")

        # Write initial content
        result1 = await write_file(path, "first version")
        assert "[ok]" in result1

        # Verify via read_file
        content = await read_file(path)
        assert content == "first version"

        # Overwrite
        result2 = await write_file(path, "second version")
        assert "[ok]" in result2

        content2 = await read_file(path)
        assert content2 == "second version"
