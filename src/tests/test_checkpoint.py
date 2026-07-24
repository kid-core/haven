"""Test checkpoint.py — schema validation, serialization, I/O (Phase 0)."""

import json
import tempfile
from pathlib import Path

import pytest

from core.checkpoint import (
    CHECKPOINT_DIR,
    Checkpoint,
    CheckpointValidationError,
    FileChanged,
    filepath,
    hash_file,
    list_checkpoints,
    load,
    save,
    to_dict,
    validate,
)


class TestCheckpointValidation:
    """Schema validation for checkpoint dicts."""

    def test_valid_minimal(self):
        cp = validate({"goal": "Fix the bug"})
        assert cp.goal == "Fix the bug"
        assert cp.completed == []
        assert cp.files_changed == []
        assert cp.iteration == 0
        assert cp.timestamp_utc > 0

    def test_valid_full(self):
        cp = validate({
            "goal": "Implement feature X",
            "completed": ["Wrote tests", "Fixed lint"],
            "last_action": "Ran pytest",
            "next_step": "Commit changes",
            "test_status": "45 passed",
            "blocking": "",
            "files_changed": [
                {"path": "src/x.py", "hash": "sha256:abc123", "diff_summary": "Added feature X"}
            ],
            "iteration": 1,
            "node_id": "node-2",
            "timestamp_utc": 1700000000.0,
        })
        assert cp.goal == "Implement feature X"
        assert cp.completed == ["Wrote tests", "Fixed lint"]
        assert cp.last_action == "Ran pytest"
        assert cp.next_step == "Commit changes"
        assert cp.test_status == "45 passed"
        assert cp.iteration == 1
        assert cp.node_id == "node-2"
        assert len(cp.files_changed) == 1
        assert cp.files_changed[0].path == "src/x.py"
        assert cp.files_changed[0].hash == "sha256:abc123"

    def test_missing_goal(self):
        with pytest.raises(CheckpointValidationError, match="Missing required"):
            validate({})

    def test_goal_not_string(self):
        with pytest.raises(CheckpointValidationError, match="must be a string"):
            validate({"goal": 123})

    def test_iteration_negative(self):
        with pytest.raises(CheckpointValidationError, match="non-negative"):
            validate({"goal": "x", "iteration": -1})

    def test_files_changed_not_list(self):
        with pytest.raises(CheckpointValidationError, match="must be a list"):
            validate({"goal": "x", "files_changed": "not a list"})

    def test_files_changed_bad_entry(self):
        with pytest.raises(CheckpointValidationError, match="must be a dict"):
            validate({"goal": "x", "files_changed": ["bad"]})

    def test_completed_item_not_string(self):
        with pytest.raises(CheckpointValidationError, match="must be a string"):
            validate({"goal": "x", "completed": [1, 2, 3]})

    def test_timestamp_bad_type(self):
        with pytest.raises(CheckpointValidationError, match="must be a number"):
            validate({"goal": "x", "timestamp_utc": "not a number"})


class TestCheckpointSerde:
    """Round-trip serialization."""

    def test_roundtrip(self):
        cp = Checkpoint(
            goal="Test roundtrip",
            completed=["A", "B"],
            files_changed=[FileChanged(path="f.py", hash="sha256:deadbeef")],
            iteration=2,
            node_id="n1",
        )
        data = to_dict(cp)
        reloaded = validate(data)
        assert reloaded.goal == cp.goal
        assert reloaded.completed == cp.completed
        assert reloaded.iteration == cp.iteration
        assert reloaded.node_id == cp.node_id
        assert reloaded.files_changed[0].path == "f.py"


class TestCheckpointIO:
    """Disk read/write."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, monkeypatch, tmp_path):
        monkeypatch.setattr("core.checkpoint.CHECKPOINT_DIR", tmp_path)
        yield

    def test_save_and_load(self):
        cp = Checkpoint(goal="IO test", node_id="io-node", iteration=0)
        saved_path = save(cp)
        assert saved_path.exists()

        loaded = load("io-node", 0)
        assert loaded.goal == "IO test"
        assert loaded.node_id == "io-node"

    def test_load_missing(self):
        with pytest.raises(FileNotFoundError):
            load("nonexistent", 0)

    def test_save_multiple_iterations(self):
        for i in range(3):
            cp = Checkpoint(goal=f"iter {i}", node_id="multi", iteration=i)
            save(cp)

        iterations = list_checkpoints("multi")
        assert iterations == [0, 1, 2]

    def test_list_checkpoints_empty_dir(self, monkeypatch, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr("core.checkpoint.CHECKPOINT_DIR", empty)
        assert list_checkpoints("any") == []

    def test_list_checkpoints_no_matches(self, monkeypatch, tmp_path):
        monkeypatch.setattr("core.checkpoint.CHECKPOINT_DIR", tmp_path)
        save(Checkpoint(goal="x", node_id="alpha"))
        assert list_checkpoints("beta") == []


class TestHashFile:
    """File hashing utility."""

    def test_hash_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h = hash_file(str(f))
        assert h.startswith("sha256:")
        assert len(h) > 7  # sha256: + at least 1 char

    def test_hash_file_empty(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        h = hash_file(str(f))
        assert h.startswith("sha256:")

    def test_hash_file_missing(self, tmp_path):
        h = hash_file(str(tmp_path / "nope.txt"))
        assert h == ""
