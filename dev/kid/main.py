"""
Haven — KID's safe haven fallback system.

Entry point that wires up tools, providers, and all transports
(Terminal + Discord + Telegram) concurrently with graceful shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any
from dotenv import load_dotenv

load_dotenv("/mnt/z/Core/.env")
load_dotenv("/root/.openclaw/env")

from core.tool_decorator import get_default_registry
from core.http_provider import HttpProvider
from core.category_router import CategoryRouter
from core.router import Router
from soul.identity import build_system_prompt
from soul.memory import SessionStore, LongTermMemory
from learning.skill_store import SkillStore
import tools  # noqa: F401 — triggers @tool registration
from transport import run_terminal, run_discord, run_telegram

logger = logging.getLogger(__name__)

PRIMARY_MODEL = os.getenv("HAVEN_PRIMARY_MODEL", "deepseek-v4-flash")
FALLBACK_MODEL = os.getenv("HAVEN_FALLBACK_MODEL", "google/gemma-4-26b-a4b-it")

# Global shutdown event — set when SIGINT/SIGTERM is received
_shutdown_event: asyncio.Event | None = None


def _handle_signal() -> None:
    """Set the shutdown event on signal receipt."""
    global _shutdown_event
    if _shutdown_event is not None and not _shutdown_event.is_set():
        logger.info("Shutdown signal received — stopping Haven...")
        _shutdown_event.set()


async def main() -> None:
    """Boot Haven: init core, start all transports, wait for shutdown."""
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows / some environments don't support add_signal_handler
            pass

    # ── Core ────────────────────────────────────────────────────────
    registry = get_default_registry()
    logger.info("Registered tools: %s", [s.name for s in registry])

    # ── Providers ───────────────────────────────────────────────────
    deepseek = HttpProvider(
        name="DeepSeek",
        model=PRIMARY_MODEL,
        base_url="https://api.deepseek.com/v1/chat/completions",
        api_key_env="DEEPSEEK_API_KEY",
        default_temperature=0.3,
    )
    openrouter = HttpProvider(
        name="OpenRouter",
        model=FALLBACK_MODEL,
        base_url="https://openrouter.ai/api/v1/chat/completions",
        api_key_env="OPENROUTER_API_KEY",
        default_temperature=0.7,
        headers_extra={
            "HTTP-Referer": "https://github.com/openclaw/haven",
            "X-Title": "Haven",
        },
    )
    providers: list[tuple[HttpProvider, str | None]] = [
        (deepseek, None), (openrouter, None)
    ]

    # ── Category Router (Phase 1b) + Ollama vision (Phase 2b) ──────
    cat_router = CategoryRouter()
    try:
        from tools.ollama_provider import create_ollama_provider
        ollama_minicpm = create_ollama_provider(
            model="minicpm-v:latest", name="Ollama-minicpm-v",
        )
        if ollama_minicpm is not None:
            providers.append((ollama_minicpm, None))
            cat_router.set_provider("vision", ollama_minicpm)
            logger.info("Ollama minicpm-v provider ready")
    except Exception as exc:
        logger.debug("Ollama provider skipped: %s", exc)

    # ── Memory (Phase 2a) + Skills (Phase 3) ───────────────────────
    ltm = LongTermMemory()
    skill_store = SkillStore()
    logger.info("Long-term memory: %d entries", len(ltm))
    logger.info("Skills: %d active, %d drafts",
                len(skill_store.get_active()), len(skill_store.get_drafts()))

    # ── System prompt ───────────────────────────────────────────────
    system_prompt = build_system_prompt()
    session_store = SessionStore()
    router = Router(
        registry,
        providers=providers,
        system_prompt=system_prompt,
        session_store=session_store,
        long_term_memory=ltm,         # Phase 2a — memory injection + auto-summarise
        skill_store=skill_store,       # Phase 3 — learned skill injection
        category_router=cat_router,    # Phase 1b — category-aware execution
    )

    # ── Banner ──────────────────────────────────────────────────────
    print("")
    print("=" * 50)
    print("  🏝️  HAVEN — KID Safe Haven")
    print("=" * 50)
    print(f"  Primary:   DeepSeek {PRIMARY_MODEL}")
    print(f"  Fallback:  OpenRouter {FALLBACK_MODEL}")
    print(f"  Tools:     {[s.name for s in registry]}")
    print(f"  Memory:    {len(ltm)} entries")
    print(f"  Skills:    {len(skill_store.get_active())} active, {len(skill_store.get_drafts())} drafts")
    print(f"  Ollama:    nomic-embed-text + minicpm-v {'✅' if ollama_minicpm else '⚠️  offline'}")
    print("=" * 50)
    print("")

    # ── Transports ──────────────────────────────────────────────────
    tasks: list[asyncio.Task] = []

    # Terminal (runs in executor to avoid blocking the event loop)
    tasks.append(asyncio.create_task(run_terminal(router)))

    # Discord (background task)
    discord_task = run_discord(router)
    if discord_task is not None:
        tasks.append(discord_task)

    # Telegram (background) — save reference for shutdown
    telegram_app = run_telegram(router)

    # ── Wait for shutdown signal or task failure ────────────────────
    wait_tasks = [
        asyncio.create_task(_shutdown_event.wait()),
        *tasks,
    ]
    done, pending = await asyncio.wait(
        wait_tasks, return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()

    # ── Graceful shutdown ───────────────────────────────────────────
    # Stop Telegram app (stop updater first, then app, then shutdown)
    if telegram_app is not None:
        try:
            if telegram_app.updater and telegram_app.updater.running:
                await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()
            logger.info("Telegram stopped.")
        except Exception as exc:
            logger.warning("Telegram shutdown error: %s", exc)

    # Cancel transport tasks
    for t in tasks:
        if not t.done():
            t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Close providers
    await deepseek.close()
    await openrouter.close()

    print("\n🛑 Haven shut down gracefully.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Haven shut down (KeyboardInterrupt).")
