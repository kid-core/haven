"""
Task Complexity Estimator — heuristic turn-count estimation via char count.

SRP: single-purpose module for task-complexity estimation.
"""

from __future__ import annotations

from typing import ClassVar


class TaskComplexityEstimator:
    """Estimate the number of turns a task might require.

    Uses character-count heuristic — language-neutral, works for
    Chinese (no spaces between words) and English.
    """

    MIN_TURNS: ClassVar[int] = 15
    MAX_TURNS: ClassVar[int] = 60
    CHARS_PER_TURN: ClassVar[int] = 20

    def __init__(self) -> None:
        self._history: list[tuple[str, int]] = []

    def estimate_turns(self, goal: str, file_count: int = 0) -> int:
        """Estimate turns from character count. Language-neutral, 8-20 turns.

        ``file_count`` is accepted for backward compatibility but not used
        in the character-length heuristic.
        """
        char_count = len(goal.strip())
        base = min(max(char_count // self.CHARS_PER_TURN, self.MIN_TURNS), self.MAX_TURNS)
        # Adaptive adjustment from history (weighted average, capped at ±25%)
        if self._history:
            avg_actual = sum(a for _, a in self._history[-20:]) / min(len(self._history), 20)
            avg_estimated = (
                sum(
                    min(max(len(g.strip()) // self.CHARS_PER_TURN, self.MIN_TURNS), self.MAX_TURNS)
                    for g, _ in self._history[-20:]
                )
                / min(len(self._history), 20)
            )
            if avg_estimated > 0:
                ratio = avg_actual / avg_estimated
                ratio = max(0.75, min(1.25, ratio))  # clamp ±25%
                base = max(self.MIN_TURNS, min(self.MAX_TURNS, int(base * ratio)))
        return base

    def add_history(self, goal: str, actual_turns: int) -> None:
        """Record actual turn count for adaptive estimation."""
        self._history.append((goal, actual_turns))
