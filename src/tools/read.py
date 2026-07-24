import os

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.tool_decorator import tool
from core.config import config  # noqa: E402

# Common binary file extensions / magic checks
# We use a heuristic: read the first 8 KB and check for null bytes.
_READ_CHUNK = 8192


def _allowed_prefix() -> str:
    """Return the allowed path prefix (overridable via env for CI).

    Default: ``HAVEN_ROOT/..``, which on WSL2 is ``/mnt/z/`` (full drive)
            and on Orange Pi is ``/opt/`` (sensible sandbox).
    """
    from core.paths import haven_dir
    root_parent = str(haven_dir().parent) + "/"
    return config.allowed_prefix or root_parent


def _is_binary(filepath: str) -> bool:
    """Heuristic: check if a file looks binary by scanning for null bytes."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(_READ_CHUNK)
        return b"\x00" in chunk
    except OSError:
        return False


@tool(
    category=ToolCategory.FILE,
    policy=ToolPolicy(timeout=10.0, rate_limit=2.0),
)
async def read_file(path: str) -> str:
    """Read the contents of a file.

    Args:
        path: Absolute or relative path to read. Must resolve under the
             allowed prefix (``HAVEN_ALLOWED_PREFIX`` or ``HAVEN_ROOT/..``).

    Returns:
        The file contents as a string, or an error message.
        For binary files, returns the file size and a warning.
    """
    # Resolve to absolute path
    resolved = os.path.realpath(os.path.abspath(path))

    # Must be under the allowed prefix
    prefix = _allowed_prefix()
    if not resolved.startswith(prefix):
        return f"[error] Path must be under {prefix.rstrip('/')}/.  Got: {resolved}"

    # Check existence
    if not os.path.exists(resolved):
        # Auto-list parent directory to help the LLM find the right file
        parent = os.path.dirname(resolved) or "."
        try:
            siblings = sorted(os.listdir(parent))
        except (OSError, PermissionError):
            siblings = ["(cannot read directory)"]
        listing = ", ".join(siblings[:50])
        if len(siblings) > 50:
            listing += f" ... and {len(siblings) - 50} more"
        return f"[error] File not found: {resolved}\nDirectory '{parent}' contains: [{listing}]"

    if not os.path.isfile(resolved):
        return f"[error] Not a regular file: {resolved}"

    # Binary detection
    if _is_binary(resolved):
        size = os.path.getsize(resolved)
        return f"[warning] Binary file ({size} bytes).  Not displaying contents."

    # Read as text
    try:
        with open(resolved, encoding="utf-8") as f:
            data = f.read()
        return data
    except UnicodeDecodeError:
        size = os.path.getsize(resolved)
        return f"[warning] File could not be decoded as UTF-8 ({size} bytes).  It may be binary."
    except OSError as e:
        return f"[error] Could not read file: {e}"
