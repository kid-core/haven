"""Pattern tracker + skill factory — detect learnable behaviors and generate drafts.

Phase 3a: monitors tool calls for repeated patterns and suggests draft skills.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from core.categories import ToolCategory
from learning.skill_store import SkillStore, StoredSkill

logger = logging.getLogger(__name__)

# Minimum occurrences before a pattern triggers a skill draft
MIN_PATTERN_OCCURRENCES = 3

# Tools / categories that are NEVER auto-learned
BLOCKED_CATEGORIES = {ToolCategory.SYSTEM}
BLOCKED_TOOLS: set[str] = set()  # can add specific tool names

# Sensitive content patterns that block skill generation
SENSITIVE_PATTERNS = [
    r"(?:api[_-]?key|password|secret|token)\s*[:=]\s*\S+",
    r"sk-[A-Za-z0-9]{20,}",
    r"(?:BEGIN|PRIVATE)\s+(?:RSA|DSA|EC|OPENSSH)?\s*(?:PRIVATE)?\s*KEY",
]


@dataclass
class ToolCallRecord:
    """A single recorded tool invocation."""
    tool_name: str
    arguments: dict[str, Any]
    category: str
    success: bool
    timestamp: float
    session_id: str
    response_preview: str = ""


@dataclass
class PatternMatch:
    """A detected repeated pattern."""
    tool_name: str
    recurring_keys: list[str]          # argument keys that repeat across calls
    sample_values: dict[str, Any]      # typical values
    occurrences: int
    recent_session_ids: list[str]
    description: str = ""


@dataclass
class SkillFactory:
    """Observes tool calls and generates skill drafts from patterns.

    Usage::

        factory = SkillFactory(store)
        factory.observe(tool_name="write_file", arguments={"path": "...", "content": "..."},
                        category="FILES", success=True, session_id="abc")
        drafts = factory.detect_patterns()
        for draft in drafts:
            factory.generate_skill(draft)
    """

    store: SkillStore
    _records: list[ToolCallRecord] = field(default_factory=list)
    _max_records: int = 500  # keep last N records to avoid memory bloat

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    def observe(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        category: ToolCategory | str,
        success: bool,
        session_id: str,
        response_preview: str = "",
    ) -> None:
        """Record a tool call for pattern analysis."""
        cat_name = category.name if isinstance(category, ToolCategory) else str(category)

        # Skip blocked categories/tools
        if isinstance(category, ToolCategory) and category in BLOCKED_CATEGORIES:
            return
        if tool_name in BLOCKED_TOOLS:
            return

        # Skip if arguments contain sensitive data
        if _contains_sensitive(arguments):
            logger.debug("Skipping sensitive tool call: %s", tool_name)
            return

        record = ToolCallRecord(
            tool_name=tool_name,
            arguments=self._sanitize_arguments(arguments),
            category=cat_name,
            success=success,
            timestamp=time.time(),
            session_id=session_id,
            response_preview=response_preview[:200],
        )
        self._records.append(record)

        # Trim old records
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]

    # ------------------------------------------------------------------
    # Pattern detection
    # ------------------------------------------------------------------

    def detect_patterns(self) -> list[PatternMatch]:
        """Analyze recorded tool calls for repeated patterns.

        Returns patterns that occurred at least MIN_PATTERN_OCCURRENCES times.
        """
        # Group records by tool name
        by_tool: dict[str, list[ToolCallRecord]] = defaultdict(list)
        for r in self._records:
            by_tool[r.tool_name].append(r)

        patterns: list[PatternMatch] = []

        for tool_name, records in by_tool.items():
            if len(records) < MIN_PATTERN_OCCURRENCES:
                continue

            # Find argument keys that consistently appear
            key_counts: dict[str, int] = defaultdict(int)
            for r in records:
                for key in r.arguments:
                    key_counts[key] += 1

            # Keys that appear in ≥80% of calls for this tool
            recurring = [
                k for k, v in key_counts.items()
                if v >= len(records) * 0.8
            ]
            if not recurring:
                continue

            # Sample typical values (from the most recent calls)
            sample = {}
            for key in recurring:
                # Last 3 values for this key
                values = [r.arguments.get(key) for r in records[-3:]]
                # Find the most common value pattern
                str_values = [self._value_summary(v) for v in values if v is not None]
                if str_values:
                    sample[key] = str_values[0]

            sessions = list({r.session_id for r in records[-5:]})

            description = self._describe_pattern(tool_name, recurring, sample)
            patterns.append(PatternMatch(
                tool_name=tool_name,
                recurring_keys=recurring,
                sample_values=sample,
                occurrences=len(records),
                recent_session_ids=sessions,
                description=description,
            ))

        return patterns

    # ------------------------------------------------------------------
    # Skill generation
    # ------------------------------------------------------------------

    def generate_skill(self, pattern: PatternMatch) -> StoredSkill:
        """Create a draft skill from a detected pattern."""
        name = self._make_skill_name(pattern.tool_name, pattern.recurring_keys)
        entry = ", ".join(f"{k}={self._format_value(pattern.sample_values.get(k))}"
                          for k in pattern.recurring_keys)
        entry_pattern = f"Tool: {pattern.tool_name} | Pattern: {entry}"

        lines = [
            f"When calling `{pattern.tool_name}` tool:",
        ]
        for key in pattern.recurring_keys:
            val = pattern.sample_values.get(key)
            if val is not None:
                lines.append(f"- Default {key}: {self._format_value(val)}")

        lines.append(f"\n(Learned from {pattern.occurrences} similar calls across "
                     f"{len(pattern.recent_session_ids)} sessions)")

        content = "\n".join(lines)

        tags = ["auto-generated", pattern.tool_name]
        return self.store.create(
            name=name,
            description=pattern.description,
            entry_pattern=entry_pattern,
            content=content,
            tags=tags,
        )

    def approve_all_drafts(self) -> int:
        """Approve all pending drafts. Returns count approved."""
        count = 0
        for skill in self.store.get_drafts():
            if self.store.approve(skill.id):
                count += 1
        return count

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_arguments(args: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive values from arguments before storing."""
        safe: dict[str, Any] = {}
        for k, v in args.items():
            if isinstance(v, str):
                # Truncate long values, mask paths
                if len(v) > 200:
                    v = v[:200] + "..."
                if any(p in v.lower() for p in ("password", "secret", "token", "api_key")):
                    v = "***REDACTED***"
            elif isinstance(v, (int, float, bool, type(None))):
                pass
            elif isinstance(v, dict):
                v = f"<dict {len(v)} keys>"
            elif isinstance(v, list):
                v = f"<list {len(v)} items>"
            else:
                v = str(v)[:100]
            safe[k] = v
        return safe

    @staticmethod
    def _value_summary(value: Any) -> str:
        """Create a summary representation of a value."""
        if isinstance(value, str):
            return value[:80]
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, dict):
            return f"<{len(value)}-key dict>"
        if isinstance(value, list):
            return f"<{len(value)}-item list>"
        return str(value)[:80]

    @staticmethod
    def _format_value(value: Any) -> str:
        if value is None:
            return "(varies)"
        if isinstance(value, str):
            return f'"{value[:60]}"'
        return str(value)

    @staticmethod
    def _make_skill_name(tool_name: str, keys: list[str]) -> str:
        """Generate a readable skill name."""
        key_part = "-".join(sorted(keys)[:3])
        return f"{tool_name}-{key_part}"

    @staticmethod
    def _describe_pattern(tool_name: str, keys: list[str], sample: dict) -> str:
        """Generate a human-readable pattern description."""
        key_desc = ", ".join(keys[:5])
        example = ", ".join(f"{k}={SkillFactory._format_value(sample.get(k))}"
                           for k in keys[:3])
        return f"Repeated calls to `{tool_name}` with keys [{key_desc}]. Example: {example}"


# ---------------------------------------------------------------------------
# Safety utilities
# ---------------------------------------------------------------------------

def _contains_sensitive(arguments: dict[str, Any]) -> bool:
    """Check if arguments contain sensitive data patterns."""
    for _, v in arguments.items():
        if isinstance(v, str):
            for pattern in SENSITIVE_PATTERNS:
                if re.search(pattern, v, re.IGNORECASE):
                    return True
    return False


def inject_active_skills(skill_store: SkillStore, system_prompt: str) -> str:
    """Append all ACTIVE learned skills to the system prompt."""
    active = skill_store.get_active()
    if not active:
        return system_prompt

    blocks = ["\n[Learned Skills (auto-generated, approved)]"]
    for skill in active:
        blocks.append(f"\n### {skill.name}")
        blocks.append(skill.content)
        blocks.append(f"(version {skill.version}, success rate: {skill.success_rate:.0%})")

    return system_prompt + "\n".join(blocks)
