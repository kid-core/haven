"""Learning subsystem — self-improvement via pattern detection and skill drafts."""

from learning.skill_factory import PatternMatch, SkillFactory, inject_active_skills
from learning.skill_refiner import SkillRefiner
from learning.skill_store import SkillChange, SkillState, SkillStore, StoredSkill

__all__ = [
    "SkillChange",
    "SkillFactory",
    "SkillRefiner",
    "SkillState",
    "SkillStore",
    "StoredSkill",
    "PatternMatch",
    "inject_active_skills",
]
