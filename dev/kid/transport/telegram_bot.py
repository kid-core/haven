"""
Telegram transport for Haven.

Connects to Telegram via python-telegram-bot, listens for text messages,
and routes messages through the Router.

To use: pass a Router instance to ``run_telegram``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters

if TYPE_CHECKING:
    from core.router import Router

logger = logging.getLogger(__name__)

load_dotenv("/mnt/z/Core/.env")
load_dotenv("/root/.openclaw/env")


class TelegramHandler:
    """DI-based handler — Router is injected via constructor (Section 3.3)."""

    def __init__(self, router: Router) -> None:
        self._router = router

    async def __call__(self, update: Update, _context: object) -> None:
        """Handle an incoming Telegram message."""
        if not update.message or not update.message.text:
            return

        user_id = str(update.message.from_user.id)
        text = update.message.text.strip()
        session_id = f"telegram:{user_id}"

        try:
            reply = await self._router.process(text, session_id=session_id)
        except Exception as exc:
            logger.exception("Router error for Telegram message")
            reply = f"❌ Sorry, I hit an error: {exc}"

        await update.message.reply_text(reply)


def run_telegram(router: Router) -> Application | None:
    """Start the Telegram bot.

    Returns the Application so the caller can await its shutdown.
    Returns None if TELEGRAM_TOKEN is not set.
    """
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        logger.warning("TELEGRAM_TOKEN not set — Telegram will not start")
        return None

    handler = TelegramHandler(router)
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler))

    async def _start():
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logger.info("Telegram bot started")

    asyncio.get_event_loop().create_task(_start())

    return app
