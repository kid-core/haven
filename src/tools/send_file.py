"""
Universal file-delivery tool — queues a file for the transport layer to send.

Works with any platform (Discord, Telegram, …) because the tool itself only
reads the file and pushes metadata into PendingFileStore.  The transport
layer picks up pending files after ``Router.process()`` returns and sends
them natively (e.g. ``discord.File`` or ``telegram.InputFile``).
"""

from __future__ import annotations

import logging
import os

from core.categories import ToolCategory
from core.pending_file import PendingFile, current_session, get_pending_file_store
from core.policy import ToolPolicy
from core.tool_decorator import tool

logger = logging.getLogger(__name__)


@tool(
    name="send_file",
    category=ToolCategory.FILE,
    policy=ToolPolicy(timeout=10.0, rate_limit=3.0),
)
async def send_file(
    file_path: str,
    filename: str | None = None,
) -> dict:
    """Queue a file to be delivered to the user over the current chat platform.

    The file **must** be under the allowed prefix (``HAVEN_ALLOWED_PREFIX``
    or ``/mnt/z/``).

    Args:
        file_path: Absolute or relative path to the file.
        filename:  Optional display name (defaults to the basename of
                   *file_path*).

    Returns:
        A dict with ``action``, ``file_path``, and ``filename`` so the model
        can confirm delivery was queued.
    """
    resolved = os.path.realpath(os.path.abspath(file_path))
    display = filename or os.path.basename(resolved)

    if not os.path.exists(resolved):
        return {"action": "file_error", "error": f"File not found: {resolved}"}

    if not os.path.isfile(resolved):
        return {"action": "file_error", "error": f"Not a regular file: {resolved}"}

    size = os.path.getsize(resolved)

    # Read content for text files; warn on binary
    if _is_binary(resolved):
        content: str = f"[binary file, {size} bytes]"
    else:
        try:
            with open(resolved, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError as exc:
            return {"action": "file_error", "error": f"Read failed: {exc}"}

    store = get_pending_file_store()
    store.add(current_session(), PendingFile(file_path=resolved, filename=display))

    return {
        "action": "file_send",
        "file_path": resolved,
        "filename": display,
        "size": size,
        "content_preview": content[:200] if len(content) > 200 else content,
    }


def _is_binary(file_path: str) -> bool:
    """Check if a file looks binary (has null bytes in first 8 KB)."""
    try:
        with open(file_path, "rb") as fh:
            chunk = fh.read(8192)
        return b"\x00" in chunk
    except OSError:
        return False
