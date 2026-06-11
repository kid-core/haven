import asyncio
import shlex

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.tool_decorator import tool

DANGEROUS_COMMANDS = {"rm", "mv", "dd", "mkfs", "sudo"}
MODERATE_COMMANDS = {"kill", "pkill", "shutdown", "reboot", "systemctl", "service"}

SHELL_METACHARS = frozenset(";|&`$()")


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

        # Drive letter pattern: X:\ or X:/
        if (
            i + 2 < len(cmd)
            and cmd[i].isalpha()
            and cmd[i + 1] == ":"
            and cmd[i + 2] in ("\\", "/")
        ):
            drive = cmd[i].lower()
            i += 3

            # Collect the rest of the path
            path_chars = []
            while i < len(cmd) and cmd[i] not in (" ", "\t", "\n", "'", '"'):
                path_chars.append(cmd[i])
                i += 1

            raw_path = "".join(path_chars)
            # Replace backslashes with forward slashes
            raw_path = raw_path.replace("\\", "/")

            # Build the Linux path
            linux_path = f"/mnt/{drive}/{raw_path}"
            result.append(linux_path)
        # Standalone backslash → forward slash
        elif c == "\\":
            result.append("/")
            i += 1
        else:
            result.append(c)
            i += 1

    return "".join(result)


def _is_safe(cmd: str) -> tuple[bool, str]:
    """Check if the command is safe to execute.

    Returns (safe, reason).  safe=False means blocked.
    """
    # Reject shell metacharacters
    for ch in cmd:
        if ch in SHELL_METACHARS:
            return False, f"Shell metacharacter '{ch}' is not allowed for safety."

    # Split with shlex to get the base command
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return False, f"Unable to parse command: {e}"

    if not parts:
        return False, "No command provided."

    base = parts[0]
    # Check against dangerous commands
    if base in DANGEROUS_COMMANDS:
        return False, f"Command '{base}' is blocked for safety."

    return True, ""


@tool(
    category=ToolCategory.ENV,
    policy=ToolPolicy(timeout=30.0, rate_limit=10.0),
)
async def execute_command(cmd: str) -> str:
    """Run a shell command and return its output (留意制 tiered safety).

    留意制 tiers:
        - 🟢 Auto: Most commands execute directly.
        - 🟡 Warn: Moderated commands (kill, pkill, shutdown, reboot,
          systemctl, service) execute but append a warning to output.
        - 🔴 Block: Dangerous commands (rm, mv, dd, mkfs, sudo) are refused.

    Args:
        cmd: The command to execute.  On WSL2, Z:\\ paths are automatically
             translated to /mnt/z/.  Shell metacharacters (; | & ` $ ( )) are
             rejected for safety.

    Returns:
        Combined stdout and stderr, or an error message.
    """
    # Safety checks
    safe, reason = _is_safe(cmd)
    if not safe:
        return f"[blocked] {reason}"

    # Translate Windows paths → Linux mounts
    translated = _translate_path(cmd)

    try:
        parts = shlex.split(translated)
    except ValueError as e:
        return f"[error] Unable to parse command: {e}"

    try:
        proc = await asyncio.create_subprocess_exec(
            *parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=30
        )
    except TimeoutError:
        return "[error] Command timed out after 30 seconds."
    except FileNotFoundError:
        return f"[error] Command not found: {parts[0]}"
    except PermissionError:
        return f"[error] Permission denied: {parts[0]}"
    except Exception as e:
        return f"[error] {e}"

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")

    if out and err:
        result = f"{out}\n{err}"
    else:
        result = out or err or "(no output)"

    # Append moderated-command warning when applicable
    if parts[0] in MODERATE_COMMANDS:
        result += "\n⚠️  Moderated command executed — proceed with caution."

    return result
