"""Test progress_judge.py — heartbeat judge for lost-agent detection (Phase 2)."""

import pytest
from core.progress_judge import (
    HOLLOW_KEYWORDS,
    HEARTBEAT_EVERY,
    HeartbeatTracker,
    TURN_EXEMPT,
    is_hollow_rule,
    judge,
    judge_similarity,
)


class TestIsHollowRule:
    """Rule-based hollow detection."""

    def test_too_short(self):
        hollow, reason = is_hollow_rule("Working")
        assert hollow
        assert "short" in reason

    def test_empty(self):
        hollow, _ = is_hollow_rule("")
        assert hollow

    def test_hollow_keyword(self):
        for kw in ["持續努力", "進行中", "測試中"]:
            # Need > 20 chars to bypass length check
            text = f"我們目前正在{kw}解決這個很複雜的問題中請稍候結果"
            hollow, reason = is_hollow_rule(text)
            assert hollow, f"Should detect: {kw} in '{text}' (len={len(text)})"
            assert kw in reason

    def test_english_hollow(self):
        hollow, _ = is_hollow_rule("We are still working on this complex issue")
        assert hollow

    def test_specific_ok(self):
        """Concrete, specific self-assessments should pass."""
        hollow, _ = is_hollow_rule(
            "已完成：修改了 cmd.py 加入 import os，已通過 pytest 45 個測試"
        )
        assert not hollow

    def test_specific_english_ok(self):
        hollow, _ = is_hollow_rule(
            "Fixed the import bug in cmd.py, all 45 tests now pass"
        )
        assert not hollow


class TestJudgeSimilarity:
    """Similarity-based judge."""

    def test_identical_hollow(self):
        hollow, score = judge_similarity("Working on it", "Working on it")
        assert hollow
        assert score >= 0.85

    def test_similar_hollow(self):
        hollow, score = judge_similarity(
            "Debugging the import issue still alive work",
            "Debugging the import problem still alive work"
        )
        assert hollow, f"Score={score}"

    def test_different_not_hollow(self):
        hollow, score = judge_similarity(
            "Fixed the import bug in cmd.py",
            "Now working on the test suite"
        )
        assert not hollow

    def test_completely_different(self):
        hollow, score = judge_similarity("abc def ghi", "xyz uvw rst")
        assert score < 0.3


class TestJudge:
    """Combined judge pipeline."""

    def test_rule_catches_hollow(self):
        hollow, reason = judge("", "進行中")
        assert hollow
        assert "rule" in reason

    def test_similarity_catches_repetition(self):
        prev = "Debugging the import issue still alive"
        curr = "Debugging the import issue still alive"
        hollow, reason = judge(prev, curr)
        assert hollow
        assert "similarity" in reason
        assert "similarity" in reason

    def test_specific_passes(self):
        hollow, reason = judge(
            "Fixed import in cmd.py",
            "Added tests for file_guard — 32 passed"
        )
        assert not hollow

    def test_no_previous_still_works(self):
        """Without a previous assessment, rule-based alone applies."""
        hollow, reason = judge("", "Fixed the bug, tests pass")
        assert not hollow  # > 20 chars, no hollow keywords


class TestHeartbeatTracker:
    """Heartbeat tracker lifecycle."""

    def test_exempt_in_first_turns(self):
        tracker = HeartbeatTracker()
        for turn in range(1, TURN_EXEMPT):
            assert not tracker.should_check(turn), f"Turn {turn} should be exempt"

    def test_check_at_interval(self):
        tracker = HeartbeatTracker()
        assert not tracker.should_check(TURN_EXEMPT + 1)
        assert tracker.should_check(TURN_EXEMPT)  # first check at turn 10
        assert not tracker.should_check(TURN_EXEMPT + 1)
        assert tracker.should_check(TURN_EXEMPT + HEARTBEAT_EVERY)  # next at 15

    def test_single_hollow_no_trigger(self):
        tracker = HeartbeatTracker()
        triggered, _ = tracker.record("進行中", TURN_EXEMPT)
        assert not triggered

    def test_two_hollow_triggers(self):
        tracker = HeartbeatTracker()
        triggered, _ = tracker.record("進行中", TURN_EXEMPT)
        assert not triggered
        triggered, reason = tracker.record("調整中", TURN_EXEMPT + 5)
        assert triggered
        assert "streak" in reason.lower()

    def test_specific_resets_streak(self):
        tracker = HeartbeatTracker()
        tracker.record("進行中", TURN_EXEMPT)  # hollow, streak=1
        tracker.record("Fixed import bug, 45 tests pass", TURN_EXEMPT + 5)  # ok, reset
        triggered, _ = tracker.record("調整中", TURN_EXEMPT + 10)  # hollow, streak=1
        assert not triggered  # streak reset after specific answer

    def test_heartbeat_prompt_content(self):
        tracker = HeartbeatTracker()
        prompt = tracker.heartbeat_prompt()
        assert "PROGRESS HEARTBEAT" in prompt
        assert "completed" in prompt.lower()
        assert "next" in prompt.lower()
