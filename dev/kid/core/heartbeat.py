"""
Heartbeat monitor for OpenClaw health.

Polls the OpenClaw Gateway health endpoint and notifies callbacks
when it goes down or recovers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from core.config import config

logger = logging.getLogger(__name__)

StatusCallback = Callable[[bool, str], Awaitable[None]]


class HeartbeatMonitor:
    """Poll OpenClaw health endpoint and fire callbacks on status change.

    Down  condition: ``threshold`` consecutive failures (timeout or HTTP >= 500)
    Recovery:        first successful response after being down
    """

    def __init__(
        self,
        health_url: str | None = None,
        interval: float = 30,
        threshold: int = 3,
    ) -> None:
        self._url = health_url or config.heartbeat_url or "http://localhost:18789/"
        self._interval = interval
        self._threshold = threshold
        self._failure_count = 0
        self._is_down = False
        self._callbacks: list[StatusCallback] = []
        self._client: httpx.AsyncClient | None = None

    @property
    def is_down(self) -> bool:
        """True if OpenClaw is currently considered down."""
        return self._is_down

    def on_status_change(self, callback: StatusCallback) -> None:
        """Register an async callback invoked on status transition.

        Signature: ``async def callback(is_down: bool, message: str) -> None``
        """
        self._callbacks.append(callback)

    async def _notify(self, is_down: bool) -> None:
        message = (
            f"OpenClaw 已掉線 — 連續 {self._threshold} 次無法連接 {self._url}"
            if is_down
            else f"OpenClaw 已恢復 — {self._url}"
        )
        logger.warning(message) if is_down else logger.info(message)
        for cb in self._callbacks:
            try:
                await cb(is_down, message)
            except Exception as exc:
                logger.warning("Heartbeat callback failed: %s", exc)

    async def start(self) -> None:
        """Run the polling loop until cancelled."""
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        logger.info(
            "Heartbeat started: url=%s interval=%ds threshold=%d",
            self._url,
            self._interval,
            self._threshold,
        )

        while True:
            await asyncio.sleep(self._interval)

            ok = False
            try:
                resp = await self._client.get(self._url)
                ok = resp.status_code < 500
            except Exception:
                pass

            if ok:
                if self._is_down:
                    self._is_down = False
                    self._failure_count = 0
                    await self._notify(False)
                else:
                    self._failure_count = 0
            else:
                self._failure_count += 1
                if not self._is_down and self._failure_count >= self._threshold:
                    self._is_down = True
                    await self._notify(True)

    async def close(self) -> None:
        """Clean up the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
