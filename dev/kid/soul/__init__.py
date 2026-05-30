"""Soul — identity, system prompts, and memory persistence."""

from .identity import build_system_prompt
from .memory import LongTermMemory, MemoryIndex, SessionStore, summarize_session

__all__ = [
    "build_system_prompt",
    "LongTermMemory",
    "MemoryIndex",
    "SessionStore",
    "summarize_session",
]
