"""
Telegram transport for Haven.

Connects to Telegram via python-telegram-bot, listens for text messages,
and routes messages through the TransportAdapter shared pipeline.

To use: pass a Router instance to ``run_telegram``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import Application, MessageHandler, filters

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)

from .adapter import TransportAdapter
from core.config import config  # noqa: E402


class TelegramAdapter(TransportAdapter):
    """Telegram transport — thin protocol wrapper over TransportAdapter."""

    def __init__(
        self,
        router: Router,
        command_handler: Any | None = None,
    ) -> None:
        super().__init__(router, transport_name="Telegram", command_handler=command_handler)

    async def _send_text(self, channel_id: str, text: str) -> bool:
        # Telegram uses chat_id directly as integer
        try:
            from telegram import Bot
            bot = Bot(config.telegram_token)
            await bot.send_message(chat_id=int(channel_id), text=text)
            return True
        except Exception as exc:
            logger.warning("Telegram send_text failed: %s", exc)
            return False

    async def _send_file(self, channel_id: str, file_path: str, filename: str) -> bool:
        try:
            from telegram import Bot, InputFile
            bot = Bot(config.telegram_token)
            with open(file_path, "rb") as fh:
                await bot.send_document(
                    chat_id=int(channel_id),
                    document=InputFile(fh, filename=filename),
                )
            return True
        except Exception as exc:
            logger.warning("Telegram send_file failed: %s", exc)
            return False

    def _extract_user_id(self, msg: Update) -> str:
        if msg.message and msg.message.from_user:
            return str(msg.message.from_user.id)
        return "unknown"

    def _extract_text(self, msg: Update) -> str:
        if msg.message and msg.message.text:
            return msg.message.text
        return ""

    def _extract_channel_id(self, msg: Update) -> str:
        if msg.message:
            return str(msg.message.chat_id)
        return ""


@dataclass
class TelegramHandle:
    """Lightweight handle to the Telegram bot for notifications + lifecycle."""

    app: Application | None = None
    task: asyncio.Task | None = None
    _stop_event: asyncio.Event | None = None

    async def notify(self, chat_id: int, text: str) -> bool:
        if self.app is None or self.app.bot is None:
            logger.warning("Telegram notification skipped: bot not ready")
            return False
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text)
            return True
        except Exception as exc:
            logger.warning("Telegram notification failed: %s", exc)
            return False

    async def shutdown(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self.app is None:
            return
        try:
            if self.app.updater and self.app.updater.running:
                await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("Telegram stopped.")
        except Exception as exc:
            logger.warning("Telegram shutdown error: %s", exc)


def run_telegram(router: Router, command_handler: Any | None = None) -> TelegramHandle:
    """Start the Telegram bot and return a handle for notifications + shutdown."""
    token = config.telegram_token
    if not token:
        logger.warning("HAVEN_TELEGRAM_TOKEN not set — Telegram will not start")
        return TelegramHandle(app=None)

    adapter = TelegramAdapter(router, command_handler=command_handler)

    app = (
        Application.builder()
        .token(token)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )
    # PTB v20+ passes (update, context) — wrap to single-arg for handle_message
    async def _ptb_callback(update: Update, context: Any) -> None:
        await adapter.handle_message(update)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _ptb_callback))

    handle = TelegramHandle(app=app)
    handle._stop_event = asyncio.Event()

    _POLLING_RETRY_DELAY = 5  # seconds between polling retries

    async def _start():
        """Start Telegram polling with automatic retry on failure.

        If polling dies (network hiccup / API rate limit), we catch the
        exception and re-enter the loop instead of letting the task die.
        The task only exits when _stop_event is set (graceful shutdown).
        """
        while not handle._stop_event.is_set():
            try:
                await app.initialize()
                await app.start()
                await app.updater.start_polling()
                logger.info("Telegram connected as @%s", app.bot.username)
                # Block until shutdown signal or polling dies
                await handle._stop_event.wait()
                break  # clean shutdown — exit loop
            except Exception as exc:
                logger.warning(
                    "Telegram polling interrupted: %s — retrying in %ds",
                    exc, _POLLING_RETRY_DELAY,
                )
                # Stop the updater cleanly before retrying
                try:
                    await app.updater.stop()
                except Exception:
                    pass
                try:
                    await app.stop()
                except Exception:
                    pass
                await asyncio.sleep(_POLLING_RETRY_DELAY)

    loop = asyncio.get_event_loop()
    handle.task = loop.create_task(_start())

    return handle
