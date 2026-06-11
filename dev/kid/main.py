"""
Haven — KID's safe haven fallback system.

Entry point that wires up tools, providers, and all transports
(Terminal + Discord + Telegram) concurrently with graceful shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal

from core.paths import core_env, haven_env, openclaw_env, ltm_dir
from dotenv import load_dotenv

load_dotenv(str(core_env()))
load_dotenv(str(haven_env()), override=True)
load_dotenv(str(openclaw_env()))

import tools  # noqa: E402, F401 — triggers @tool registration (needs .env loaded first)
from core.category_router import CategoryRouter  # noqa: E402
from core.heartbeat import HeartbeatMonitor  # noqa: E402
from core.http_provider import HttpProvider  # noqa: E402
from core.prompt_assembler import SystemPromptAssembler  # noqa: E402
from core.router import Router  # noqa: E402
from core.config import config
from core.tool_decorator import get_default_registry  # noqa: E402
from learning.skill_store import SkillStore  # noqa: E402
from soul.identity import build_system_prompt  # noqa: E402
from soul.memory import LongTermMemory, SessionStore  # noqa: E402
from transport import run_discord, run_telegram, run_terminal  # noqa: E402

logger = logging.getLogger(__name__)

PRIMARY_MODEL = config.primary_model
FALLBACK_MODEL = config.fallback_model
TERTIARY_MODEL = config.tertiary_model

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
        with contextlib.suppress(NotImplementedError):
            # Windows / some environments don't support add_signal_handler
            loop.add_signal_handler(sig, _handle_signal)

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
    # ── ARK / BytePlus 備用 (tertiary) ───────────────────────────
    ark_provider = None
    if os.getenv("ARK_API_KEY"):  # secret, stays in env
        ark_provider = HttpProvider(
            name="Ark",
            model=TERTIARY_MODEL,
            base_url="https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions",
            api_key_env="ARK_API_KEY",
            default_temperature=0.3,
        )

    providers: list[tuple[HttpProvider, str | None]] = [
        (deepseek, None),
        (openrouter, None),
    ]
    if ark_provider:
        providers.append((ark_provider, None))

    # ── Category Router (Phase 1b) + Ollama vision (Phase 2b) ──────
    cat_router = CategoryRouter()
    try:
        from tools.ollama_provider import create_ollama_provider
        ollama_minicpm = create_ollama_provider(
            model="minicpm-v:latest", name="Ollama-minicpm-v",
        )
        if ollama_minicpm is not None:
            cat_router.set_provider("vision", ollama_minicpm)
            logger.info("Ollama minicpm-v provider ready (vision only)")
    except Exception as exc:
        logger.debug("Ollama provider skipped: %s", exc)

    # ── Memory (Phase 2a) + Skills (Phase 3) ───────────────────────
    ltm = LongTermMemory()
    skill_store = SkillStore()
    # P5a — bind skill store for on-demand expansion tool
    from tools.skill_tool import set_skill_store
    set_skill_store(skill_store)
    logger.info("Long-term memory: %d entries", len(ltm))
    logger.info("Skills: %d active, %d drafts",
                len(skill_store.get_active()), len(skill_store.get_drafts()))

    # ── Goal Manager (P4d) + Command Handler ───────────────────────
    from core.goal_manager import GoalManager
    goal_manager = GoalManager(storage_path=ltm_dir() / "goals.json")
    from core.command_handler import CommandHandler
    command_handler = CommandHandler(goal_manager)

    # ── System prompt (P4a layered assembler) ───────────────────────
    identity_prompt = build_system_prompt()
    assembler = SystemPromptAssembler(identity_text=identity_prompt)
    # P4d — inject active goals into context after runtime layer
    assembler.register_layer("goals",
        lambda ctx: goal_manager.inject_into_context(),
        after="runtime",
    )
    session_store = SessionStore()
    transports = []
    if config.discord_token:
        transports.append("Discord")
    if config.telegram_token:
        transports.append("Telegram")

    router = Router(
        registry,
        providers=providers,
        prompt_assembler=assembler,
        session_store=session_store,
        long_term_memory=ltm,         # Phase 2a — memory injection + auto-summarise
        skill_store=skill_store,       # Phase 3 — learned skill injection
        category_router=cat_router,    # Phase 1b — category-aware execution
        transport_names=transports,
    )

    # ── Restore persisted tasks (Phase 9) ─────────────────────────
    restore_info = await router.restore_tasks()
    if restore_info["restored"] > 0:
        logger.info(
            "Restored %d task records (%d interrupted by restart)",
            restore_info["restored"],
            restore_info["interrupted"],
        )

    # P4d-ext — wire Scheduler into CommandHandler for /cron
    command_handler.set_scheduler(router.scheduler)

    # ── Banner ──────────────────────────────────────────────────────
    print("")
    print("=" * 50)
    print("  🏝️  HAVEN — KID Safe Haven")
    print("=" * 50)
    print(f"  Primary:   DeepSeek {PRIMARY_MODEL}")
    print(f"  Fallback:  OpenRouter {FALLBACK_MODEL}")
    if ark_provider:
        print(f"  Tertiary:  Ark {ark_provider.get_model()}")
    print(f"  Tools:     {[s.name for s in registry]}")
    print(f"  Memory:    {len(ltm)} entries")
    print(f"  Skills:    {len(skill_store.get_active())} active, {len(skill_store.get_drafts())} drafts")
    print(f"  Ollama:    nomic-embed-text + minicpm-v {'✅' if ollama_minicpm else '⚠️  offline'}")
    print("=" * 50)
    print("")

    # ── Scheduler (Phase 7) ───────────────────────────────────────
    await router.start_scheduler()
    logger.info("Scheduler started")

    # ── Transports ──────────────────────────────────────────────────
    tasks: list[asyncio.Task] = []

    # Terminal (only when stdin is interactive)
    if not config.no_terminal:
        tasks.append(asyncio.create_task(run_terminal(router)))
    else:
        logger.info("Terminal skipped (background mode)")

    # Discord (background task) — returns handle for notifications
    discord = run_discord(router, command_handler=command_handler)
    tasks.append(discord.task)

    # Telegram (background) — returns handle for notifications + shutdown
    # NOTE: run_telegram starts polling in a background task that completes
    # quickly — lifecycle is managed via telegram.shutdown(), not task tracking.
    telegram = run_telegram(router, command_handler=command_handler)

    # ── Heartbeat Monitor ──────────────────────────────────────────
    heartbeat = HeartbeatMonitor(
        interval=config.heartbeat_interval,
        threshold=config.heartbeat_threshold,
    )
    notify_discord_ch = config.heartbeat_discord_channel
    notify_discord_user = config.heartbeat_discord_user
    notify_telegram_chat = config.heartbeat_telegram_chat

    async def _heartbeat_notify(is_down: bool, message: str) -> None:
        """Notify via Haven's own channels using transport handles."""
        if notify_discord_user:
            await discord.notify_user(notify_discord_user, message)
        elif notify_discord_ch:
            await discord.notify(notify_discord_ch, message)
        if notify_telegram_chat:
            await telegram.notify(notify_telegram_chat, message)

    heartbeat.on_status_change(_heartbeat_notify)
    tasks.append(asyncio.create_task(heartbeat.start()))

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
    # Stop Telegram app via handle
    await telegram.shutdown()

    # Cancel transport tasks
    for t in tasks:
        if not t.done():
            t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Close providers
    await deepseek.close()
    await openrouter.close()
    await heartbeat.close()
    await router.close_scheduler()
    await router.task_manager.close()

    print("\n🛑 Haven shut down gracefully.")


if __name__ == "__main__":
    # ── Logging: file + console ──
    from core.paths import log_file as _log_file
    LOG_FILE = str(_log_file())
    handlers: list = [logging.FileHandler(LOG_FILE, mode="w")]
    if not config.no_terminal:
        handlers.insert(0, logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=handlers,
    )
    # Structured format for file handler (always last in handlers list)
    file_handler = handlers[-1]
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
                          datefmt="%H:%M:%S")
    )
    file_handler.setLevel(logging.INFO)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Haven shut down (KeyboardInterrupt).")
