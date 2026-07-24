"""
Tests for soul/memory/session_store.py — SessionStore persistence.

Validates JSON roundtrip, max_messages trimming, and the critical
orphan-tool-message guard that prevents DeepSeek 400 errors when
trimming cuts off assistant(tool_calls) but keeps trailing tool results.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from soul.memory.session_store import SessionStore


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    """SessionStore with temp dir, small max for trimming tests."""
    return SessionStore(session_dir=tmp_path, max_messages=10)


# ── Basic roundtrip ────────────────────────────────────────────────

def test_save_load_roundtrip(store: SessionStore) -> None:
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi!"},
    ]
    store.save("s1", messages)
    loaded = store.load("s1")
    assert loaded == messages


def test_load_missing_session(store: SessionStore) -> None:
    assert store.load("nonexistent") == []


# ── Trimming (max_messages) ───────────────────────────────────────

def test_trim_excess_messages(store: SessionStore) -> None:
    """Last max_messages are kept, older ones discarded."""
    messages = [{"role": "user", "content": f"msg{i}"} for i in range(15)]
    store.save("trim", messages)
    loaded = store.load("trim")
    assert len(loaded) == 10
    assert loaded[0]["content"] == "msg5"
    assert loaded[-1]["content"] == "msg14"


# ── Orphan tool guard (the critical fix) ──────────────────────────

def _make_tool_call_assistant(call_ids: list[str]) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
            for cid in call_ids
        ],
    }


def _make_tool_result(call_id: str, content: str = "ok") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_leading_orphan_tools_stripped_on_save(store: SessionStore) -> None:
    """When trimming cuts off assistant(tool_calls), orphan tool
    messages at the front of the trimmed array must be stripped."""
    # Simulate: assistant with 3 tool_calls, then 3 tool results,
    # then more messages to push past max.
    messages = [
        {"role": "system", "content": "base"},
        {"role": "user", "content": "q1"},
        _make_tool_call_assistant(["c0", "c1", "c2"]),
        _make_tool_result("c0"),
        _make_tool_result("c1"),
        _make_tool_result("c2"),
        {"role": "assistant", "content": "got results"},
    ]
    # Add filler to force trimming — 7 base + 10 filler = 17, trim to 10
    filler = [{"role": "user", "content": f"fill{i}"} for i in range(10)]
    messages.extend(filler)

    store.save("orphan_front", messages)
    loaded = store.load("orphan_front")

    # First message must NOT be a tool
    assert loaded[0]["role"] != "tool", (
        f"Orphan tool messages not stripped! First message: {loaded[0]}"
    )
    # Assistant with tool results at index 0-3 should be gone (trimmed off)
    # Only filler + tail should remain
    assert all(
        m["role"] != "tool" for m in loaded
    ), "All orphaned tools should be removed"


def test_valid_tool_messages_preserved(store: SessionStore) -> None:
    """Tool messages with valid preceding assistant(tool_calls) survive."""
    messages = [
        {"role": "system", "content": "base"},
        _make_tool_call_assistant(["a0"]),
        _make_tool_result("a0", "result"),
        {"role": "assistant", "content": "done"},
    ]
    store.save("valid_tools", messages)
    loaded = store.load("valid_tools")
    assert len(loaded) == 4
    assert loaded[1]["role"] == "assistant"
    assert "tool_calls" in loaded[1]
    assert loaded[2]["role"] == "tool"
    assert loaded[2]["tool_call_id"] == "a0"


def test_orphan_tools_anywhere_stripped(store: SessionStore) -> None:
    """Tool messages without matching assistant(tool_calls) are
    removed regardless of position."""
    # Valid pair a0, then orphan b0 (no matching assistant), then valid pair c0
    messages = [
        {"role": "system", "content": "base"},
        _make_tool_call_assistant(["a0"]),
        _make_tool_result("a0", "from a"),
        {"role": "assistant", "content": "mid"},
        _make_tool_result("b0"),       # orphan — no matching tool_calls
        {"role": "user", "content": "next"},
        _make_tool_call_assistant(["c0"]),
        _make_tool_result("c0", "from c"),
        {"role": "assistant", "content": "final"},
    ]
    store.save("orphan_mid", messages)
    loaded = store.load("orphan_mid")

    tool_ids = [m.get("tool_call_id") for m in loaded if m["role"] == "tool"]
    assert "b0" not in tool_ids, f"Orphan b0 was not stripped! {tool_ids}"
    assert "a0" in tool_ids, "Valid a0 should be preserved"
    assert "c0" in tool_ids, "Valid c0 should be preserved"


def test_multiple_orphan_sets(store: SessionStore) -> None:
    """Multiple orphaned tool sets (e.g. 2 different trimmed turns)."""
    messages = [
        {"role": "system", "content": "base"},
        # Turn 1: 3 tool_calls → will be trimmed
        _make_tool_call_assistant(["x0", "x1", "x2"]),
        _make_tool_result("x0"),
        _make_tool_result("x1"),
        _make_tool_result("x2"),
        # Turn 2: 2 tool_calls → will be trimmed
        _make_tool_call_assistant(["y0", "y1"]),
        _make_tool_result("y0"),
        _make_tool_result("y1"),
        # Turn 3: valid pair that survives
        _make_tool_call_assistant(["z0"]),
        _make_tool_result("z0"),
        {"role": "assistant", "content": "last"},
    ]
    # Add filler to push past max=10
    filler = [{"role": "user", "content": f"f{i}"} for i in range(12)]
    messages.extend(filler)

    store.save("multi_orphan", messages)
    loaded = store.load("multi_orphan")

    # No orphaned tools should remain
    assert loaded[0]["role"] != "tool", f"Leading orphan found: {loaded[0]}"
    tool_ids = [m.get("tool_call_id") for m in loaded if m["role"] == "tool"]
    for orphan_prefix in ("x", "y"):
        assert not any(tid and tid.startswith(orphan_prefix) for tid in tool_ids), (
            f"Orphan {orphan_prefix}* tools not stripped: {tool_ids}"
        )


def test_load_strips_orphans_too(store: SessionStore) -> None:
    """Orphan guard also fires on load() for defense-in-depth."""
    # Directly write a corrupt file with leading orphans
    corrupt = [
        _make_tool_result("orphan_1"),
        _make_tool_result("orphan_2"),
        {"role": "assistant", "content": "first valid"},
    ]
    path = store.session_dir / "corrupt.json"
    import json
    path.write_text(json.dumps(corrupt))

    loaded = store.load("corrupt")
    assert len(loaded) == 1, f"Should have stripped 2 orphans, got {len(loaded)}: {loaded}"
    assert loaded[0]["role"] == "assistant"


def test_empty_and_edge_cases(store: SessionStore) -> None:
    """Guard handles empty arrays and edge cases gracefully."""
    assert store._validate_tool_pairing([]) == []
    assert store._validate_tool_pairing(
        [{"role": "system", "content": "only"}]
    ) == [{"role": "system", "content": "only"}]
    # All orphans
    assert store._validate_tool_pairing(
        [_make_tool_result("o1"), _make_tool_result("o2")]
    ) == []
    # Only assistant with tool_calls (no tool results yet — valid)
    msgs = [_make_tool_call_assistant(["pending"])]
    assert store._validate_tool_pairing(msgs) == msgs
