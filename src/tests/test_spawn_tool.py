"""Tests for spawn_child checkpoint and retry logic (Phase 1)."""

import pytest
from tools.spawn_child import (
    MAX_NESTING,
    ChildTask,
    DEFAULT_MAX_RETRIES,
    _build_checkpoint_task,
)


class TestBuildCheckpointTask:
    """Checkpoint-augmented task string construction."""

    def test_includes_retry_info(self):
        result = _build_checkpoint_task("Fix the bug", 1, 2)
        assert "attempt 1/2" in result
        assert "Fix the bug" in result

    def test_includes_auto_resume_header(self):
        result = _build_checkpoint_task("Test task", 3, 5)
        assert "AUTO-RESUME" in result
        assert "attempt 3/5" in result

    def test_includes_git_diff_hint(self):
        result = _build_checkpoint_task("Any task", 1, 3)
        # Phase 4.1: checkpoint includes git diff --stat or instruction text
        assert "git diff" in result or "files" in result.lower()
        # When no git repo, text guides to check files; when git is present, diff is shown
        assert "files" in result.lower() or "modified" in result

    def test_original_task_preserved(self):
        task = ("Long multi-line task description.\n"
                "With multiple lines.\n"
                "That should all be kept.")
        result = _build_checkpoint_task(task, 1, 2)
        assert task in result

    def test_max_retry_matches(self):
        result = _build_checkpoint_task("x", 2, 2)
        assert "attempt 2/2" in result
        assert "[AUTO-RESUME" in result


class TestChildTask:
    """ChildTask dataclass with retry_count."""

    def test_defaults(self):
        ct = ChildTask(
            task_id="abc",
            parent_id="main",
            nesting_level=1,
            task="test",
            created_at=0.0,
            timeout=60.0,
        )
        assert ct.status == "pending"
        assert ct.retry_count == 0

    def test_retry_tracked(self):
        ct = ChildTask(
            task_id="xyz",
            parent_id="p",
            nesting_level=2,
            task="retry test",
            created_at=1.0,
            timeout=30.0,
            retry_count=2,
        )
        assert ct.retry_count == 2


class TestConstants:
    """Phase 1 configuration."""

    def test_default_max_retries(self):
        assert DEFAULT_MAX_RETRIES == 2

    def test_max_nesting_unchanged(self):
        assert MAX_NESTING == 3
