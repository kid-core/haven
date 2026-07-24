"""
Tests for core/crash_journal.py — CrashJournal persistence and recovery.

Unit tests: uses tmp_path for isolation, no real crash files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.crash_journal import CrashJournal


class TestCrashJournal:
    """CrashJournal — file-backed crash log."""

    # ------------------------------------------------------------------
    # Basic life-cycle
    # ------------------------------------------------------------------

    def test_log_returns_id(self, crash_journal: CrashJournal):
        crash_id = crash_journal.log(task_name="test_task", error="Something broke")
        assert len(crash_id) == 12
        assert isinstance(crash_id, str)

    def test_read_pending_after_log(self, crash_journal: CrashJournal):
        crash_journal.log(task_name="task_1", error="fail")
        pending = crash_journal.read_pending()
        assert len(pending) == 1
        assert pending[0]["task_name"] == "task_1"
        assert pending[0]["handled"] is False

    def test_mark_handled(self, crash_journal: CrashJournal):
        crash_id = crash_journal.log(task_name="task_1", error="fail")
        crash_journal.mark_handled(crash_id)
        pending = crash_journal.read_pending()
        assert len(pending) == 0

    def test_mark_handled_only_one(self, crash_journal: CrashJournal):
        id_1 = crash_journal.log(task_name="a", error="err1")
        crash_journal.log(task_name="b", error="err2")
        crash_journal.mark_handled(id_1)
        pending = crash_journal.read_pending()
        assert len(pending) == 1
        assert pending[0]["task_name"] == "b"

    def test_context_is_optional(self, crash_journal: CrashJournal):
        crash_journal.log(task_name="noctx", error="err")
        pending = crash_journal.read_pending()
        assert pending[0]["context"] == {}

    def test_context_stored(self, crash_journal: CrashJournal):
        ctx = {"file": "/tmp/x.txt", "retry_count": 3}
        crash_journal.log(task_name="ctx_test", error="err", context=ctx)
        pending = crash_journal.read_pending()
        assert pending[0]["context"] == ctx

    def test_timestamp_is_set(self, crash_journal: CrashJournal):
        crash_journal.log(task_name="ts_test", error="err")
        pending = crash_journal.read_pending()
        assert isinstance(pending[0]["timestamp"], (int, float))
        assert pending[0]["timestamp"] > 0

    # ------------------------------------------------------------------
    # Persistence (survives re-creation)
    # ------------------------------------------------------------------

    def test_logs_survive_reload(self, tmp_path: Path):
        storage = str(tmp_path / "crash.json")
        j1 = CrashJournal(storage_path=storage)
        j1.log(task_name="persist", error="gone")
        j1.log(task_name="persist2", error="gone2")

        j2 = CrashJournal(storage_path=storage)
        pending = j2.read_pending()
        assert len(pending) == 2
        assert pending[0]["task_name"] == "persist"
        assert pending[1]["task_name"] == "persist2"

    # ------------------------------------------------------------------
    # Corrupted file handling
    # ------------------------------------------------------------------

    def test_corrupt_file_returns_empty_list(self, tmp_path: Path):
        storage = tmp_path / "crash.json"
        storage.write_text("{invalid json", encoding="utf-8")

        journal = CrashJournal(storage_path=str(storage))
        pending = journal.read_pending()
        assert pending == []

    def test_corrupt_file_does_not_block_new_logs(self, tmp_path: Path):
        storage = tmp_path / "crash.json"
        storage.write_text("not json", encoding="utf-8")

        journal = CrashJournal(storage_path=str(storage))
        crash_id = journal.log(task_name="after_corrupt", error="still works")
        assert crash_id is not None

        # File should now contain valid JSON
        data = json.loads(storage.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["task_name"] == "after_corrupt"

    def test_partial_write_survives_atomic(self, tmp_path: Path):
        """CrashJournal uses atomic write (tmp + replace). A partial write
        to the temp file should not corrupt the original."""
        storage = tmp_path / "crash.json"

        j1 = CrashJournal(storage_path=str(storage))
        original_id = j1.log(task_name="original", error="preserve me")

        # Simulate a crash during write: create a bad .tmp file
        j1._path.with_suffix(".tmp").write_text("partial]", encoding="utf-8")

        j2 = CrashJournal(storage_path=str(storage))
        pending = j2.read_pending()
        assert len(pending) == 1
        assert pending[0]["id"] == original_id

    # ------------------------------------------------------------------
    # Empty / missing file handling
    # ------------------------------------------------------------------

    def test_no_file_returns_empty(self, tmp_path: Path):
        journal = CrashJournal(storage_path=str(tmp_path / "nonexistent.json"))
        pending = journal.read_pending()
        assert pending == []

    def test_empty_file_returns_empty(self, tmp_path: Path):
        storage = tmp_path / "empty.json"
        storage.write_text("", encoding="utf-8")
        journal = CrashJournal(storage_path=str(storage))
        pending = journal.read_pending()
        assert pending == []

    def test_blank_file_returns_empty(self, tmp_path: Path):
        storage = tmp_path / "blank.json"
        storage.write_text("   ", encoding="utf-8")
        journal = CrashJournal(storage_path=str(storage))
        pending = journal.read_pending()
        assert pending == []

    # ------------------------------------------------------------------
    # Multiple crash entries
    # ------------------------------------------------------------------

    def test_multiple_crashes_accumulate(self, crash_journal: CrashJournal):
        ids = []
        for i in range(10):
            cid = crash_journal.log(task_name=f"task_{i}", error=f"error_{i}")
            ids.append(cid)

        pending = crash_journal.read_pending()
        assert len(pending) == 10
        for i in range(10):
            assert pending[i]["task_name"] == f"task_{i}"

    def test_mark_handled_idempotent(self, crash_journal: CrashJournal):
        """Marking an already-handled crash should not raise."""
        crash_id = crash_journal.log(task_name="x", error="x")
        crash_journal.mark_handled(crash_id)
        crash_journal.mark_handled(crash_id)  # second call — no error
        pending = crash_journal.read_pending()
        assert len(pending) == 0

    def test_mark_nonexistent_does_not_crash(self, crash_journal: CrashJournal):
        """Marking a crash_id that doesn't exist should not raise."""
        crash_journal.mark_handled("nonexistent_id")
        # no assertion needed — just must not crash
