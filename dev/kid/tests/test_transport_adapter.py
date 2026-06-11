"""
Tests for transport/adapter.py — TransportAdapter base class.

Uses a fake transport subclass to test the shared pipeline without
any real transport library.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from transport.adapter import TransportAdapter, _MENTION_RE


# ── Fake transport for testing ────────────────────────────────

class FakeTransport(TransportAdapter):
    """A TransportAdapter that records calls instead of sending."""

    def __init__(self, router, allowed_user_ids=None):
        super().__init__(router, allowed_user_ids, transport_name="Fake")
        self.sent_texts: list[tuple[str, str]] = []  # (channel_id, text)
        self.sent_files: list[tuple[str, str, str]] = []  # (cid, path, name)

    async def _send_text(self, channel_id: str, text: str) -> bool:
        self.sent_texts.append((channel_id, text))
        return True

    async def _send_file(self, channel_id: str, file_path: str, filename: str) -> bool:
        self.sent_files.append((channel_id, file_path, filename))
        return True

    def _extract_user_id(self, msg) -> str:
        return msg.get("user_id", "999")

    def _extract_text(self, msg) -> str:
        return msg.get("text", "")

    def _extract_channel_id(self, msg) -> str:
        return msg.get("channel_id", "chan_1")


# ── Tests ─────────────────────────────────────────────────────

class TestMentionRe:
    """_MENTION_RE strips Discord-style mentions."""

    def test_strips_user_mention(self):
        result = _MENTION_RE.sub("", "<@!123456> hello")
        assert result.strip() == "hello"

    def test_strips_role_ping(self):
        result = _MENTION_RE.sub("", "<@&789012> ping")
        assert result.strip() == "ping"

    def test_strips_bare_mention(self):
        result = _MENTION_RE.sub("", "<@123> test")
        assert result.strip() == "test"

    def test_no_mention_unchanged(self):
        result = _MENTION_RE.sub("", "just text")
        assert result.strip() == "just text"

    def test_empty_string(self):
        result = _MENTION_RE.sub("", "")
        assert result == ""


class TestTransportAdapter:
    """Shared pipeline in TransportAdapter."""

    @pytest.fixture
    def router(self):
        r = MagicMock()
        r.process = AsyncMock(return_value="Hello back")
        r.pop_pending_files = MagicMock(return_value=[])
        return r

    @pytest.fixture
    def transport(self, router):
        return FakeTransport(router)

    # ── handle_message basic flow ─────────────────────────────

    async def test_handle_message_sends_reply(self, transport, router):
        msg = {"user_id": "111", "text": "Hi", "channel_id": "chan_x"}
        await transport.handle_message(msg)

        assert len(transport.sent_texts) == 1
        cid, text = transport.sent_texts[0]
        assert cid == "chan_x"
        assert text == "Hello back"
        router.process.assert_awaited_once()

    async def test_handle_empty_text_skipped(self, transport):
        msg = {"user_id": "111", "text": "", "channel_id": "chan_x"}
        await transport.handle_message(msg)
        assert len(transport.sent_texts) == 0

    async def test_handle_whitespace_only_skipped(self, transport):
        msg = {"user_id": "111", "text": "   ", "channel_id": "chan_x"}
        await transport.handle_message(msg)
        assert len(transport.sent_texts) == 0

    async def test_handle_mention_only_skipped(self, transport):
        msg = {"user_id": "111", "text": "<@!123>", "channel_id": "chan_x"}
        await transport.handle_message(msg)
        assert len(transport.sent_texts) == 0

    async def test_handle_mention_stripped(self, transport, router):
        msg = {"user_id": "111", "text": "<@!123> hello", "channel_id": "chan_x"}
        await transport.handle_message(msg)
        router.process.assert_awaited_once_with("hello", session_id="fake:111")

    # ── User whitelist ───────────────────────────────────────

    async def test_whitelist_allows(self, router):
        transport = FakeTransport(router, allowed_user_ids=["111", "222"])
        msg = {"user_id": "111", "text": "Hi"}
        await transport.handle_message(msg)
        router.process.assert_awaited_once()

    async def test_whitelist_blocks(self, router):
        transport = FakeTransport(router, allowed_user_ids=["111"])
        msg = {"user_id": "999", "text": "Hi"}
        await transport.handle_message(msg)
        router.process.assert_not_called()

    async def test_empty_whitelist_allows_all(self, router):
        transport = FakeTransport(router, allowed_user_ids=[])
        msg = {"user_id": "999", "text": "Hi"}
        await transport.handle_message(msg)
        router.process.assert_awaited_once()

    async def test_none_whitelist_allows_all(self, router):
        transport = FakeTransport(router, allowed_user_ids=None)
        msg = {"user_id": "999", "text": "Hi"}
        await transport.handle_message(msg)
        router.process.assert_awaited_once()

    # ── Error handling ───────────────────────────────────────

    async def test_router_error_returns_friendly_message(self, transport):
        transport._router.process = AsyncMock(side_effect=RuntimeError("boom"))
        msg = {"user_id": "111", "text": "Hi", "channel_id": "chan_x"}
        await transport.handle_message(msg)
        assert len(transport.sent_texts) == 1
        cid, text = transport.sent_texts[0]
        assert "error" in text.lower()

    # ── Session ID ────────────────────────────────────────────

    async def test_session_id_format(self, transport, router):
        transport._transport_name = "Discord"
        msg = {"user_id": "user_42", "text": "Hi"}
        await transport.handle_message(msg)
        router.process.assert_awaited_once_with("Hi", session_id="discord:user_42")

    # ── Pending files ─────────────────────────────────────────

    async def test_files_sent_when_pending(self, transport, router):
        file_mock = MagicMock()
        file_mock.file_path = "/tmp/test.txt"
        file_mock.filename = "test.txt"
        router.pop_pending_files = MagicMock(return_value=[file_mock])

        msg = {"user_id": "111", "text": "send file", "channel_id": "chan_x"}
        await transport.handle_message(msg)

        assert len(transport.sent_files) == 1
        assert transport.sent_files[0] == ("chan_x", "/tmp/test.txt", "test.txt")

    async def test_no_files_no_error(self, transport, router):
        router.pop_pending_files = MagicMock(return_value=[])
        msg = {"user_id": "111", "text": "no file", "channel_id": "chan_x"}
        await transport.handle_message(msg)
        assert len(transport.sent_texts) == 1
        assert len(transport.sent_files) == 0

    # ── DiscordAdapter spec ───────────────────────────────────

    def test_discord_adapter_extract_user_id(self):
        from transport.discord_bot import DiscordAdapter

        adapter = DiscordAdapter(router=MagicMock())

        msg = MagicMock()
        msg.author.id = 12345
        assert adapter._extract_user_id(msg) == "12345"

    def test_discord_adapter_extract_text(self):
        from transport.discord_bot import DiscordAdapter

        adapter = DiscordAdapter(router=MagicMock())
        msg = MagicMock()
        msg.content = "hello discord"
        assert adapter._extract_text(msg) == "hello discord"

    def test_discord_adapter_extract_channel_id(self):
        from transport.discord_bot import DiscordAdapter

        adapter = DiscordAdapter(router=MagicMock())
        msg = MagicMock()
        msg.channel.id = 67890
        assert adapter._extract_channel_id(msg) == "67890"

    # ── TelegramAdapter spec ──────────────────────────────────

    def test_telegram_adapter_extract_user_id(self):
        from transport.telegram_bot import TelegramAdapter

        adapter = TelegramAdapter(router=MagicMock())

        update = MagicMock()
        update.message.from_user.id = 555
        assert adapter._extract_user_id(update) == "555"

    def test_telegram_adapter_extract_text(self):
        from transport.telegram_bot import TelegramAdapter

        adapter = TelegramAdapter(router=MagicMock())
        update = MagicMock()
        update.message.text = "hello tg"
        assert adapter._extract_text(update) == "hello tg"

    def test_telegram_adapter_extract_channel_id(self):
        from transport.telegram_bot import TelegramAdapter

        adapter = TelegramAdapter(router=MagicMock())
        update = MagicMock()
        update.message.chat_id = 444
        assert adapter._extract_channel_id(update) == "444"
