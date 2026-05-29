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
from typing import TYPE_CHECKING

import discord
from dotenv import load_dotenv

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)

load_dotenv("/mnt/z/Core/.env")
load_dotenv("/root/.openclaw/env")


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

        # Only respond to @mentions or DMs
        if not (
            self.user and self.user.mentioned_in(message)
            or isinstance(message.channel, discord.DMChannel)
        ):
            return

        # Strip @mention from content
        clean = re.sub(r"<@!\d+>|<@\d+>", "", message.content).strip()
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


def run_discord(router: Router) -> asyncio.Task:
    """Start the Discord bot as a background asyncio task.

    Returns the task so the caller can await or cancel it.
    """
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.warning("DISCORD_TOKEN not set — Discord will not start")
        # Return a no-op completed task
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        fut.set_result(None)
        return fut

    intents = discord.Intents.default()
    intents.message_content = True
    bot = DiscordBot(router, intents)

    task = asyncio.get_event_loop().create_task(bot.start(token))
    return task
