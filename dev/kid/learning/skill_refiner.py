"""Skill refiner — tracks usage effectiveness and adjusts skills (Phase 3b).

Auto-adjusts skill content based on success/failure patterns.
Conservative: only deprecates clearly broken skills; never auto-activates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from learning.skill_store import SkillStore

logger = logging.getLogger(__name__)

# Minimum uses before refinement triggers
MIN_USES_FOR_REFINE = 5

# Success rate thresholds
DEPRECATE_THRESHOLD = 0.2   # deprecate if < 20% success
WARN_THRESHOLD = 0.5        # warn if < 50% success


@dataclass
class SkillRefiner:
    """Monitors Active skills and adjusts based on real-world results.

    Conservative principles:
    - Only deprecates or warns; never auto-creates or auto-approves
    - Requires MIN_USES_FOR_REFINE before making any judgment
    - All changes are logged to the skill's audit trail
    """

    store: SkillStore

    def evaluate(self) -> list[str]:
        """Evaluate all Active skills and return warnings.

        Actions taken:
        - Deprecate skills with consistently low success rate
        - Warn about borderline skills (returned in result list)
        """
        warnings: list[str] = []

        for skill in self.store.get_active():
            if skill.usage_count < MIN_USES_FOR_REFINE:
                continue

            rate = skill.success_rate

            if rate < DEPRECATE_THRESHOLD:
                reason = (
                    f"Auto-deprecated: success rate {rate:.0%} "
                    f"({skill.success_count}/{skill.usage_count}) "
                    f"over {skill.usage_count} uses — below {DEPRECATE_THRESHOLD:.0%} threshold"
                )
                self.store.deprecate(skill.id, reason)
                logger.warning("Skill %s deprecated: %s", skill.name, reason)
                warnings.append(f"DEPRECATED: {skill.name} — {reason}")

            elif rate < WARN_THRESHOLD:
                msg = (
                    f"WARNING: {skill.name} has low success rate "
                    f"({rate:.0%}, {skill.success_count}/{skill.usage_count})"
                )
                logger.info(msg)
                warnings.append(msg)

        return warnings

    def get_health_report(self) -> str:
        """Return a markdown-formatted health report for all skills."""
        lines = ["## Skill Health Report", ""]
        for skill in self.store.all():
            state_flag = "🟢" if skill.state == "active" else "🟡" if skill.state == "draft" else "⚫"
            rate_str = f"{skill.success_rate:.0%}" if skill.usage_count > 0 else "N/A"
            lines.append(
                f"{state_flag} **{skill.name}** (v{skill.version}) — "
                f"used {skill.usage_count}×, success {rate_str}, state={skill.state}"
            )
        return "\n".join(lines) if len(lines) > 2 else "No skills stored."
