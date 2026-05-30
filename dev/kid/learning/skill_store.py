"""Skill store — persistent storage for learned skills (Phase 3).

Supports draft/active/deprecated lifecycle with versioning and audit trail.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "skills_store"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class SkillState:
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


@dataclass
class SkillChange:
    """Single entry in a skill's audit trail."""
    timestamp: float
    action: str          # "created", "updated", "approved", "deprecated", "refined"
    detail: str = ""
    previous: str = ""   # snapshot of content before change


@dataclass
class StoredSkill:
    """A learned skill stored in the skill store."""

    id: str
    name: str
    description: str
    state: str = SkillState.DRAFT
    version: int = 1
    content: str = ""           # prompt-injection text (what gets added to context)
    entry_pattern: str = ""     # "trigger keyword or situation"
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    usage_count: int = 0
    success_count: int = 0
    history: list[SkillChange] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count

    def to_context_block(self) -> str:
        """Render as a context block for injection into system prompt."""
        lines = [
            f"[Learned Skill: {self.name}]",
            f"Trigger: {self.entry_pattern}",
            self.content,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# SkillStore
# ---------------------------------------------------------------------------

class SkillStore:
    """JSON file-backed store for learned skills.

    Safety: skills are created in DRAFT state and must be explicitly
    approved (state → ACTIVE) before being loaded into context.

    Usage::

        store = SkillStore()
        draft = store.create(
            name="prefer-short-replies",
            description="Cris prefers short replies",
            entry_pattern="any user message",
            content="Keep responses under 3 sentences unless asked otherwise.",
            tags=["style", "preference"],
        )
        # ... Cris reviews via approval command ...
        store.approve(draft.id)
    """

    def __init__(self, storage_dir: Path = DEFAULT_SKILL_DIR) -> None:
        self._dir = storage_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "skills.json"
        self._skills: dict[str, StoredSkill] = {}
        self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        description: str,
        entry_pattern: str,
        content: str,
        tags: list[str] | None = None,
    ) -> StoredSkill:
        """Create a new skill in DRAFT state."""
        now = time.time()
        sid = uuid.uuid4().hex[:10]
        skill = StoredSkill(
            id=sid,
            name=name,
            description=description,
            state=SkillState.DRAFT,
            entry_pattern=entry_pattern,
            content=content,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            history=[
                SkillChange(timestamp=now, action="created", detail="Auto-generated draft")
            ],
        )
        self._skills[sid] = skill
        self._save()
        logger.info("Skill draft created: %s (%s)", name, sid)
        return skill

    def get(self, skill_id: str) -> StoredSkill | None:
        return self._skills.get(skill_id)

    def update_content(self, skill_id: str, content: str, description: str | None = None) -> StoredSkill | None:
        """Update a skill's content (creates new version, records in history)."""
        skill = self._skills.get(skill_id)
        if not skill:
            return None
        now = time.time()
        skill.history.append(SkillChange(
            timestamp=now, action="updated",
            detail=description or "Updated content",
            previous=skill.content[:200],
        ))
        skill.content = content
        skill.version += 1
        skill.updated_at = now
        self._save()
        return skill

    def approve(self, skill_id: str) -> bool:
        """Promote a skill from DRAFT to ACTIVE."""
        skill = self._skills.get(skill_id)
        if not skill or skill.state != SkillState.DRAFT:
            return False
        now = time.time()
        skill.state = SkillState.ACTIVE
        skill.updated_at = now
        skill.history.append(SkillChange(timestamp=now, action="approved"))
        self._save()
        logger.info("Skill approved: %s", skill.name)
        return True

    def deprecate(self, skill_id: str, reason: str = "") -> bool:
        """Mark a skill as deprecated."""
        skill = self._skills.get(skill_id)
        if not skill:
            return False
        now = time.time()
        skill.state = SkillState.DEPRECATED
        skill.updated_at = now
        skill.history.append(SkillChange(timestamp=now, action="deprecated", detail=reason))
        self._save()
        return True

    def remove(self, skill_id: str) -> bool:
        """Permanently delete a skill."""
        if skill_id not in self._skills:
            return False
        del self._skills[skill_id]
        self._save()
        return True

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_active(self) -> list[StoredSkill]:
        """Return all ACTIVE skills (for context injection)."""
        return [s for s in self._skills.values() if s.state == SkillState.ACTIVE]

    def get_drafts(self) -> list[StoredSkill]:
        """Return all DRAFT skills pending approval."""
        return [s for s in self._skills.values() if s.state == SkillState.DRAFT]

    def get_by_tag(self, tag: str) -> list[StoredSkill]:
        return [s for s in self._skills.values() if tag in s.tags]

    def all(self) -> list[StoredSkill]:
        return list(self._skills.values())

    def record_usage(self, skill_id: str, success: bool) -> None:
        """Mark a skill as used (increment counters)."""
        skill = self._skills.get(skill_id)
        if not skill:
            return
        skill.usage_count += 1
        if success:
            skill.success_count += 1
        self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for item in data:
                sid = item["id"]
                history = [
                    SkillChange(**h) for h in item.get("history", [])
                ]
                self._skills[sid] = StoredSkill(
                    id=sid,
                    name=item["name"],
                    description=item.get("description", ""),
                    state=item.get("state", SkillState.DRAFT),
                    version=item.get("version", 1),
                    content=item.get("content", ""),
                    entry_pattern=item.get("entry_pattern", ""),
                    tags=item.get("tags", []),
                    created_at=item.get("created_at", 0),
                    updated_at=item.get("updated_at", 0),
                    usage_count=item.get("usage_count", 0),
                    success_count=item.get("success_count", 0),
                    history=history,
                )
            logger.info("Loaded %d skills from %s", len(self._skills), self._path)
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning("Could not load skills: %s", exc)

    def _save(self) -> None:
        data = [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "state": s.state,
                "version": s.version,
                "content": s.content,
                "entry_pattern": s.entry_pattern,
                "tags": s.tags,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "usage_count": s.usage_count,
                "success_count": s.success_count,
                "history": [vars(h) for h in s.history],
            }
            for s in self._skills.values()
        ]
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def __len__(self) -> int:
        return len(self._skills)
