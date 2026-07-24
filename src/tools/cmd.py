"""execute_command tool — Phase 3: shell execution (pipe/redirect live).

Uses create_subprocess_shell for real shell execution.
Safety: classify_command() blocks DANGEROUS commands first,
then file_guard validates all write targets.
"""

import asyncio
import os
import shlex

from core.categories import ToolCategory
from core.file_guard import extract_paths, is_write_allowed
from core.policy import ToolPolicy, classify_command
from core.tool_decorator import tool


def _translate_path(cmd: str) -> str:
    """Translate Windows-style paths to Linux mounts.

    Z:\\path\\to\\thing  →  /mnt/z/path/to/thing
    Z:/path/to/thing     →  /mnt/z/path/to/thing
    backslashes          →  forward slashes
    """
    result = []
    i = 0
    while i < len(cmd):
        c = cmd[i]

        if (
            i + 2 < len(cmd)
            and cmd[i].isalpha()
            and cmd[i + 1] == ":"
            and cmd[i + 2] in ("\\", "/")
        ):
            drive = cmd[i].lower()
            i += 3
            path_chars = []
            while i < len(cmd) and cmd[i] not in (" ", "\t", "\n", "'", '"'):
                path_chars.append(cmd[i])
                i += 1
            raw_path = "".join(path_chars).replace("\\", "/")
            linux_path = f"/mnt/{drive}/{raw_path}"
            result.append(linux_path)
        elif c == "\\":
            result.append("/")
            i += 1
        else:
            result.append(c)
            i += 1

    return "".join(result)


@tool(
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=30.0, rate_limit=3.0),
)
async def execute_command(cmd: str) -> str:
    """Run a shell command and return its output.

    Phase 3 tiered safety with real shell execution:
        READONLY  — no path check (ls, cat, grep, ...)
        NORMAL    — file_guard validates all write targets
        DANGEROUS — blocked (dd, sudo, kill, ...)

    Pipes (|), redirects (>, >>), chaining (&&, ;), and command
    substitution ($( ), backticks) are all fully functional via
    /bin/sh -c execution.

    Args:
        cmd: Shell command to execute.  Z:\\ paths auto-translated.

    Returns:
        Combined stdout and stderr, or an error/blocked message.
    """
    # Translate Windows paths
    translated = _translate_path(cmd)

    # Extract base command for tier classification
    try:
        parts = shlex.split(translated)
    except ValueError:
        # Fallback: simple split for classification
        parts = translated.split()

    if not parts:
        return "[error] No command provided."

    base = parts[0]
    base_clean = base.split("/")[-1]

    # Phase 2: tier classification
    tier, reason = classify_command(base, translated)
    if tier == "DANGEROUS":
        return f"[blocked] {reason}"

    # Phase 1: path whitelist (skip for READONLY)
    if tier != "READONLY":
        paths = extract_paths(translated)
        # Exclude the executable itself from path checks
        paths = [p for p in paths if os.path.basename(p) != base_clean]
        for p in paths:
            allowed, reason = is_write_allowed(p)
            if not allowed:
                return f"[blocked] {reason}"

    # Phase 3: real shell execution
    try:
        proc = await asyncio.create_subprocess_shell(
            translated,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=30
        )
    except TimeoutError:
        return "[error] Command timed out after 30 seconds."
    except Exception as e:
        return f"[error] {e}"

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")

    if out and err:
        result = f"{out}\n{err}"
    else:
        result = out or err or "(no output)"

    if base_clean in {"rm", "mv", "chmod", "chown"}:
        result += "\n[warning] Destructive command executed — file_guard is active."

    return result
