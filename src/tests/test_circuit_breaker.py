"""
Tests for core/circuit_breaker.py — CircuitBreaker state machine.

Unit tests: pure logic, no async, no external deps.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitStates:
    """State machine transitions."""

    def test_initial_state_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_closed_allow_request(self):
        cb = CircuitBreaker(name="test")
        assert cb.allow_request() is True

    def test_threshold_opens_circuit(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_below_threshold_stays_closed(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_open_blocks_requests(self):
        cb = CircuitBreaker(name="test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_open_transitions_to_half_open_after_cooldown(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, cooldown_seconds=5.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Simulate cooldown expiry
        cb._last_failure_time = time.monotonic() - 6.0

        assert cb.allow_request() is True  # triggers HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_probe_success_returns_to_closed(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, cooldown_seconds=1.0)
        cb.record_failure()
        cb.record_failure()

        # Force HALF_OPEN manually
        cb._state = CircuitState.HALF_OPEN

        assert cb.allow_request() is True  # probe allowed

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_probe_failure_reopens(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, cooldown_seconds=1.0)
        cb.record_failure()
        cb.record_failure()

        # Force HALF_OPEN
        cb._state = CircuitState.HALF_OPEN

        cb.record_failure()  # probe fails → back to OPEN
        assert cb.state == CircuitState.OPEN

    def test_success_in_open_still_resets(self):
        """Success should close the circuit even if called from OPEN state."""
        cb = CircuitBreaker(name="test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_cooldown_not_expired_stays_open(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, cooldown_seconds=30.0)
        cb.record_failure()

        assert cb.allow_request() is False  # not enough time passed

    def test_failure_count_tracking(self):
        cb = CircuitBreaker(name="test", failure_threshold=10)
        for i in range(7):
            cb.record_failure()
        assert cb.failure_count == 7


class TestReset:
    """Manual reset."""

    def test_reset_from_open(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_reset_idempotent(self):
        cb = CircuitBreaker(name="test")
        cb.reset()  # already closed
        assert cb.state == CircuitState.CLOSED


class TestConfig:
    """Constructor defaults and edge cases."""

    def test_default_threshold(self):
        cb = CircuitBreaker(name="test")
        assert cb.failure_threshold == 3

    def test_default_cooldown(self):
        cb = CircuitBreaker(name="test")
        assert cb.cooldown_seconds == 30.0

    def test_zero_threshold_opens_immediately(self):
        cb = CircuitBreaker(name="test", failure_threshold=0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_name_stored(self):
        cb = CircuitBreaker(name="DeepSeek")
        assert cb.name == "DeepSeek"
