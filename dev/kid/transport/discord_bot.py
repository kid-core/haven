"""
Discord transport for Haven.

Connects to Discord via discord.py, listens for @mentions and DMs,
and routes messages through the Router.

To use: pass a Router instance to ``run_discord``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
from dotenv import load_dotenv

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)

from core.paths import core_env, haven_env, openclaw_env  # noqa: E402

load_dotenv(str(core_env()))
load_dotenv(str(haven_env()), override=True)
load_dotenv(str(openclaw_env()))


@dataclass
class DiscordHandle:
    """Lightweight handle to the Discord bot for notification purposes.

    Keeps the bot reference private — external code calls ``notify()``
    without touching discord.py internals.
    """

    task: asyncio.Task
    _bot: DiscordBot | None = None

    async def notify(self, channel_id: int, text: str) -> bool:
        """Send a message to a Discord channel. Returns True on success."""
        if self._bot is None:
            logger.warning("Discord notification skipped: bot not ready")
            return False
        channel = self._bot.get_channel(channel_id)
        if channel is None:
            logger.warning(
                "Discord notification skipped: channel %s not found", channel_id
            )
            return False
        await channel.send(text)
        return True

    async def notify_user(self, user_id: int, text: str) -> bool:
        """Send a direct message to a Discord user. Returns True on success."""
        if self._bot is None:
            logger.warning("Discord DM notification skipped: bot not ready")
            return False
        user = self._bot.get_user(user_id)
        if user is None:
            logger.warning(
                "Discord DM notification skipped: user %s not found", user_id
            )
            return False
        await user.send(text)
        return True


class DiscordBot(discord.Client):
    """Discord client that forwards messages to a Haven Router."""

    def __init__(self, router: Router, intents: discord.Intents) -> None:
        super().__init__(intents=intents)
        self._router = router
        self._session_prefix = "discord:"

    async def on_ready(self) -> None:
        logger.info("Discord connected as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        # Ignore own messages
        if message.author == self.user:
            return

        # The @Haven role ID (integration-managed, bot can't actually "have" this role)
        haven_role_id = 1510890634989408269

        # Only respond to @mentions, role pings, or DMs
        if not (
            self.user and self.user.mentioned_in(message)
            or haven_role_id in message.raw_role_mentions
            or isinstance(message.channel, discord.DMChannel)
        ):
            return

        # Strip @mentions and role pings from content
        clean = re.sub(r"<@!\d+>|<@\d+>|<@&\d+>", "", message.content).strip()
        if not clean:
            return

        session_id = f"{self._session_prefix}{message.author.id}"
        async with message.channel.typing():
            try:
                reply = await self._router.process(clean, session_id=session_id)
            except Exception as exc:
                logger.exception("Router error for Discord message")
                reply = f"❌ Sorry, I hit an error: {exc}"

        await message.reply(reply)


def run_discord(router: Router) -> DiscordHandle:
    """Start the Discord bot and return a handle for notifications.

    Returns a handle whose ``notify()`` method can send messages
    once the bot has connected.
    """
    token = os.getenv("HAVEN_DISCORD_TOKEN") or os.getenv("DISCORD_TOKEN")
    if not token:
        logger.warning("HAVEN_DISCORD_TOKEN not set — Discord will not start")
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        fut.set_result(None)
        return DiscordHandle(task=fut, _bot=None)

    intents = discord.Intents.default()
    intents.message_content = True
    intents.guild_messages = True
    bot = DiscordBot(router, intents)

    task = asyncio.get_event_loop().create_task(bot.start(token))
    return DiscordHandle(task=task, _bot=bot)
