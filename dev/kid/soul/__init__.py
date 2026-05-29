"""Soul — identity, system prompts, and memory persistence."""

from .identity import build_system_prompt
from .memory import SessionStore

__all__ = ["build_system_prompt", "SessionStore"]
