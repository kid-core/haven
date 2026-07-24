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

from core.config import config

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)


from .adapter import TransportAdapter, split_long_message, DISCORD_MAX_LEN
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

    # ── Primitives ────────────────────────────────────────────────────────────────

    async def _send_text(self, channel_id: str, text: str) -> bool:
        """Send text, auto-splitting into ≤2000-char chunks for Discord."""
        if self._bot is None:
            logger.warning("Discord _send_text: bot is None")
            return False
        try:
            channel = self._bot.get_channel(int(channel_id))
            if channel is None:
                channel = await self._bot.fetch_channel(int(channel_id))
        except Exception as exc:
            logger.warning("Discord _send_text: channel %s not found — %s", channel_id, exc)
            return False

        chunks = split_long_message(text, DISCORD_MAX_LEN)
        logger.info(
            "Discord _send_text: channel=%s chunks=%d preview=%r",
            channel_id, len(chunks), text[:100],
        )
        for chunk in chunks:
            await channel.send(chunk)
        return True

    async def _send_progress(self, channel_id: str, text: str) -> str | None:
        """Send a progress message. Returns Discord message id."""
        if self._bot is None:
            return None
        try:
            channel = self._bot.get_channel(int(channel_id))
            if channel is None:
                channel = await self._bot.fetch_channel(int(channel_id))
        except Exception as exc:
            logger.warning("Discord _send_progress: channel %s not found — %s", channel_id, exc)
            return None
        msg = await channel.send(text)
        return str(msg.id)

    async def _edit_progress(self, channel_id: str, msg_id: str, text: str) -> None:
        """Edit an existing progress message."""
        if self._bot is None:
            return
        try:
            channel = self._bot.get_channel(int(channel_id))
            if channel is None:
                channel = await self._bot.fetch_channel(int(channel_id))
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(content=text)
        except Exception as exc:
            logger.debug("Discord _edit_progress: %s", exc)

    async def _delete_progress(self, channel_id: str, msg_id: str) -> None:
        """Delete a progress message."""
        if self._bot is None:
            return
        try:
            channel = self._bot.get_channel(int(channel_id))
            if channel is None:
                channel = await self._bot.fetch_channel(int(channel_id))
            msg = await channel.fetch_message(int(msg_id))
            await msg.delete()
        except Exception as exc:
            logger.debug("Discord _delete_progress: %s", exc)

    async def _send_file(self, channel_id: str, file_path: str, filename: str) -> bool:
        if self._bot is None:
            return False
        try:
            channel = self._bot.get_channel(int(channel_id))
            if channel is None:
                channel = await self._bot.fetch_channel(int(channel_id))
        except Exception:
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
        for chunk in split_long_message(text, DISCORD_MAX_LEN):
            await channel.send(chunk)
        return True

    async def notify_user(self, user_id: int, text: str) -> bool:
        if self._bot is None:
            logger.warning("Discord DM notification skipped: bot not ready")
            return False
        try:
            user = await self._bot.fetch_user(user_id)
        except Exception as exc:
            logger.warning("Discord DM notification skipped: user %d fetch failed — %s", user_id, exc)
            return False
        for chunk in split_long_message(text, DISCORD_MAX_LEN):
            await user.send(chunk)
        return True


class DiscordBot(discord.Client):
    """Discord client that delegates to a DiscordAdapter."""

    def __init__(self, adapter: DiscordAdapter, intents: discord.Intents) -> None:
        super().__init__(intents=intents)
        self._adapter = adapter

    async def on_ready(self) -> None:
        logger.info("Discord connected as %s", self.user)
        print(f"✅ Discord connected as {self.user}", flush=True)
        print(f"📋 listen_channels: {config.listen_channels}", flush=True)

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        is_mention = self.user and self.user.mentioned_in(message)
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_listen = message.channel.id in config.listen_channels
        guild_id = message.guild.id if message.guild else 0
        guild_name = message.guild.name if message.guild else "DM"
        is_listen_guild = guild_id in config.listen_guilds

        logger.info(
            "📨 Discord msg | guild=%s ch=%s(%s) author=%s is_mention=%s is_dm=%s is_listen=%s is_listen_guild=%s content=%s",
            guild_name,
            message.channel.name if hasattr(message.channel, 'name') else "DM",
            message.channel.id,
            message.author,
            is_mention,
            is_dm,
            is_listen,
            is_listen_guild,
            message.content[:80] if message.content else "(empty)",
        )

        haven_role_id = 1510890634989408269

        if not (
            is_mention
            or haven_role_id in message.raw_role_mentions
            or is_dm
            or is_listen
            or is_listen_guild
        ):
            logger.info("⛔ Discord msg FILTERED | ch=%s reason: no match", message.channel.id)
            return

        logger.info("✅ Discord msg ACCEPTED | ch=%s", message.channel.id)
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
