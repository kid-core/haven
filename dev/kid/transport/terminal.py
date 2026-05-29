"""
Terminal transport for Haven.

Simple REPL that reads user input and prints responses.
Runs in a thread executor so it doesn't block the asyncio event loop.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.router import Router


async def _async_input(prompt: str = "") -> str:
    """Async wrapper around ``input()``, runs in a thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, input, prompt)


async def run_terminal(router: "Router") -> None:
    """REPL: read input, call router.process(), print response."""
    session_id = "terminal"
    print("🏝️  Haven Terminal (type 'exit' to quit)")
    print("    Discord + Telegram are also active.\n")

    while True:
        try:
            user_input = await _async_input("Cris> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        text = user_input.strip()
        if not text:
            continue
        if text.lower() in ("exit", "quit"):
            break

        response = await router.process(text, session_id=session_id)
        print(f"\n🏝️ {response}\n")

    print("👋 Terminal session ended.")
