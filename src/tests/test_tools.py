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
    """Test classify_command() from core/policy.py and _translate_path() from tools/cmd.py."""

    # -- helpers -------------------------------------------------------

    def _import_functions(self):
        """Import functions for isolated testing."""
        from tools.cmd import _translate_path
        from core.policy import DANGEROUS_COMMANDS, classify_command
        self._translate_path = _translate_path
        self._classify = classify_command
        self.DANGEROUS_COMMANDS = DANGEROUS_COMMANDS

    # -- classify_command tests (Phase 2) -----------------------------

    def test_allows_readonly_command(self):
        self._import_functions()
        for cmd in ["ls -la", "cat file.txt", "grep test *.py", "find . -name x",
                     "ps aux", "echo hello", "pwd", "head file.txt", "wc -l"]:
            base = cmd.split()[0]
            tier, reason = self._classify(base, cmd)
            assert tier == "READONLY", f"Expected READONLY for {cmd!r}, got {tier}"

    def test_allows_normal_command(self):
        self._import_functions()
        for cmd in ["python main.py", "mkdir testdir", "cp a b", "curl example.com",
                     "git status", "git log"]:
            base = cmd.split()[0]
            tier, _ = self._classify(base, cmd)
            assert tier == "NORMAL", f"Expected NORMAL for {cmd!r}, got {tier}"

    def test_rejects_dangerous_command(self):
        self._import_functions()
        for bad in [("sudo", "sudo echo hi"), ("mkfs", "mkfs.ext4 /dev/sda"),
                     ("dd", "dd if=/dev/zero of=/dev/sda"), ("kill", "kill 1234"),
                     ("shutdown", "shutdown now"), ("systemctl", "systemctl restart")]:
            base, cmd = bad
            tier, _ = self._classify(base, cmd)
            assert tier == "DANGEROUS", f"Should be DANGEROUS: {cmd}"

    def test_rejects_dangerous_subcommands(self):
        self._import_functions()
        for sub in ["git push --force", "git push -f", "pip install pkg",
                     "git reset --hard"]:
            base = sub.split()[0]
            tier, _ = self._classify(base, sub)
            assert tier == "DANGEROUS", f"Should be DANGEROUS: {sub}"

    def test_redirects_are_classified(self):
        """Redirects are not blocked at classify level — cmd.py checks via file_guard."""
        self._import_functions()
        for cmd in ["ls > file.txt", "echo test >> log"]:
            base = cmd.split()[0]
            tier, _ = self._classify(base, cmd)
            # Should not be DANGEROUS — redirect validation happens later in file_guard
            assert tier in ("READONLY", "NORMAL"), f"{cmd!r} got {tier}, expected READONLY or NORMAL"

    def test_readonly_with_redirect_bumps_to_normal(self):
        """READONLY commands with > or >> must become NORMAL so file_guard runs."""
        self._import_functions()
        # echo > /etc/ should be NORMAL (redirect triggers path check)
        tier, _ = self._classify("echo", "echo hello > /etc/evil.txt")
        assert tier == "NORMAL", f"echo > /etc/ should be NORMAL, got {tier}"
        tier, _ = self._classify("ls", "ls >> /boot/bad")
        assert tier == "NORMAL", f"ls >> /boot should be NORMAL, got {tier}"

    def test_readonly_without_redirect_stays_readonly(self):
        """Bare READONLY commands without redirect should stay READONLY."""
        self._import_functions()
        tier, _ = self._classify("ls", "ls -la /tmp")
        assert tier == "READONLY"
        tier, _ = self._classify("echo", "echo hello world")
        assert tier == "READONLY"

    def test_shell_metacharacters_allowed(self):
        """Phase 2: shell metacharacters are NO LONGER blocked."""
        self._import_functions()
        for cmd in ["ls | grep test", "echo a && echo b", "cat a; cat b",
                     "echo $(date)"]:
            base = cmd.split()[0]
            tier, _ = self._classify(base, cmd)
            assert tier in ("READONLY", "NORMAL"), f"{cmd!r} should be allowed, got {tier}"

    # -- _translate_path tests ----------------------------------------

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

    def test_translate_mixed_paths_in_command(self):
        self._import_functions()
        result = self._translate_path(r"python Z:\haven\script.py")
        assert "/mnt/z/haven/script.py" in result
        assert result.startswith("python ")

    def test_translate_standalone_backslash(self):
        self._import_functions()
        result = self._translate_path("dir\\subdir")
        assert "dir/subdir" in result


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
        assert "[blocked]" in result or "[error]" in result

    @pytest.mark.asyncio
    async def test_rejects_protected_file_by_name(self, work_dir):
        from tools.write import write_file
        result = await write_file(str(work_dir / ".env"), "SECRET=1")
        assert "[blocked]" in result or "[error]" in result
        assert "protected" in result.lower()

    @pytest.mark.asyncio
    async def test_rejects_protected_file_by_extension(self, work_dir):
        from tools.write import write_file
        result = await write_file(str(work_dir / "secret.key"), "xxx")
        assert "[blocked]" in result or "[error]" in result
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
