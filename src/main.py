"""
Haven — KID's safe haven fallback system.

Entry point that wires up tools, providers, and all transports
(Terminal + Discord + Telegram) concurrently with graceful shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
import signal
import sys

from core.paths import core_env, haven_env, openclaw_env, haven_dir, ltm_dir
from dotenv import load_dotenv

load_dotenv(str(core_env()))
load_dotenv(str(haven_env()), override=True)
load_dotenv(str(openclaw_env()))

import tools  # noqa: E402, F401 — triggers @tool registration (needs .env loaded first)
from core.category_router import CategoryRouter  # noqa: E402
from core.heartbeat import HeartbeatMonitor  # noqa: E402
from core.provider_registry import ProviderRegistry  # noqa: E402
from core.prompt_assembler import SystemPromptAssembler  # noqa: E402
from core.budget import BudgetTracker  # noqa: E402
from core.router import Router  # noqa: E402
from core.task_complexity import TaskComplexityEstimator  # noqa: E402
from core.config import config
from core.tool_decorator import get_default_registry  # noqa: E402
from learning.skill_store import SkillStore  # noqa: E402
from soul.identity import build_system_prompt  # noqa: E402
from soul.memory import LongTermMemory, SessionStore  # noqa: E402
from transport import run_discord, run_telegram, run_terminal  # noqa: E402

logger = logging.getLogger(__name__)

# Global shutdown event — set when SIGINT/SIGTERM is received
_shutdown_event: asyncio.Event | None = None


def _handle_signal() -> None:
    """Set the shutdown event on signal receipt."""
    global _shutdown_event
    if _shutdown_event is not None and not _shutdown_event.is_set():
        logger.info("Shutdown signal received — stopping Haven...")
        _shutdown_event.set()


LOCK_FILE = haven_dir() / "haven.lock"
_lock_fd = None  # kept alive for the process lifetime


def _acquire_instance_lock() -> None:
    """Prevent dual instances via fcntl exclusive lock (atomic, race-free)."""
    global _lock_fd
    _lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _lock_fd.seek(0)
        content = _lock_fd.read().strip()
        print(
            f"Haven is already running (PID {content}). "
            f"Stop it first or remove {LOCK_FILE} if stale.",
            file=sys.stderr,
        )
        sys.exit(1)
    _lock_fd.write(str(os.getpid()))
    _lock_fd.flush()


async def main() -> None:
    """Boot Haven: init core, start all transports, wait for shutdown."""
    _acquire_instance_lock()
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            # Windows / some environments don't support add_signal_handler
            loop.add_signal_handler(sig, _handle_signal)

    # ── Core ──────────────────────────────────────────────────────────────────
    registry = get_default_registry()
    logger.info("Registered tools: %s", [s.name for s in registry])

    # ── MCP Servers ───────────────────────────────────────────────────────────
    from tools.mcp import MCPBridge
    import json
    mcp_bridge = MCPBridge(registry)
    mcp_config_path = haven_dir() / "config" / "mcp_servers.json"
    if mcp_config_path.exists():
        with open(mcp_config_path) as f:
            mcp_servers = json.load(f)
        for server_cfg in mcp_servers:
            names = await mcp_bridge.attach_from_config(server_cfg)
            for name in names:
                logger.info("MCP tool registered: %s", name)
    else:
        logger.debug("No MCP server config found at %s", mcp_config_path)

    # ── Providers ─────────────────────────────────────────────────────────────
    registry_prov = ProviderRegistry.from_toml(
        haven_dir() / "config" / "providers.toml"
    )
    providers = list(registry_prov)
    logger.info("Loaded %d providers", len(providers))

    # ── Category Router (Phase 1b) + Ollama vision (Phase 2b) ──
    cat_router = CategoryRouter()
    registry_prov.setup_category_router(cat_router)
    if registry_prov.get("ollama_vision"):
        logger.info("Ollama minicpm-v provider ready (vision only)")

    # ── Memory (Phase 2a) + Skills (Phase 3) ──────────────────────────────────
    ltm = LongTermMemory()
    skill_store = SkillStore()
    # P5a — bind skill store for on-demand expansion tool
    from tools.skill_tool import set_skill_store
    set_skill_store(skill_store)
    logger.info("Long-term memory: %d entries", len(ltm))
    logger.info("Skills: %d active, %d drafts",
                len(skill_store.get_active()), len(skill_store.get_drafts()))

    # ── Goal Manager (P4d) + Command Handler ──────────────────────────────────
    from core.goal_manager import GoalManager
    goal_manager = GoalManager(storage_path=ltm_dir() / "goals.json")
    from core.command_handler import CommandHandler
    command_handler = CommandHandler(goal_manager)

    # ── System prompt (P4a layered assembler) ─────────────────────────────────
    identity_prompt = build_system_prompt()
    assembler = SystemPromptAssembler(identity_text=identity_prompt)
    # P4d — inject active goals into context after runtime layer
    assembler.register_layer("goals",
        lambda ctx: goal_manager.inject_into_context(),
        after="runtime",
    )
    # ── Task Complexity Estimator (P5b) ───────────────────────────────────────
    complexity_estimator = TaskComplexityEstimator()
    budget_tracker = BudgetTracker()  # 監控模式，無上限

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
        complexity_estimator=complexity_estimator,
        budget_tracker=budget_tracker,
    )

    # ── Restore persisted tasks (Phase 9) ─────────────────────────────────────
    restore_info = await router.restore_tasks()
    if restore_info["restored"] > 0:
        logger.info(
            "Restored %d task records (%d interrupted by restart)",
            restore_info["restored"],
            restore_info["interrupted"],
        )

    # P4d-ext — wire Scheduler into CommandHandler for /cron
    command_handler.set_scheduler(router.scheduler)

    # ── Banner ────────────────────────────────────────────────────────────────
    print("")
    print("=" * 50)
    print("  \U0001f3dd\ufe0f  HAVEN — KID Safe Haven")
    print("=" * 50)
    for key in registry_prov.all_keys:
        provider = registry_prov.get(key)
        category = registry_prov._meta.get(key, {}).get("category", "")
        tag = f" [{category}]" if category else ""
        print(f"  {key}: {provider.get_model()}{tag}")
    print(f"  Tools:     {[s.name for s in registry]}")
    print(f"  Memory:    {len(ltm)} entries")
    print(f"  Skills:    {len(skill_store.get_active())} active, {len(skill_store.get_drafts())} drafts")
    ollama_ok = "\u2705" if registry_prov.get("ollama_vision") else "\u26a0\ufe0f  offline"
    print(f"  Ollama:    nomic-embed-text + minicpm-v {ollama_ok}")
    print("=" * 50)
    print("")

    # ── Scheduler (Phase 7) ───────────────────────────────────────────────────
    await router.start_scheduler()
    logger.info("Scheduler started")

    # ── Transports ────────────────────────────────────────────────────────────
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
    telegram = run_telegram(router, command_handler=command_handler)
    tasks.append(telegram.task)

    # ── Wire scheduler notification → Discord DM / Telegram ───────────────────
    _SCHEDULE_MESSAGES: dict[str, str] = {
        "drink_water_reminder": "💧 該喝水囉！起身走走，補充水分～",
        "squat_reminder": "🦵 該深蹲了！站起來動一動，做個 20 下～",
    }

    _SCHEDULE_DEFAULT_DISCORD_USER = "893743161338396692"

    async def _schedule_notify(name: str, metadata: dict) -> None:
        """Send schedule reminders via Discord DM or Telegram."""
        text = _SCHEDULE_MESSAGES.get(name, f"⏰ **{name}**")
        md = metadata or {}
        discord_user = md.get("discord_dm_user") or _SCHEDULE_DEFAULT_DISCORD_USER
        telegram_chat = md.get("telegram_chat")

        if discord_user:
            try:
                await discord.notify_user(int(discord_user), text)
            except Exception:
                logger.exception("Schedule notify Discord DM failed for %s", name)
        if telegram_chat:
            try:
                await telegram.notify(int(telegram_chat), text)
            except Exception:
                logger.exception("Schedule notify Telegram failed for %s", name)

    router.scheduler.set_notify_handler(_schedule_notify)
    logger.info("Scheduler notification handler wired (Discord DM + Telegram)")

    # ── Heartbeat Monitor ─────────────────────────────────────────────────────
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

    # ── Wait for shutdown signal or task failure ──────────────────────────
    wait_tasks = [
        asyncio.create_task(_shutdown_event.wait()),
        *tasks,
    ]
    done, pending = await asyncio.wait(
        wait_tasks, return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    # Stop Telegram app via handle
    await telegram.shutdown()

    # Cancel transport tasks
    for t in tasks:
        if not t.done():
            t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Close providers
    await registry_prov.close_all()
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
