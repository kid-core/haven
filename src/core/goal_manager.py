"""P4d-A — Goal manager with JSON persistence.

Goals represent user-defined objectives that Haven tracks across
sessions.  The GoalManager handles CRUD, persistence, and can be
queried by the P4a prompt assembler to inject active goals into
the system prompt.

Storage: data/long_term_memory/goals.json
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from core.paths import ltm_dir

logger = logging.getLogger(__name__)

DEFAULT_GOALS_FILE = ltm_dir() / "goals.json"
GoalStatus = Literal["active", "completed", "cancelled"]


@dataclass
class Goal:
    """A user-defined objective tracked by Haven."""

    id: str
    title: str
    description: str = ""
    status: GoalStatus = "active"
    created_at: float = 0.0
    completed_at: float | None = None
    progress: float = 0.0  # 0.0–1.0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Goal:
        return cls(
            id=d["id"],
            title=d["title"],
            description=d.get("description", ""),
            status=d.get("status", "active"),
            created_at=d.get("created_at", 0.0),
            completed_at=d.get("completed_at"),
            progress=d.get("progress", 0.0),
            tags=d.get("tags", []),
        )


class GoalManager:
    """CRUD manager for user goals backed by a JSON file.

    Thread-unsafe — assume single-asyncio-event-loop usage.
    """

    def __init__(self, storage_path: Path | str = DEFAULT_GOALS_FILE) -> None:
        self._path = Path(storage_path)
        self._goals: dict[str, Goal] = {}
        self._load()

    # ── Persistence ─────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                self._goals = {
                    gid: Goal.from_dict(g) for gid, g in raw.items()
                }
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("Failed to load goals: %s — starting fresh", exc)
                self._goals = {}
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {gid: g.to_dict() for gid, g in self._goals.items()}
        self._path.write_text(json.dumps(data, indent=2))

    # ── CRUD ────────────────────────────────────────────────────────

    def create(
        self,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> Goal:
        """Create a new active goal."""
        goal = Goal(
            id=uuid.uuid4().hex[:10],
            title=title.strip(),
            description=description.strip(),
            status="active",
            created_at=time.time(),
            progress=0.0,
            tags=tags or [],
        )
        self._goals[goal.id] = goal
        self._save()
        logger.info("Goal created: %s (%s)", goal.id, goal.title)
        return goal

    def complete(self, goal_id: str) -> Goal | None:
        """Mark a goal as completed."""
        goal = self._goals.get(goal_id)
        if goal is None or goal.status != "active":
            return None
        goal.status = "completed"
        goal.completed_at = time.time()
        goal.progress = 1.0
        self._save()
        return goal

    def cancel(self, goal_id: str) -> Goal | None:
        """Cancel an active goal."""
        goal = self._goals.get(goal_id)
        if goal is None or goal.status != "active":
            return None
        goal.status = "cancelled"
        self._save()
        return goal

    def get(self, goal_id: str) -> Goal | None:
        return self._goals.get(goal_id)

    def list_active(self) -> list[Goal]:
        return [g for g in self._goals.values() if g.status == "active"]

    def list_all(self) -> list[Goal]:
        return list(self._goals.values())

    def update_progress(self, goal_id: str, progress: float) -> Goal | None:
        """Set progress (0.0–1.0) for an active goal."""
        goal = self._goals.get(goal_id)
        if goal is None or goal.status != "active":
            return None
        goal.progress = max(0.0, min(1.0, progress))
        self._save()
        return goal

    # ── Queries ─────────────────────────────────────────────────────

    def status_report(self) -> str:
        """Multi-line status report for /goal status."""
        active = self.list_active()
        completed = [g for g in self._goals.values() if g.status == "completed"]
        cancelled = [g for g in self._goals.values() if g.status == "cancelled"]

        lines = ["📋 **Goal Status**"]
        lines.append(f"   Active: {len(active)} | Completed: {len(completed)} | Cancelled: {len(cancelled)}")
        if active:
            lines.append("")
            lines.append("**Active Goals:**")
            for g in active:
                bar = _progress_bar(g.progress)
                lines.append(f"  `{g.id}` {g.title} {bar}")
                if g.description:
                    lines.append(f"     {g.description[:100]}")
        if completed:
            lines.append("")
            lines.append("**Recently Completed:**")
            for g in completed[-3:]:
                lines.append(f"  ✅ `{g.id}` {g.title}")
        return "\n".join(lines)

    def inject_into_context(self) -> str:
        """Return a prompt fragment listing active goals (or '')."""
        active = self.list_active()
        if not active:
            return ""
        lines = ["[Active Goals]"]
        for g in active:
            bar = _progress_bar(g.progress)
            lines.append(f"- [{g.id}] {g.title} {bar}")
            if g.description:
                lines.append(f"  {g.description[:120]}")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._goals)


def _progress_bar(progress: float, width: int = 10) -> str:
    """Render a text progress bar: ``█████░░░░░ 50%``"""
    clamped = max(0.0, min(1.0, progress))
    filled = round(clamped * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = round(clamped * 100)
    return f"{bar} {pct}%"
