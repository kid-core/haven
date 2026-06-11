"""
Circuit breaker for provider calls.

State machine:
    CLOSED        — normal operation, calls pass through
    OPEN          — failures exceeded threshold, calls are skipped
    HALF_OPEN     — after cooldown, one probe call is allowed

After a successful probe → back to CLOSED
After a failed probe   → back to OPEN (reset cooldown counter)
"""

from __future__ import annotations

import logging
import time
from enum import Enum, auto
from typing import Protocol

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreaker:
    """Per-provider circuit breaker.

    Example
    -------
    >>> cb = CircuitBreaker(name="DeepSeek", failure_threshold=3, cooldown_seconds=30)
    >>> if cb.allow_request():
    ...     try:
    ...         result = await provider.chat_completion(...)
    ...         cb.record_success()
    ...     except Exception:
    ...         cb.record_failure()
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    # ── Public API ────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def allow_request(self) -> bool:
        """Check whether a request should be sent to this provider.

        CLOSED  → True (let through)
        OPEN    → False (skip), unless cooldown expired → transition to HALF_OPEN
        HALF_OPEN → True (probe)
        """
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.cooldown_seconds:
                logger.info(
                    "Circuit %s: OPEN → HALF_OPEN (cooldown %ss elapsed)",
                    self.name,
                    round(elapsed, 1),
                )
                self._state = CircuitState.HALF_OPEN
                return True
            return False

        # HALF_OPEN — allow one probe
        return True

    def record_success(self) -> None:
        """Call after a successful provider request."""
        if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            logger.info(
                "Circuit %s: %s → CLOSED (probe succeeded)",
                self.name,
                self._state.name,
            )
        self._state = CircuitState.CLOSED
        self._failure_count = 0

    def record_failure(self) -> None:
        """Call after a failed provider request."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._failure_count >= self.failure_threshold:
            if self._state != CircuitState.OPEN:
                logger.warning(
                    "Circuit %s: %s → OPEN (%d failures)",
                    self.name,
                    self._state.name,
                    self._failure_count,
                )
                self._state = CircuitState.OPEN
        else:
            if self._state == CircuitState.HALF_OPEN:
                logger.warning(
                    "Circuit %s: HALF_OPEN → OPEN (probe failed, %d total)",
                    self.name,
                    self._failure_count,
                )
                self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Force reset to CLOSED (e.g. manual intervention)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        logger.info("Circuit %s: manually reset to CLOSED", self.name)


# ── Protocol for dependency injection ──────────────────────────

class BreakerProtocol(Protocol):
    """Minimal interface Router uses — makes testing trivial."""

    @property
    def name(self) -> str: ...

    @property
    def state(self) -> CircuitState: ...

    def allow_request(self) -> bool: ...

    def record_success(self) -> None: ...

    def record_failure(self) -> None: ...
