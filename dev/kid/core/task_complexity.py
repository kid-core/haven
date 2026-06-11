"""
Task Complexity Estimator — heuristic turn-count estimation via dict dispatch.

SRP: single-purpose module for task-complexity estimation.
"""

from __future__ import annotations

import math
from typing import ClassVar


class TaskComplexityEstimator:
    """Estimate the number of turns a task might require.

    Uses dict dispatch on the first word of the goal.
    """

    VERB_TURN_MAP: ClassVar[dict[str, int]] = {
        "analyze": 3,
        "compare": 3,
        "research": 4,
        "rewrite": 3,
        "debug": 4,
        "implement": 5,
        "migrate": 4,
        "plan": 3,
        "summarize": 2,
        "test": 3,
        "refactor": 4,
        "translate": 2,
    }
    FILE_TURN_PENALTY: ClassVar[int] = 2
    BUFFER_RATIO: ClassVar[float] = 1.5
    DEFAULT_TURNS: ClassVar[int] = 3

    def __init__(self) -> None:
        self._history: list[tuple[str, int]] = []

    def estimate_turns(self, goal: str, file_count: int = 0) -> int:
        """Estimate turns from *goal*'s first word + file penalty + buffer."""
        words = goal.strip().split()
        first_word = words[0].lower() if words else ""
        base = self.VERB_TURN_MAP.get(first_word, self.DEFAULT_TURNS)
        base += file_count * self.FILE_TURN_PENALTY
        return math.ceil(base * self.BUFFER_RATIO)

    def add_history(self, goal: str, actual_turns: int) -> None:
        """Record actual turn count for later analysis."""
        self._history.append((goal, actual_turns))
