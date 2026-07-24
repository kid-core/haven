"""Conversation summariser — compresses chat history into structured summaries.

Phase 2a: rule-based extraction + keyword tagging.  Phase 2b will add LLM-based summarisation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionSummary:
    """Compressed summary of a conversation session."""

    session_id: str
    brief: str = ""                   # 1-2 sentence overview
    key_topics: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    facts_learned: list[str] = field(default_factory=list)
    preferences_mentioned: list[str] = field(default_factory=list)
    message_count: int = 0
    tags: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        """Render summary as a compact natural-language paragraph."""
        parts: list[str] = []

        if self.brief:
            parts.append(self.brief)

        if self.key_topics:
            parts.append(f"Topics: {', '.join(self.key_topics)}")

        if self.decisions:
            parts.append(f"Decisions: {'; '.join(self.decisions)}")

        if self.facts_learned:
            parts.append(f"Facts: {'; '.join(self.facts_learned)}")

        if self.preferences_mentioned:
            parts.append(f"Preferences: {'; '.join(self.preferences_mentioned)}")

        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Keywords / patterns for rule-based extraction
# ---------------------------------------------------------------------------

DECISION_PATTERNS = [
    (r"(?:decided|決定|決定要|確定|決定用|選擇)\s+(.+?)(?:[。，.!]|$)", "zh"),
    (r"(?:I|we)\s*(?:'ve | have | )?decided(?:\s+to)?\s+(.+?)(?:[.!]|$)", "en"),
    (r"(?:let'?s|we should|we will)\s+(.+?)(?:[.!]|$)", "en"),
]

PREFERENCE_PATTERNS = [
    (r"(?:喜歡|偏好|比較喜歡|prefer)\s+(.+?)(?:[。，.!]|$)", "zh"),
    (r"(?:I|they|he|she)\s+(?:prefer|like|love|hate)\s+(.+?)(?:[.!]|$)", "en"),
]

FACT_PATTERNS = [
    (r"(?:記得|remember|note|記住)\s+(.+?)(?:[。，.!]|$)", "mixed"),
]

TOPIC_KEYWORDS: dict[str, str] = {
    # English
    "python": "coding", "javascript": "coding", "rust": "coding",
    "docker": "infra", "server": "infra", "deploy": "infra",
    "memory": "memory", "storage": "infra", "database": "infra",
    "ai": "ai", "llm": "ai", "model": "ai", "prompt": "ai",
    "discord": "platform", "telegram": "platform", "api": "api",
    "tool": "tools", "config": "config", "identity": "identity",
    "security": "security", "backup": "infra", "test": "testing",
    # Chinese
    "記憶": "memory", "部署": "infra", "模型": "ai",
    "工具": "tools", "配置": "config", "安全": "security",
    "測試": "testing", "備份": "infra", "身份": "identity",
}


def summarize_session(
    session_id: str,
    messages: list[dict[str, Any]],
) -> SessionSummary:
    """Extract a structured summary from raw conversation messages.

    Works with raw message dicts (role + content), no LLM needed.
    """
    # Collect all text
    texts: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            texts.append(content)

    combined = "\n".join(texts) if texts else ""

    summary = SessionSummary(
        session_id=session_id,
        message_count=len(messages),
    )

    if not texts:
        summary.brief = "(empty session)"
        return summary

    # Brief: first + last significant messages, truncated
    first_text = texts[0][:150].strip()
    last_text = texts[-1][:150].strip() if len(texts) > 1 else ""
    if last_text and last_text != first_text:
        summary.brief = f"Started with: {first_text}… Ended with: {last_text}…"
    else:
        summary.brief = f"Conversation: {first_text}…"

    # Extract patterns
    summary.decisions = _extract_patterns(combined, DECISION_PATTERNS)
    summary.preferences_mentioned = _extract_patterns(combined, PREFERENCE_PATTERNS)
    summary.facts_learned = _extract_patterns(combined, FACT_PATTERNS)

    # Extract topics from keywords
    summary.key_topics = _extract_topics(combined)

    # Tags from topics
    summary.tags = sorted({
        TOPIC_KEYWORDS.get(t.lower(), "general") for t in summary.key_topics
    })

    return summary


def _extract_patterns(text: str, patterns: list[tuple[str, str]]) -> list[str]:
    """Apply regex patterns and return extracted captures."""
    results: list[str] = []
    seen: set[str] = set()
    for pattern, _lang in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            capture = match.group(1).strip().rstrip(".,;!。，、；！").strip()
            if capture and capture not in seen and len(capture) > 1:
                results.append(capture)
                seen.add(capture)
    return results


def _extract_topics(text: str) -> list[str]:
    """Extract topic keywords from text."""
    lower = text.lower()
    topics: list[str] = []
    seen: set[str] = set()
    for keyword, _topic in TOPIC_KEYWORDS.items():
        if keyword in lower and keyword not in seen:
            topics.append(keyword)
            seen.add(keyword)
    return topics[:10]  # max 10 topics
