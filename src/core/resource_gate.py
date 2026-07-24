"""
Resource Gate — Pre-flight RAM/disk checks, chunked processing,
task complexity estimation, crash journal, and a decorator gate.

Pillars: SRP (one concern per class), TDD-Lite, composition over inheritance,
dict dispatch, guard clauses.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import time
from collections.abc import Callable, Generator
from enum import IntEnum
from typing import Any, ClassVar

from .exceptions import ResourceBusyError
from .task_complexity import TaskComplexityEstimator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PressureLevel
# ---------------------------------------------------------------------------


class PressureLevel(IntEnum):
    """System resource pressure levels.

    GREEN    = <50%   — normal
    YELLOW   = 50-70% — caution
    RED      = 70-85% — delay/retry
    CRITICAL = >=85%  — reject
    """

    GREEN = 0
    YELLOW = 1
    RED = 2
    CRITICAL = 3

    @staticmethod
    def from_percent(pct: float) -> PressureLevel:
        if pct < 50:
            return PressureLevel.GREEN
        if pct < 70:
            return PressureLevel.YELLOW
        if pct < 85:
            return PressureLevel.RED
        return PressureLevel.CRITICAL


# ---------------------------------------------------------------------------
# ResourceMonitor
# ---------------------------------------------------------------------------

_psutil_available: bool
try:
    import psutil  # noqa: F811
    _psutil_available = True
except ImportError:
    _psutil_available = False
    psutil = None  # type: ignore[assignment]


class ResourceMonitor:
    """Static resource checks with short-lived caching.

    All methods are static/class-level — no instantiation needed.
    """

    _ram_cache: ClassVar[PressureLevel | None] = None
    _ram_cache_ts: ClassVar[float] = 0.0
    _psutil_available: ClassVar[bool] = _psutil_available

    CACHE_TTL: ClassVar[float] = 2.0  # seconds
    DISK_PERCENT_THRESHOLD: ClassVar[float] = 90.0

    @staticmethod
    def check_ram() -> PressureLevel:
        """Return current RAM pressure level with 1-2s caching."""
        now = time.monotonic()
        if (
            ResourceMonitor._ram_cache is not None
            and now - ResourceMonitor._ram_cache_ts < ResourceMonitor.CACHE_TTL
        ):
            return ResourceMonitor._ram_cache

        if not ResourceMonitor._psutil_available:
            logger.warning("psutil not installed — ResourceMonitor defaulting to GREEN")
            ResourceMonitor._ram_cache = PressureLevel.GREEN
            ResourceMonitor._ram_cache_ts = now
            return PressureLevel.GREEN

        try:
            pct = psutil.virtual_memory().percent  # type: ignore[union-attr]
        except Exception:
            logger.exception("psutil.virtual_memory() failed — defaulting to GREEN")
            ResourceMonitor._ram_cache = PressureLevel.GREEN
            ResourceMonitor._ram_cache_ts = now
            return PressureLevel.GREEN

        level = PressureLevel.from_percent(pct)
        ResourceMonitor._ram_cache = level
        ResourceMonitor._ram_cache_ts = now
        return level

    @staticmethod
    def check_disk(path: str = "/mnt/z") -> tuple[bool, float]:
        """Return (under_90_percent, usage_pct)."""
        if not ResourceMonitor._psutil_available:
            logger.warning("psutil not installed — disk check defaulting to under-threshold")
            return True, 0.0

        try:
            usage_pct = ResourceMonitor._disk_usage(path).percent
        except (FileNotFoundError, PermissionError):
            logger.warning("Disk path %r not accessible — defaulting to under-threshold", path)
            return True, 0.0
        except Exception:
            logger.exception("disk_usage(%r) failed — defaulting to under-threshold", path)
            return True, 0.0

        return usage_pct < ResourceMonitor.DISK_PERCENT_THRESHOLD, usage_pct

    @staticmethod
    def _disk_usage(path: str) -> Any:
        """Thin wrapper for testability — delegates to psutil."""
        return psutil.disk_usage(path)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------


class Chunker:
    """Data-aware chunking with inter-chunk RAM re-checks."""

    @staticmethod
    def iter_chunks(data: list[Any], chunk_size: int = 5000) -> Generator[list[Any], None, None]:
        """Yield data in chunks of at most *chunk_size* items."""
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]

    @staticmethod
    async def process_chunks(
        data: list[Any],
        callback: Callable[[list[Any]], Any],
        chunk_size: int = 5000,
    ) -> None:
        """Process *data* in chunks, calling *callback* per chunk.

        RAM is re-checked before every chunk; CRITICAL raises ResourceBusyError.
        """
        for chunk in Chunker.iter_chunks(data, chunk_size):
            ram = ResourceMonitor.check_ram()
            if ram == PressureLevel.CRITICAL:
                raise ResourceBusyError(
                    f"RAM pressure CRITICAL ({ram.name}); chunked processing aborted."
                )
            result = callback(chunk)
            if inspect.isawaitable(result):
                await result


# ---------------------------------------------------------------------------
# resource_gate decorator
# ---------------------------------------------------------------------------

MB = 1_024 * 1_024
_10MB = 10 * MB


def resource_gate(
    min_ram_gate: PressureLevel = PressureLevel.RED,
    chunk_threshold_bytes: int = _10MB,
    chunk_threshold_lines: int = 5000,
    auto_estimate: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: pre-flight RAM gate + optional complexity estimate + auto-chunking.

    1. Pre-flight RAM check for CRITICAL → raise ResourceBusyError
    2. If RAM >= min_ram_gate → 3s delay + one retry, raise on persist
    3. auto_estimate=True → inspect first str arg with TaskComplexityEstimator
    4. Execute the function
    5. If data exceeds threshold → auto-chunk via Chunker
    """

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        sig = inspect.signature(fn)

        # Determine which positional parameter acts as the "data" argument
        # for auto-chunking.
        param_names = list(sig.parameters.keys())
        _data_param: str | None = None
        for name in param_names:
            if any(kw in name.lower() for kw in ("data", "items", "lines", "batch")):
                _data_param = name
                break
        if _data_param is None and param_names:
            _data_param = param_names[0]

        # ── inner helpers ───────────────────────────────────────────

        def _gate_check() -> None:
            ram = ResourceMonitor.check_ram()
            if ram == PressureLevel.CRITICAL:
                raise ResourceBusyError(f"RAM at {ram.name} — task queued or rejected.")
            if ram < min_ram_gate:
                return
            # RAM >= min_ram_gate: delay + retry once
            logger.warning("resource_gate: RAM at %s — waiting 3s then retry", ram.name)
            time.sleep(3)
            ram2 = ResourceMonitor.check_ram()
            if ram2 >= min_ram_gate:
                raise ResourceBusyError(
                    f"RAM still at {ram2.name} after retry — task queued or rejected."
                )

        def _estimate_if_needed(given_args: tuple[Any, ...]) -> None:
            if not auto_estimate:
                return
            if given_args and isinstance(given_args[0], str):
                goal = given_args[0]
                estimator = TaskComplexityEstimator()
                turns = estimator.estimate_turns(goal)
                logger.info("resource_gate: estimated %d turns for goal=%r", turns, goal)

        def _should_chunk(data: list[Any] | str | None) -> bool:
            if data is None:
                return False
            if isinstance(data, str):
                data_bytes = len(data.encode("utf-8"))
                line_count = len(data.splitlines())
                return data_bytes > chunk_threshold_bytes or line_count > chunk_threshold_lines
            if isinstance(data, list):
                data_bytes = _approx_size_bytes(data)
                line_count = len(data)
                return data_bytes > chunk_threshold_bytes or line_count > chunk_threshold_lines
            return False

        def _approx_size_bytes(data: list[Any]) -> int:
            try:
                s = json.dumps(data, default=str, ensure_ascii=False)
                return len(s.encode("utf-8"))
            except (TypeError, ValueError):
                return 0

        def _resolve_data_arg(
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
        ) -> tuple[Any | None, int]:
            if _data_param is not None and _data_param in kwargs:
                return kwargs[_data_param], -1
            params = list(sig.parameters.items())
            for idx, (pname, _param) in enumerate(params):
                if idx < len(args) and pname == _data_param:
                    return args[idx], idx
            return None, -1

        def _replace_data_in_args(args: tuple[Any, ...], idx: int, new_value: Any) -> tuple[Any, ...]:
            lst = list(args)
            lst[idx] = new_value
            return tuple(lst)

        def _run_with_chunking(
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
        ) -> Any:
            data_val, data_idx = _resolve_data_arg(args, kwargs)
            if not _should_chunk(data_val):
                return fn(*args, **kwargs)
            if _data_param is None:
                return fn(*args, **kwargs)

            chunks = list(Chunker.iter_chunks(data_val, chunk_threshold_lines))
            results: list[Any] = []
            for chunk in chunks:
                ram = ResourceMonitor.check_ram()
                if ram == PressureLevel.CRITICAL:
                    raise ResourceBusyError("RAM at CRITICAL during chunked processing — aborting.")
                if data_idx >= 0:
                    new_args = _replace_data_in_args(args, data_idx, chunk)
                    results.append(fn(*new_args, **kwargs))
                else:
                    chunk_kwargs = {**kwargs, _data_param: chunk}
                    results.append(fn(*args, **chunk_kwargs))

            if results and all(isinstance(r, list) for r in results):
                combined: list[Any] = []
                for r in results:
                    combined.extend(r)
                return combined
            return results

        async def _run_async_with_chunking(
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
        ) -> Any:
            data_val, data_idx = _resolve_data_arg(args, kwargs)
            if not _should_chunk(data_val):
                return await fn(*args, **kwargs)
            if _data_param is None:
                return await fn(*args, **kwargs)

            chunks = list(Chunker.iter_chunks(data_val, chunk_threshold_lines))
            results: list[Any] = []
            for chunk in chunks:
                ram = ResourceMonitor.check_ram()
                if ram == PressureLevel.CRITICAL:
                    raise ResourceBusyError("RAM at CRITICAL during chunked processing — aborting.")
                if data_idx >= 0:
                    new_args = _replace_data_in_args(args, data_idx, chunk)
                    results.append(await fn(*new_args, **kwargs))
                else:
                    chunk_kwargs = {**kwargs, _data_param: chunk}
                    results.append(await fn(*args, **chunk_kwargs))

            if results and all(isinstance(r, list) for r in results):
                combined: list[Any] = []
                for r in results:
                    combined.extend(r)
                return combined
            return results

        # ── wrapper dispatch ───────────────────────────────────────

        @functools.wraps(fn)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            _gate_check()
            _estimate_if_needed(args)
            return _run_with_chunking(args, kwargs)

        @functools.wraps(fn)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            _gate_check()
            _estimate_if_needed(args)
            return await _run_async_with_chunking(args, kwargs)

        if inspect.iscoroutinefunction(fn):
            return _async_wrapper
        return _sync_wrapper

    return _decorator
