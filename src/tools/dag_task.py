"""DAG task tool — structured multi-node task execution (Phase 3).

Wraps the TaskDAG engine behind a COLLAB-category tool.
For ≤ 3 nodes, executes inline via spawn_child.
For > 3 nodes, runs the full DAG engine with concurrent layers.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from core.categories import ToolCategory
from core.policy import ToolPolicy
from core.tool_decorator import tool

if TYPE_CHECKING:
    from tools.spawn_child import SpawnManager

logger = logging.getLogger(__name__)

_spawn_manager: SpawnManager | None = None


def set_spawn_manager(mgr: SpawnManager) -> None:
    """Inject the spawn manager (called by Router on init)."""
    global _spawn_manager
    _spawn_manager = mgr


@tool(
    category=ToolCategory.COLLAB,
    policy=ToolPolicy(timeout=3600.0, rate_limit=60.0),
)
async def dag_task(dag_json: str) -> str:
    """Execute a structured task DAG with parallel or sequential child agents.

    Provide a JSON DAG definition with nodes that have dependencies.
    Independent nodes run concurrently.  Nodes that timeout are auto-retried.

    Schema:
    {
      "description": "Optional overall description",
      "nodes": [
        {
          "id": "1",
          "task": "Do step one",
          "depends_on": [],
          "timeout": 300,
          "max_retries": 2,
          "acceptance_criteria": "pytest passes",
          "output_files": ["src/x.py"],
          "output_files_exclusive": true
        }
      ]
    }

    Args:
        dag_json: JSON string following the DAG schema above.

    Returns:
        DAG execution summary with per-node results.
    """
    if _spawn_manager is None:
        return "[dag error] Spawn manager not wired."

    # Parse and validate
    try:
        dag_dict = json.loads(dag_json)
    except json.JSONDecodeError as e:
        return f"[dag error] Invalid JSON: {e}"

    from core.task_dag import (
        DAGValidationError,
        NodeStatus,
        execute,
        validate,
    )

    try:
        dag = validate(dag_dict)
    except DAGValidationError as e:
        return f"[dag error] Schema validation failed: {e}"

    # Spawn adapter — wraps SpawnManager.spawn to match DAG engine's SpawnFn
    async def _spawn(task: str, timeout: float, max_turns: int, max_retries: int) -> str:
        return await _spawn_manager.spawn(
            task=task,
            timeout=timeout,
            max_turns=max_turns,
            max_retries=max_retries,
        )

    logger.info("DAG task: %d nodes → %s", len(dag.nodes), dag.description or "(no desc)")
    result = await execute(dag, _spawn)

    return result.summary
