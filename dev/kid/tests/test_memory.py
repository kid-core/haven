"""
Edge-case tests for SessionStore (JSON file-backed session persistence).
"""

from __future__ import annotations

import json

import pytest


class TestSessionStoreEdgeCases:
    """SessionStore edge cases beyond basic save/load."""

    # -- empty session --------------------------------------------------

    def test_empty_session_returns_empty_list(self, tmp_path):
        """Loading a session that was never saved returns []."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path)
        assert store.load("never_saved") == []

    # -- trim -----------------------------------------------------------

    def test_trim_keeps_only_last_n(self, tmp_path):
        """Save 60 messages → load should return only max_messages (50)."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path, max_messages=50)
        messages = [{"role": "user", "content": str(i)} for i in range(60)]
        store.save("trim-test", messages)

        loaded = store.load("trim-test")
        assert len(loaded) == 50
        # First loaded message should be "10" (oldest 10 were trimmed)
        assert loaded[0]["content"] == "10"

    def test_trim_small_custom_max(self, tmp_path):
        """Custom max_messages=3 trims appropriately."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path, max_messages=3)
        messages = [{"role": "user", "content": str(i)} for i in range(10)]
        store.save("small-trim", messages)

        loaded = store.load("small-trim")
        assert len(loaded) == 3
        assert loaded[0]["content"] == "7"

    # -- corrupted file -------------------------------------------------

    def test_corrupted_json_file_returns_empty(self, tmp_path):
        """Invalid JSON in the session file → load returns []."""
        from soul.memory import SessionStore

        path = tmp_path / "corrupt.json"
        path.write_text("{this is not valid json}", encoding="utf-8")

        store = SessionStore(session_dir=tmp_path)
        result = store.load("corrupt")
        assert result == []

    def test_corrupted_json_with_dict_returns_empty(self, tmp_path):
        """Valid JSON but not a list → load returns []."""
        from soul.memory import SessionStore

        path = tmp_path / "notlist.json"
        path.write_text('{"role": "user", "content": "hello"}', encoding="utf-8")

        store = SessionStore(session_dir=tmp_path)
        result = store.load("notlist")
        assert result == []

    # -- unicode/CJK roundtrip -----------------------------------------

    def test_unicode_content_roundtrip(self, tmp_path):
        """CJK characters and emoji survive save/load."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path)
        messages = [
            {"role": "user", "content": "你好，世界！"},
            {"role": "assistant", "content": "こんにちは 🌟"},
            {"role": "user", "content": "😊 test with unicode: ñ á é"},
        ]
        store.save("unicode-session", messages)
        loaded = store.load("unicode-session")
        assert loaded == messages

    def test_unicode_trim_preserves_cjk(self, tmp_path):
        """Trimming should not corrupt unicode characters."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path, max_messages=2)
        messages = [
            {"role": "user", "content": "中文字符"},
            {"role": "assistant", "content": "日本語"},
            {"role": "user", "content": "Emoji 🎉"},
        ]
        store.save("unicode-trim", messages)
        loaded = store.load("unicode-trim")
        assert len(loaded) == 2
        assert loaded[0]["content"] == "日本語"
        assert loaded[1]["content"] == "Emoji 🎉"

    # -- special characters in session ID --------------------------------

    def test_session_id_with_slashes(self, tmp_path):
        """Session IDs with slashes should be used literally as filenames."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path)
        messages = [{"role": "user", "content": "hello"}]
        store.save("user/123", messages)
        loaded = store.load("user/123")
        assert loaded == messages

    def test_session_id_with_dots_and_dashes(self, tmp_path):
        """Session IDs with dots and dashes are fine."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path)
        messages = [{"role": "user", "content": "dotty"}]
        store.save("test.session-2026.05.29", messages)
        loaded = store.load("test.session-2026.05.29")
        assert loaded == messages

    def test_session_id_with_spaces(self, tmp_path):
        """Session IDs with spaces should work."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path)
        messages = [{"role": "user", "content": "spaces"}]
        store.save("my session with spaces", messages)
        loaded = store.load("my session with spaces")
        assert loaded == messages

    # -- large content --------------------------------------------------

    def test_large_content_roundtrip(self, tmp_path):
        """A very long message should survive save/load."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path)
        long_text = "x" * 100_000
        messages = [{"role": "user", "content": long_text}]
        store.save("large", messages)
        loaded = store.load("large")
        assert loaded == messages

    # -- multiple saves -------------------------------------------------

    def test_overwrite_saves_replaces(self, tmp_path):
        """Saving to the same session_id replaces the previous data."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path)
        store.save("overwrite", [{"role": "user", "content": "first"}])
        store.save("overwrite", [{"role": "user", "content": "second"}])
        loaded = store.load("overwrite")
        assert len(loaded) == 1
        assert loaded[0]["content"] == "second"

    # -- custom max_messages = 0 (edge) ----------------------------------

    def test_zero_max_messages_returns_empty(self, tmp_path):
        """max_messages=0 should trim everything."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path, max_messages=0)
        messages = [{"role": "user", "content": "hello"}]
        store.save("zero-max", messages)

        loaded = store.load("zero-max")
        assert loaded == []

    # -- nested dicts in messages ---------------------------------------

    def test_nested_message_structures(self, tmp_path):
        """Messages with nested dicts should survive roundtrip."""
        from soul.memory import SessionStore

        store = SessionStore(session_dir=tmp_path)
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "execute_command",
                            "arguments": {"cmd": "ls"},
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"output": "file.txt"}',
            },
        ]
        store.save("nested", messages)
        loaded = store.load("nested")
        assert loaded == messages
