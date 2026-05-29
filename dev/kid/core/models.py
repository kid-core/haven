"""Pydantic v2 models for structured data exchange."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ProviderResponse(BaseModel):
    """Normalised response from an LLM provider."""

    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    reasoning_content: str | None = None


class ToolResult(BaseModel):
    """OpenAI-compatible tool result message."""

    role: str = "tool"
    tool_call_id: str
    content: str
