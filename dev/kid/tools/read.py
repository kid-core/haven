import os

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.tool_decorator import tool

# Common binary file extensions / magic checks
# We use a heuristic: read the first 8 KB and check for null bytes.
_READ_CHUNK = 8192


def _allowed_prefix() -> str:
    """Return the allowed path prefix (overridable via env for CI)."""
    return os.getenv("HAVEN_ALLOWED_PREFIX", "/mnt/z/")


def _is_binary(filepath: str) -> bool:
    """Heuristic: check if a file looks binary by scanning for null bytes."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(_READ_CHUNK)
        return b"\x00" in chunk
    except OSError:
        return False


@tool(
    category=ToolCategory.FILES,
    policy=ToolPolicy(timeout=10.0, rate_limit=2.0),
)
async def read_file(path: str) -> str:
    """Read the contents of a file.

    Args:
        path: Absolute or relative path to read. Must resolve under /mnt/z/.

    Returns:
        The file contents as a string, or an error message.
        For binary files, returns the file size and a warning.
    """
    # Resolve to absolute path
    resolved = os.path.realpath(os.path.abspath(path))

    # Must be under /mnt/z/
    prefix = _allowed_prefix()
    if not resolved.startswith(prefix):
        return f"[error] Path must be under {prefix.strip('/')}/.  Got: {resolved}"

    # Check existence
    if not os.path.exists(resolved):
        return f"[error] File not found: {resolved}"

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
