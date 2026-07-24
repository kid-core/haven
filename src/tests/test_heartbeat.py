"""
Tests for HeartbeatMonitor — core/heartbeat.py.

Exercises state transitions (alive→down→alive), threshold counting,
and callback invocation.
"""

from __future__ import annotations

import pytest
from core.heartbeat import HeartbeatMonitor


class TestHeartbeatStateMachine:
    """Test the state logic directly — no async loop."""

    def test_starts_alive(self) -> None:
        monitor = HeartbeatMonitor("http://test/", interval=30, threshold=3)
        assert monitor.is_down is False

    def test_goes_down_after_threshold(self) -> None:
        monitor = HeartbeatMonitor("http://test/", interval=30, threshold=3)
        # Simulate 3 consecutive failures
        monitor._failure_count = 3
        monitor._is_down = True
        assert monitor.is_down is True

    def test_stays_alive_below_threshold(self) -> None:
        monitor = HeartbeatMonitor("http://test/", interval=30, threshold=3)
        monitor._failure_count = 2
        assert monitor.is_down is False

    def test_resets_on_success(self) -> None:
        monitor = HeartbeatMonitor("http://test/", interval=30, threshold=3)
        monitor._is_down = True
        monitor._failure_count = 3
        # A successful ping resets everything
        monitor._is_down = False
        monitor._failure_count = 0
        assert monitor.is_down is False
        assert monitor._failure_count == 0


class TestHeartbeatCallbacks:
    """Test callback registration and invocation."""

    @pytest.mark.asyncio
    async def test_registers_and_fires(self) -> None:
        monitor = HeartbeatMonitor("http://test/", interval=30, threshold=3)
        called: list[tuple[bool, str]] = []

        def cb(is_down: bool, msg: str) -> None:
            called.append((is_down, msg))

        monitor.on_status_change(cb)  # type: ignore[arg-type]
        await monitor._notify(True)
        assert len(called) == 1
        assert called[0][0] is True

    @pytest.mark.asyncio
    async def test_multiple_callbacks(self) -> None:
        monitor = HeartbeatMonitor("http://test/", interval=30, threshold=3)
        results: list[bool] = []

        def cb1(d: bool, _: str) -> None:
            results.append(d)

        def cb2(d: bool, _: str) -> None:
            results.append(d)

        monitor.on_status_change(cb1)  # type: ignore[arg-type]
        monitor.on_status_change(cb2)  # type: ignore[arg-type]
        await monitor._notify(False)
        assert results == [False, False]
