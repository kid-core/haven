"""
Tests for transport layer — Discord, Telegram, Terminal handles.

Unit tests: tests startup logic, handle dataclasses, and error paths
without requiring actual bot tokens or network connections.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


# ======================================================================
# Discord transport
# ======================================================================

class TestRunDiscord:
    """run_discord startup and handle behaviour."""

    async def test_no_token_returns_handle_without_bot(self):
        from transport.discord_bot import run_discord
        router = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            handle = run_discord(router)
        assert handle._bot is None

    async def test_no_token_notify_returns_false(self):
        from transport.discord_bot import run_discord
        router = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            handle = run_discord(router)
        result = await handle.notify(channel_id=123, text="test")
        assert result is False

    async def test_no_token_notify_user_returns_false(self):
        from transport.discord_bot import run_discord
        router = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            handle = run_discord(router)
        result = await handle.notify_user(user_id=456, text="test")
        assert result is False

    async def test_with_discord_token_env(self):
        from transport.discord_bot import run_discord
        router = MagicMock()
        with patch.dict("os.environ", {"HAVEN_DISCORD_TOKEN": "fake_token"}):
            with patch("transport.discord_bot.DiscordBot") as mock_bot:
                mock_instance = MagicMock()
                async def fake_start(_): pass
                mock_instance.start = fake_start
                mock_bot.return_value = mock_instance
                handle = run_discord(router)
        assert isinstance(handle.task, asyncio.Task)

    async def test_no_start_with_legacy_token(self):
        from transport.discord_bot import run_discord
        router = MagicMock()
        with patch.dict("os.environ", {"DISCORD_TOKEN": "legacy_token"}):
            handle = run_discord(router)
        assert handle._bot is None  # legacy token ignored


# ======================================================================
# Telegram transport
# ======================================================================

class TestRunTelegram:
    """run_telegram startup and handle behaviour."""

    async def test_no_token_returns_handle_without_app(self):
        from transport.telegram_bot import run_telegram
        router = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            handle = run_telegram(router)
        assert handle.app is None
        assert handle.task is None

    async def test_no_token_notify_returns_false(self):
        from transport.telegram_bot import run_telegram
        router = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            handle = run_telegram(router)
        result = await handle.notify(chat_id=123, text="test")
        assert result is False

    async def test_shutdown_without_app_doesnt_crash(self):
        from transport.telegram_bot import TelegramHandle
        handle = TelegramHandle(app=None)
        result = await handle.shutdown()
        assert result is None


# ======================================================================
# DiscordHandle edge cases
# ======================================================================

class TestDiscordHandle:
    """DiscordHandle dataclass behaviour."""

    async def test_default_fields(self):
        from transport.discord_bot import DiscordHandle
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        handle = DiscordHandle(task=fut)
        assert handle._bot is None
        assert handle.task is fut

    async def test_notify_without_bot_returns_false(self):
        from transport.discord_bot import DiscordHandle
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        handle = DiscordHandle(task=fut)
        result = await handle.notify(channel_id=1, text="x")
        assert result is False

    async def test_notify_user_without_bot_returns_false(self):
        from transport.discord_bot import DiscordHandle
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        handle = DiscordHandle(task=fut)
        result = await handle.notify_user(user_id=1, text="x")
        assert result is False
