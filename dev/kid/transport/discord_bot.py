"""
Discord transport for Haven.

Connects to Discord via discord.py, listens for @mentions and DMs,
and routes messages through the TransportAdapter shared pipeline.

To use: pass a Router instance to ``run_discord``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)


from .adapter import TransportAdapter
from core.config import config  # noqa: E402


class DiscordAdapter(TransportAdapter):
    """Discord transport — thin protocol wrapper over TransportAdapter."""

    def __init__(
        self,
        router: Router,
        bot: discord.Client | None = None,
        allowed_user_ids: list[str] | None = None,
        command_handler: Any | None = None,
    ) -> None:
        super().__init__(router, allowed_user_ids, transport_name="Discord", command_handler=command_handler)
        self._bot = bot

    # ── Primitives ─────────────────────────────────────────────

    async def _send_text(self, channel_id: str, text: str) -> bool:
        if self._bot is None:
            return False
        channel = self._bot.get_channel(int(channel_id))
        if channel is None:
            return False
        await channel.send(text)
        return True

    async def _send_file(self, channel_id: str, file_path: str, filename: str) -> bool:
        if self._bot is None:
            return False
        channel = self._bot.get_channel(int(channel_id))
        if channel is None:
            return False
        await channel.send(file=discord.File(file_path, filename=filename))
        return True

    def _extract_user_id(self, msg: discord.Message) -> str:
        return str(msg.author.id)

    def _extract_text(self, msg: discord.Message) -> str:
        return msg.content

    def _extract_channel_id(self, msg: discord.Message) -> str:
        return str(msg.channel.id)


@dataclass
class DiscordHandle:
    """Lightweight handle to the Discord bot for notification purposes.

    Keeps the bot reference private — external code calls ``notify()``
    without touching discord.py internals.
    """

    task: asyncio.Task
    _bot: discord.Client | None = None

    async def notify(self, channel_id: int, text: str) -> bool:
        if self._bot is None:
            logger.warning("Discord notification skipped: bot not ready")
            return False
        channel = self._bot.get_channel(channel_id)
        if channel is None:
            logger.warning("Discord notification skipped: channel %d not found", channel_id)
            return False
        await channel.send(text)
        return True

    async def notify_user(self, user_id: int, text: str) -> bool:
        if self._bot is None:
            logger.warning("Discord DM notification skipped: bot not ready")
            return False
        user = self._bot.get_user(user_id)
        if user is None:
            logger.warning("Discord DM notification skipped: user %d not found", user_id)
            return False
        await user.send(text)
        return True


class DiscordBot(discord.Client):
    """Discord client that delegates to a DiscordAdapter."""

    def __init__(self, adapter: DiscordAdapter, intents: discord.Intents) -> None:
        super().__init__(intents=intents)
        self._adapter = adapter

    async def on_ready(self) -> None:
        logger.info("Discord connected as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        haven_role_id = 1510890634989408269

        if not (
            self.user and self.user.mentioned_in(message)
            or haven_role_id in message.raw_role_mentions
            or isinstance(message.channel, discord.DMChannel)
        ):
            return

        await self._adapter.handle_message(message)


def run_discord(router: Router, command_handler: Any | None = None) -> DiscordHandle:
    """Start the Discord bot and return a handle for notifications."""
    token = config.discord_token
    if not token:
        logger.warning("HAVEN_DISCORD_TOKEN not set — Discord will not start")
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        fut.set_result(None)
        return DiscordHandle(task=fut, _bot=None)

    intents = discord.Intents.default()
    intents.message_content = True
    intents.guild_messages = True

    adapter = DiscordAdapter(router, command_handler=command_handler)
    bot = DiscordBot(adapter, intents)
    adapter._bot = bot

    task = asyncio.get_event_loop().create_task(bot.start(token))
    return DiscordHandle(task=task, _bot=bot)
