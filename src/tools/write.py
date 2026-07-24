import os

from core.categories import ToolCategory
from core.file_guard import is_write_allowed
from core.policy import ToolPolicy
from core.tool_decorator import tool


# Files that must never be overwritten
PROTECTED_NAMES = {".env", "identity.md"}
PROTECTED_EXTENSIONS = {".key"}


def _is_protected(path: str) -> bool:
    """Check if a file is protected from overwriting."""
    basename = os.path.basename(path)
    if basename in PROTECTED_NAMES:
        return True
    _, ext = os.path.splitext(basename)
    return ext in PROTECTED_EXTENSIONS


@tool(
    category=ToolCategory.FILE,
    policy=ToolPolicy(timeout=10.0, rate_limit=2.0),
)
async def write_file(path: str, content: str) -> str:
    """Write content to a file (留意制: 🟢 auto-run, 🔴 block protected files).

    留意制 tier:
        - 🟢 Auto: Writes proceed directly for normal files.
        - 🔴 Block: Refuses to overwrite ``.env``, ``identity.md``, or ``*.key``
          (PROTECTED_NAMES / PROTECTED_EXTENSIONS).

    Args:
        path: Absolute or relative path to write to. Must resolve under the
             allowed prefix (``HAVEN_ALLOWED_PREFIX`` or ``HAVEN_ROOT/..``).
        content: The text content to write.

    Returns:
        A success message or an error description.
    """
    # Resolve to absolute path
    resolved = os.path.realpath(os.path.abspath(path))

    # Phase 1 security: path whitelist check
    allowed, reason = is_write_allowed(resolved)
    if not allowed:
        return f"[blocked] {reason}"

    # Protect certain files
    if _is_protected(resolved):
        return f"[error] Refusing to overwrite protected file: {os.path.basename(resolved)}"

    # Create parent directories
    parent = os.path.dirname(resolved)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as e:
        return f"[error] Could not create parent directories: {e}"

    # Write the file
    try:
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return f"[error] Could not write file: {e}"

    return f"[ok] Wrote {len(content)} bytes to {resolved}"
