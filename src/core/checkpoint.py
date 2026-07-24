"""Checkpoint schema and I/O for task orchestration (Phase 0).

Defines the standard checkpoint format used by Auto Resume (Phase 1).
Write happens before timeout; read happens when a new agent takes over.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Configurable paths ──────────────────────────────────────────────────

CHECKPOINT_DIR = Path(os.getenv("HAVEN_CHECKPOINT_DIR", "/mnt/z/haven/tmp"))


# ── Schema: FileChanged ─────────────────────────────────────────────────

@dataclass
class FileChanged:
    """Record of a file modified during a task node."""
    path: str
    hash: str = ""
    diff_summary: str = ""


# ── Schema: Checkpoint ──────────────────────────────────────────────────

@dataclass
class Checkpoint:
    """Standard checkpoint for task node handoff.

    Fields:
        goal:           Original task goal for this node.
        completed:      List of things already done.
        last_action:    Last concrete action taken.
        next_step:      Planned next action.
        test_status:    Current test suite status (pass/fail/count).
        blocking:       Blocking issue, if any.
        files_changed:  List of modified files with hashes + summaries.
        iteration:      Retry counter (0 = first attempt).
        node_id:        DAG node ID this checkpoint belongs to.
        timestamp_utc:  POSIX timestamp of checkpoint creation.
    """
    goal: str
    completed: list[str] = field(default_factory=list)
    last_action: str = ""
    next_step: str = ""
    test_status: str = ""
    blocking: str = ""
    files_changed: list[FileChanged] = field(default_factory=list)
    iteration: int = 0
    node_id: str = ""
    timestamp_utc: float = field(default_factory=time.time)


# ── Validation ──────────────────────────────────────────────────────────

class CheckpointValidationError(ValueError):
    """Raised when a checkpoint fails schema validation."""
    pass


def _check_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise CheckpointValidationError(f"'{field}' must be a string, got {type(value).__name__}")
    return value


def _check_list(value: Any, field: str) -> list:
    if not isinstance(value, list):
        raise CheckpointValidationError(f"'{field}' must be a list, got {type(value).__name__}")
    return value


def validate(checkpoint_dict: dict[str, Any]) -> Checkpoint:
    """Validate a raw dict against the Checkpoint schema.

    Returns a typed Checkpoint on success.
    Raises CheckpointValidationError on failure.
    """
    required_fields = ["goal"]
    for key in required_fields:
        if key not in checkpoint_dict:
            raise CheckpointValidationError(f"Missing required field: '{key}'")

    goal = _check_str(checkpoint_dict["goal"], "goal")
    last_action = _check_str(checkpoint_dict.get("last_action", ""), "last_action")
    next_step = _check_str(checkpoint_dict.get("next_step", ""), "next_step")
    test_status = _check_str(checkpoint_dict.get("test_status", ""), "test_status")
    blocking = _check_str(checkpoint_dict.get("blocking", ""), "blocking")
    node_id = _check_str(checkpoint_dict.get("node_id", ""), "node_id")

    completed = _check_list(checkpoint_dict.get("completed", []), "completed")
    for i, item in enumerate(completed):
        if not isinstance(item, str):
            raise CheckpointValidationError(f"'completed[{i}]' must be a string")

    iteration = checkpoint_dict.get("iteration", 0)
    if not isinstance(iteration, int) or iteration < 0:
        raise CheckpointValidationError(f"'iteration' must be a non-negative int, got {iteration}")

    timestamp = checkpoint_dict.get("timestamp_utc", time.time())
    if not isinstance(timestamp, (int, float)):
        raise CheckpointValidationError(f"'timestamp_utc' must be a number")

    # Validate files_changed
    files_raw = checkpoint_dict.get("files_changed", [])
    if not isinstance(files_raw, list):
        raise CheckpointValidationError("'files_changed' must be a list")

    files: list[FileChanged] = []
    for i, entry in enumerate(files_raw):
        if not isinstance(entry, dict):
            raise CheckpointValidationError(f"'files_changed[{i}]' must be a dict")
        path = _check_str(entry.get("path", ""), f"files_changed[{i}].path")
        fhash = _check_str(entry.get("hash", ""), f"files_changed[{i}].hash")
        summary = _check_str(entry.get("diff_summary", ""), f"files_changed[{i}].diff_summary")
        files.append(FileChanged(path=path, hash=fhash, diff_summary=summary))

    return Checkpoint(
        goal=goal,
        completed=completed,
        last_action=last_action,
        next_step=next_step,
        test_status=test_status,
        blocking=blocking,
        files_changed=files,
        iteration=iteration,
        node_id=node_id,
        timestamp_utc=timestamp,
    )


# ── Serialization ───────────────────────────────────────────────────────

def to_dict(cp: Checkpoint) -> dict[str, Any]:
    """Serialize a Checkpoint to a JSON-serializable dict."""
    return {
        "goal": cp.goal,
        "completed": cp.completed,
        "last_action": cp.last_action,
        "next_step": cp.next_step,
        "test_status": cp.test_status,
        "blocking": cp.blocking,
        "files_changed": [
            {"path": f.path, "hash": f.hash, "diff_summary": f.diff_summary}
            for f in cp.files_changed
        ],
        "iteration": cp.iteration,
        "node_id": cp.node_id,
        "timestamp_utc": cp.timestamp_utc,
    }


# ── Disk I/O ────────────────────────────────────────────────────────────

def filepath(node_id: str, iteration: int = 0) -> Path:
    """Get the checkpoint file path for a given node + iteration."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR / f"checkpoint_{node_id}_iter{iteration}.json"


def save(cp: Checkpoint) -> Path:
    """Write a Checkpoint to disk. Returns the file path."""
    path = filepath(cp.node_id, cp.iteration)
    data = to_dict(cp)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load(node_id: str, iteration: int = 0) -> Checkpoint:
    """Load a Checkpoint from disk.

    Raises FileNotFoundError if the file doesn't exist.
    Raises CheckpointValidationError if the file is malformed.
    """
    path = filepath(node_id, iteration)
    if not path.exists():
        raise FileNotFoundError(f"No checkpoint for node '{node_id}' iteration {iteration}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CheckpointValidationError("Checkpoint file must be a JSON object")
    return validate(raw)


def list_checkpoints(node_id: str) -> list[int]:
    """List all iteration numbers for a given node_id that have checkpoints."""
    if not CHECKPOINT_DIR.exists():
        return []
    iterations: list[int] = []
    prefix = f"checkpoint_{node_id}_iter"
    for f in CHECKPOINT_DIR.iterdir():
        name = f.name
        if name.startswith(prefix) and name.endswith(".json"):
            try:
                iterations.append(int(name[len(prefix):-5]))
            except ValueError:
                pass
    return sorted(iterations)


# ── Hash helper ─────────────────────────────────────────────────────────

def hash_file(path: str) -> str:
    """Compute SHA-256 of a file for the FileChanged hash field."""
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
    except OSError:
        return ""
    return "sha256:" + hasher.hexdigest()[:16]
