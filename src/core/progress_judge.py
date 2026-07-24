"""Progress heartbeat judge — lost-agent detection (Phase 2).

Dual-track judging:
  1. Rule-based (zero-cost, runs first):
     - Self-assessment < 20 chars → HOLLOW
     - Contains hollow keywords → HOLLOW
  2. LLM judge (fallback, runs only if rule-based passes):
     - Compares two consecutive self-assessments for semantic similarity
     - Similarity > threshold → HOLLOW

Design:
  - First 10 turns exempt from heartbeat
  - After turn 10, forced self-assessment every 5 turns
  - Two consecutive HOLLOW verdicts → trigger auto-resume
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────

TURN_EXEMPT = 10       # First N turns skip heartbeat entirely
HEARTBEAT_EVERY = 5    # After TURN_EXEMPT, check every N turns
SIMILARITY_THRESHOLD = 0.75  # Above this → too similar → HOLLOW

HOLLOW_KEYWORDS: set[str] = {
    "持續努力", "進行中", "調整中", "測試中", "嘗試中", "處理中",
    "努力中", "研究中", "分析中", "修復中", "檢查中",
    "still working", "in progress", "working on it", "trying",
    "continuing",
}


# ── Rule-based fallback ─────────────────────────────────────────────────

def is_hollow_rule(text: str) -> tuple[bool, str]:
    """Check if a self-assessment is hollow via zero-cost rules.

    Returns (is_hollow, reason).
    """
    stripped = text.strip()

    # Empty or too short
    if len(stripped) < 20:
        return True, f"Self-assessment too short ({len(stripped)} chars)"

    # Hollow keywords
    lower = stripped.lower()
    for kw in HOLLOW_KEYWORDS:
        if kw in lower:
            return True, f"Contains hollow keyword: '{kw}'"

    return False, ""


# ── Similarity-based judge ──────────────────────────────────────────────

def _simple_similarity(a: str, b: str) -> float:
    """Compute a simple word-overlap similarity (zero-cost, no embeddings).

    Jaccard similarity on word sets, weighted by word length.
    """
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a and not words_b:
        return 1.0
    intersection = words_a & words_b
    union = words_a | words_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


def judge_similarity(prev: str, current: str) -> tuple[bool, float]:
    """Compare two consecutive self-assessments for semantic similarity.

    Returns (is_hollow, similarity_score).
    Uses simple word overlap first (zero cost).  A proper LLM judge
    would be added here for more nuanced comparison.
    """
    score = _simple_similarity(prev, current)
    is_hollow = score >= SIMILARITY_THRESHOLD
    return is_hollow, score


# ── Combined judge ──────────────────────────────────────────────────────

def judge(prev_assessment: str, current: str) -> tuple[bool, str]:
    """Full dual-track judgment pipeline.

    1. Rule-based check on current assessment
    2. If passes, similarity check against previous assessment
    3. Returns (is_hollow, verdict_reason)
    """
    # Rule-based first (zero cost)
    hollow, reason = is_hollow_rule(current)
    if hollow:
        return True, f"[rule] {reason}"

    # Similarity to previous (only if we have a previous)
    if prev_assessment:
        hollow, score = judge_similarity(prev_assessment, current)
        if hollow:
            return True, f"[similarity] score={score:.2f} >= {SIMILARITY_THRESHOLD}"

    return False, "ok"


# ── Heartbeat tracker ───────────────────────────────────────────────────

class HeartbeatTracker:
    """Tracks heartbeat state across turns within a session.

    Usage (in agent loop):
        tracker = HeartbeatTracker()
        for turn in range(max_turns):
            prompt = tracker.check(turn)
            if prompt:
                # inject prompt into system message
                ...
            ...
            response = await agent.process(...)
            lost = tracker.record(response)
            if lost:
                # trigger auto-resume
                ...
    """

    def __init__(self) -> None:
        self._turn_count = 0
        self._prev_assessment = ""
        self._hollow_streak = 0

    def should_check(self, turn: int) -> bool:
        """Should we inject a heartbeat prompt at this turn?"""
        if turn < TURN_EXEMPT:
            return False
        return (turn - TURN_EXEMPT) % HEARTBEAT_EVERY == 0

    def heartbeat_prompt(self) -> str:
        """Return the prompt to inject for self-assessment."""
        return (
            "\n[PROGRESS HEARTBEAT]\n"
            "In ONE sentence, briefly state: (1) what you completed so far, "
            "(2) what your next step is.\n"
            "Keep it specific.  Do NOT say 'still working' or 'continuing'.\n"
            "Format: [DONE: ...] [NEXT: ...]"
        )

    def record(self, response: str, turn: int) -> tuple[bool, str]:
        """Record the agent's self-assessment and judge it.

        Returns (triggered, reason).  triggered=True means the
        heartbeat detected a lost agent (2 consecutive hollow).
        """
        if not response.strip():
            return False, ""

        hollow, verdict = judge(self._prev_assessment, response)
        self._turn_count = turn

        if hollow:
            self._hollow_streak += 1
            self._prev_assessment = response
            if self._hollow_streak >= 2:
                logger.warning(
                    "Heartbeat triggered: hollow streak=%d verdict=%s",
                    self._hollow_streak, verdict,
                )
                return True, f"Hollow streak {self._hollow_streak}: {verdict}"
            return False, f"Warning: {verdict} (streak={self._hollow_streak})"

        # Non-hollow → reset streak
        self._hollow_streak = 0
        self._prev_assessment = response
        return False, "ok"
