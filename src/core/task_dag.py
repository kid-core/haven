"""Task DAG schema, validator, and execution engine (Phase 0 + Phase 3).

Phase 0: Schema definition and validation.
Phase 3: Execution engine with topological sort, concurrent spawn,
         output file isolation, and partial success handling.
"""

from __future__ import annotations

import asyncio

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# ── Schema: DAG Node ────────────────────────────────────────────────────

@dataclass
class DAGNode:
    """A single node in a task DAG.

    Fields:
        id:                   Unique node identifier within this DAG.
        task:                 Task description for this node.
        depends_on:           List of node IDs that must complete first.
        timeout:              Max seconds for this node (default 300).
        max_retries:          Per-node retry limit (default 2).
        acceptance_criteria:  Verifiable completion condition
                              (e.g. "pytest src/tests/test_x.py passes").
        output_files:         List of file paths this node is expected to
                              produce or modify.
        output_files_exclusive: If True, no other concurrent node may write
                              to the same files.
    """
    id: str
    task: str
    depends_on: list[str] = field(default_factory=list)
    timeout: int = 300
    max_retries: int = 2
    acceptance_criteria: str = ""
    output_files: list[str] = field(default_factory=list)
    output_files_exclusive: bool = False


# ── Schema: DAG ─────────────────────────────────────────────────────────

@dataclass
class TaskDAG:
    """A complete task dependency graph.

    Fields:
        nodes:       Ordered list of DAGNode definitions.
        description: Human-readable description of the overall task.
    """
    nodes: list[DAGNode] = field(default_factory=list)
    description: str = ""


# ── Validation ──────────────────────────────────────────────────────────

class DAGValidationError(ValueError):
    """Raised when a DAG schema fails validation."""
    pass


def _check_node(raw: dict[str, Any], index: int) -> DAGNode:
    """Validate and parse a single node dict."""
    node_id = raw.get("id")
    if not isinstance(node_id, str) or not node_id:
        raise DAGValidationError(f"Node [{index}]: 'id' must be a non-empty string")

    task = raw.get("task")
    if not isinstance(task, str) or not task:
        raise DAGValidationError(f"Node '{node_id}': 'task' must be a non-empty string")

    depends_on = raw.get("depends_on", [])
    if not isinstance(depends_on, list):
        raise DAGValidationError(f"Node '{node_id}': 'depends_on' must be a list")
    for j, dep in enumerate(depends_on):
        if not isinstance(dep, str):
            raise DAGValidationError(f"Node '{node_id}': 'depends_on[{j}]' must be a string")

    timeout = raw.get("timeout", 300)
    if not isinstance(timeout, int) or timeout < 1:
        raise DAGValidationError(f"Node '{node_id}': 'timeout' must be a positive int")

    max_retries = raw.get("max_retries", 2)
    if not isinstance(max_retries, int) or max_retries < 0:
        raise DAGValidationError(f"Node '{node_id}': 'max_retries' must be >= 0")

    acceptance = raw.get("acceptance_criteria", "")
    if not isinstance(acceptance, str):
        raise DAGValidationError(f"Node '{node_id}': 'acceptance_criteria' must be a string")

    output_files = raw.get("output_files", [])
    if not isinstance(output_files, list):
        raise DAGValidationError(f"Node '{node_id}': 'output_files' must be a list")
    for k, fpath in enumerate(output_files):
        if not isinstance(fpath, str):
            raise DAGValidationError(f"Node '{node_id}': 'output_files[{k}]' must be a string")

    exclusive = raw.get("output_files_exclusive", False)
    if not isinstance(exclusive, (bool, type(None))):
        raise DAGValidationError(f"Node '{node_id}': 'output_files_exclusive' must be a bool")

    return DAGNode(
        id=node_id,
        task=task,
        depends_on=depends_on,
        timeout=timeout,
        max_retries=max_retries,
        acceptance_criteria=acceptance,
        output_files=output_files,
        output_files_exclusive=exclusive if exclusive else False,
    )


def validate(dag_dict: dict[str, Any]) -> TaskDAG:
    """Validate a raw dict against the DAG schema.

    Returns a typed TaskDAG on success.
    Raises DAGValidationError on failure.
    """
    if not isinstance(dag_dict, dict):
        raise DAGValidationError("DAG must be a JSON object")

    nodes_raw = dag_dict.get("nodes", [])
    if not isinstance(nodes_raw, list):
        raise DAGValidationError("'nodes' must be a list")
    if not nodes_raw:
        raise DAGValidationError("'nodes' must not be empty")

    description = dag_dict.get("description", "")
    if not isinstance(description, str):
        raise DAGValidationError("'description' must be a string")

    # Parse all nodes
    nodes = [_check_node(n, i) for i, n in enumerate(nodes_raw)]

    # Cross-node validation
    all_ids = {n.id for n in nodes}
    if len(all_ids) != len(nodes):
        raise DAGValidationError("Duplicate node IDs detected")

    for node in nodes:
        for dep in node.depends_on:
            if dep not in all_ids:
                raise DAGValidationError(
                    f"Node '{node.id}' depends on unknown node '{dep}'"
                )
            if dep == node.id:
                raise DAGValidationError(
                    f"Node '{node.id}' cannot depend on itself"
                )

    return TaskDAG(nodes=nodes, description=description)


def validate_concurrency(dag: TaskDAG) -> list[str]:
    """Check for concurrent output file conflicts.

    Returns a list of conflict descriptions (empty = no conflicts).
    Two nodes are concurrent if neither depends on the other.
    """
    conflicts: list[str] = []

    for i, a in enumerate(dag.nodes):
        if not a.output_files_exclusive:
            continue
        for b in dag.nodes[i + 1:]:
            if not b.output_files_exclusive:
                continue
            # Check if a and b are concurrent (neither depends on the other)
            if a.id not in b.depends_on and b.id not in a.depends_on:
                overlap = set(a.output_files) & set(b.output_files)
                if overlap:
                    conflicts.append(
                        f"Node '{a.id}' and '{b.id}' both claim exclusive "
                        f"output on: {', '.join(sorted(overlap))}"
                    )

    return conflicts


# ==========================================================================
# Phase 3: DAG Execution Engine
# ==========================================================================


logger = logging.getLogger(__name__)

SIMPLE_DAG_THRESHOLD = 3
DAG_CONCURRENCY = 3   # Max concurrent nodes per layer


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    BLOCKED = "blocked"  # retries exhausted


@dataclass
class NodeResult:
    """Result of executing a single DAG node."""
    node_id: str
    status: NodeStatus
    output: str = ""
    error: str = ""
    retries_used: int = 0


@dataclass
class DAGResult:
    """Aggregate result of a full DAG execution."""
    status: str = "pending"  # pending | success | partial | failed
    nodes: dict[str, NodeResult] = field(default_factory=dict)
    summary: str = ""


# ── Topological sort ────────────────────────────────────────────────────

def topological_sort(dag: TaskDAG) -> list[list[DAGNode]]:
    """Topologically sort nodes into parallel-ready layers.

    Each layer is a list of nodes that can all run concurrently
    (none depend on each other).

    Raises ValueError if a cycle is detected.
    """
    in_degree: dict[str, int] = {n.id: 0 for n in dag.nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)

    for node in dag.nodes:
        for dep in node.depends_on:
            outgoing[dep].append(node.id)
            in_degree[node.id] += 1

    # Kahn's algorithm
    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    layers: list[list[DAGNode]] = []
    node_map = {n.id: n for n in dag.nodes}

    while queue:
        layer: list[DAGNode] = []
        for _ in range(len(queue)):
            nid = queue.popleft()
            layer.append(node_map[nid])
            for dep_id in outgoing[nid]:
                in_degree[dep_id] -= 1
                if in_degree[dep_id] == 0:
                    queue.append(dep_id)
        layers.append(layer)

    if sum(len(l) for l in layers) != len(dag.nodes):
        raise ValueError("DAG contains a cycle")

    return layers


# ── Execution Engine ────────────────────────────────────────────────────

# Type for spawn callback: (task, timeout, max_turns, max_retries) -> result_str
SpawnFn = Callable[[str, float, int, int], Awaitable[str]]


async def execute(
    dag: TaskDAG,
    spawn: SpawnFn,
) -> DAGResult:
    """Execute a full DAG, spawning child agents per node.

    Parameters
    ----------
    dag:
        Validated TaskDAG to execute.
    spawn:
        Async callback with signature (task, timeout, max_turns, max_retries)
        → str.  This decouples the engine from specific spawn implementations.

    Returns
    -------
    DAGResult with per-node status and aggregate summary.
    """
    # Simple DAG: skip the engine, run inline
    if len(dag.nodes) <= SIMPLE_DAG_THRESHOLD:
        return await _execute_simple(dag, spawn)

    # Concurrency check
    conflicts = validate_concurrency(dag)
    if conflicts:
        return DAGResult(
            status="failed",
            summary="Concurrency conflict: " + "; ".join(conflicts),
        )

    result = DAGResult()
    sem = asyncio.Semaphore(DAG_CONCURRENCY)

    try:
        layers = topological_sort(dag)
    except ValueError as e:
        return DAGResult(status="failed", summary=str(e))

    for layer_idx, layer in enumerate(layers):
        logger.info("DAG layer %d: %d node(s) → %s",
                    layer_idx, len(layer),
                    [n.id for n in layer])

        # Run all nodes in this layer concurrently (throttled by semaphore)
        tasks = []
        for node in layer:
            async def _throttled(node=node):
                async with sem:
                    return await _run_node(node, spawn, result)
            tasks.append(_throttled())

        await asyncio.gather(*tasks, return_exceptions=True)

        # After layer completes, check if downstream nodes should be skipped
        for node in layer:
            nr = result.nodes.get(node.id)
            if nr and nr.status == NodeStatus.FAILED:
                _mark_downstream_blocked(node.id, dag, result)

    # Aggregate status
    _aggregate_result(dag, result)
    return result


async def _execute_simple(dag: TaskDAG, spawn: SpawnFn) -> DAGResult:
    """Execute a simple DAG (≤ 3 nodes) serially."""
    result = DAGResult()

    try:
        layers = topological_sort(dag)
    except ValueError as e:
        return DAGResult(status="failed", summary=str(e))

    for layer_idx, layer in enumerate(layers):
        for node in layer:
            node_result = await _run_node(node, spawn, result)
            if node_result.status == NodeStatus.FAILED:
                _mark_downstream_blocked(node.id, dag, result)
                _aggregate_result(dag, result)
                return result

    _aggregate_result(dag, result)
    return result


async def _run_node(
    node: DAGNode,
    spawn: SpawnFn,
    result: DAGResult,
) -> NodeResult:
    """Execute a single DAG node via the spawn callback."""
    logger.info("DAG node '%s': spawning", node.id)

    result.nodes[node.id] = NodeResult(
        node_id=node.id, status=NodeStatus.RUNNING,
    )

    try:
        output = await spawn(
            node.task,
            node.timeout,
            30,  # default max_turns per node
            node.max_retries,
        )
    except Exception as exc:
        result.nodes[node.id] = NodeResult(
            node_id=node.id,
            status=NodeStatus.FAILED,
            error=str(exc),
        )
        return result.nodes[node.id]

    # Determine status from output
    if output.startswith("[spawn error]") and "Retries exhausted" in output:
        result.nodes[node.id] = NodeResult(
            node_id=node.id, status=NodeStatus.BLOCKED, output=output,
        )
    elif output.startswith("[spawn error]") or output.startswith("[background error]"):
        result.nodes[node.id] = NodeResult(
            node_id=node.id, status=NodeStatus.FAILED, output=output,
        )
    elif "timeout" in output.lower() or "timed out" in output.lower():
        result.nodes[node.id] = NodeResult(
            node_id=node.id, status=NodeStatus.TIMED_OUT, output=output,
        )
    else:
        result.nodes[node.id] = NodeResult(
            node_id=node.id, status=NodeStatus.DONE, output=output,
        )

    logger.info("DAG node '%s': %s", node.id, result.nodes[node.id].status.value)
    return result.nodes[node.id]


def _mark_downstream_blocked(
    failed_node_id: str, dag: TaskDAG, result: DAGResult,
) -> None:
    """When a node fails, mark all downstream nodes as BLOCKED."""
    # Find all nodes that depend (directly or transitively) on failed_node_id
    blocked_set: set[str] = set()
    queue: deque[str] = deque([failed_node_id])

    while queue:
        current = queue.popleft()
        for node in dag.nodes:
            if current in node.depends_on and node.id not in blocked_set:
                blocked_set.add(node.id)
                queue.append(node.id)

    for nid in blocked_set:
        if nid not in result.nodes:
            result.nodes[nid] = NodeResult(
                node_id=nid,
                status=NodeStatus.BLOCKED,
                error=f"Upstream node '{failed_node_id}' failed",
            )


def _aggregate_result(dag: TaskDAG, result: DAGResult) -> None:
    """Compute aggregate DAG status from per-node results."""
    done_count = sum(1 for n in result.nodes.values() if n.status == NodeStatus.DONE)
    total = len(dag.nodes)

    if done_count == total:
        result.status = "success"
    elif done_count > 0:
        result.status = "partial"
    else:
        result.status = "failed"

    parts: list[str] = [f"DAG: {done_count}/{total} nodes completed"]
    for nid, nr in sorted(result.nodes.items()):
        icon = {NodeStatus.DONE: "✅", NodeStatus.FAILED: "❌",
                NodeStatus.TIMED_OUT: "⏱️", NodeStatus.BLOCKED: "🚫",
                NodeStatus.RUNNING: "🔄", NodeStatus.PENDING: "⏳"}
        parts.append(f"  {icon.get(nr.status, '?')} {nid}: {nr.status.value}")
        if nr.error:
            parts.append(f"     error: {nr.error[:120]}")

    result.summary = "\n".join(parts)


