"""
Minimal observability — trace_id per request, timing per operation.

Usage
-----
    tracer = Tracer()
    with tracer.span("provider_call", provider="DeepSeek"):
        result = await provider.chat_completion(...)

    # Later
    report = tracer.summary()  # dict with timing breakdown

Can be injected into Router via tracer= kwarg.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Span:
    """A single timed operation within a trace."""

    name: str
    start: float
    end: float | None = None
    tags: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        if self.end is None:
            return 0.0
        return round((self.end - self.start) * 1000, 1)

    @property
    def is_complete(self) -> bool:
        return self.end is not None


class Tracer:
    """Per-request tracer.

    Example
    -------
    >>> tracer = Tracer()
    >>> with tracer.span("user_message"):
    ...     with tracer.span("provider", provider="DeepSeek", model="v4"):
    ...         ...
    >>> print(tracer.summary())
    """

    def __init__(self) -> None:
        self.trace_id: str = ""
        self._spans: list[Span] = []
        self._active: list[Span] = []

    def start(self) -> str:
        """Begin a new trace. Returns trace_id."""
        self.trace_id = uuid.uuid4().hex[:12]
        self._spans.clear()
        self._active.clear()
        return self.trace_id

    @contextmanager
    def span(self, name: str, **tags: Any) -> Any:
        """Time a named operation.

        Usage:
            with tracer.span("provider", provider="DeepSeek"):
                ...
        """
        span = Span(name=name, start=time.monotonic(), tags=tags)
        self._active.append(span)
        self._spans.append(span)

        try:
            yield
        except Exception as exc:
            span.error = str(exc)
            logger.warning(
                "[%s] span %s failed: %s",
                self.trace_id, name, exc,
            )
            raise
        finally:
            self._active.pop()
            span.end = time.monotonic()

    def set_tag(self, key: str, value: Any) -> None:
        """Tag the current (innermost) active span."""
        if self._active:
            self._active[-1].tags[key] = value

    def summary(self) -> dict[str, Any]:
        """Compile a structured summary of this trace.

        Returns
        -------
        {
            "trace_id": "...",
            "total_ms": float,
            "spans": [
                {"name": "...", "duration_ms": ..., "tags": {...}},
            ],
            "by_name": {"provider": {"count": N, "total_ms": float, ...}},
        }
        """
        total_ms = 0.0
        by_name: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "total_ms": 0.0, "errors": 0}
        )

        spans_out: list[dict] = []
        for s in self._spans:
            d = s.duration_ms
            total_ms += d
            spans_out.append({
                "name": s.name,
                "duration_ms": d,
                "tags": dict(s.tags),
                "error": s.error,
            })
            bn = by_name[s.name]
            bn["count"] += 1
            bn["total_ms"] = round(bn["total_ms"] + d, 1)
            if s.error is not None:
                bn["errors"] += 1

        return {
            "trace_id": self.trace_id,
            "total_ms": round(total_ms, 1),
            "spans": spans_out,
            "by_name": dict(by_name),
        }

    def log_summary(self) -> None:
        """Log the full summary at INFO level."""
        s = self.summary()
        parts = [
            f"[{s['trace_id']}] total={s['total_ms']}ms",
        ]
        for name, stats in sorted(s["by_name"].items()):
            err = f" err={stats['errors']}" if stats["errors"] else ""
            parts.append(f"  {name}: {stats['count']}x {stats['total_ms']}ms{err}")
        logger.info("\n".join(parts))
