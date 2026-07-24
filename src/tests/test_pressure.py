"""
Tests for core/resource_gate.py — PressureLevel, ResourceMonitor cache, Chunker.

Unit tests: pure logic, no real RAM/disk requirements.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.resource_gate import Chunker, PressureLevel, ResourceMonitor


class TestPressureLevel:
    """PressureLevel enum and from_percent()."""

    def test_values(self):
        assert PressureLevel.GREEN == 0
        assert PressureLevel.YELLOW == 1
        assert PressureLevel.RED == 2
        assert PressureLevel.CRITICAL == 3

    def test_is_int_enum(self):
        assert issubclass(PressureLevel, int)

    def test_from_percent_green(self):
        for pct in [0, 10, 49, 49.9]:
            assert PressureLevel.from_percent(pct) == PressureLevel.GREEN

    def test_from_percent_yellow(self):
        for pct in [50, 60, 69, 69.9]:
            assert PressureLevel.from_percent(pct) == PressureLevel.YELLOW

    def test_from_percent_red(self):
        for pct in [70, 75, 84, 84.9]:
            assert PressureLevel.from_percent(pct) == PressureLevel.RED

    def test_from_percent_critical(self):
        for pct in [85, 90, 99, 100]:
            assert PressureLevel.from_percent(pct) == PressureLevel.CRITICAL

    def test_from_percent_boundaries(self):
        """Exact boundary values — inclusive on the lower side."""
        assert PressureLevel.from_percent(50) == PressureLevel.YELLOW
        assert PressureLevel.from_percent(70) == PressureLevel.RED
        assert PressureLevel.from_percent(85) == PressureLevel.CRITICAL


class TestResourceMonitor:
    """ResourceMonitor cache behaviour."""

    def test_psutil_available_flag(self):
        """_psutil_available is a known class var."""
        assert hasattr(ResourceMonitor, "_psutil_available")

    def test_cache_ttl_exists(self):
        assert ResourceMonitor.CACHE_TTL == 2.0

    def test_psutil_unavailable_fallback(self):
        """When psutil is not available, should not crash."""
        with patch.object(ResourceMonitor, "_psutil_available", False):
            level = ResourceMonitor.check_ram()
            assert level == PressureLevel.GREEN

    def test_cache_returns_cached_value(self):
        """After first call, _ram_cache is populated."""
        with patch.object(ResourceMonitor, "_ram_cache", None):
            with patch.object(ResourceMonitor, "_ram_cache_ts", 0.0):
                with patch.object(ResourceMonitor, "_psutil_available", False):
                    level1 = ResourceMonitor.check_ram()
                    level2 = ResourceMonitor.check_ram()
                    # Both should be GREEN (psutil unavailable fn returns GREEN)
                    assert level1 == level2 == PressureLevel.GREEN

    def test_cache_skipped_when_none(self):
        """When _ram_cache is None, should run fresh check."""
        with patch.object(ResourceMonitor, "_ram_cache", None):
            with patch.object(ResourceMonitor, "_ram_cache_ts", 0.0):
                with patch.object(ResourceMonitor, "_psutil_available", False):
                    level = ResourceMonitor.check_ram()
                    assert level == PressureLevel.GREEN

    def test_disk_check_defaults(self):
        """check_disk without psutil returns under-threshold."""
        with patch.object(ResourceMonitor, "_psutil_available", False):
            ok, pct = ResourceMonitor.check_disk()
            assert ok is True
            assert pct == 0.0


class TestChunker:
    """Chunker — split large data lists into manageable chunks."""

    def test_chunk_small_data(self):
        """Data under chunk_size → single chunk."""
        data = ["x"] * 3
        chunks = list(Chunker.iter_chunks(data, chunk_size=10))
        assert len(chunks) == 1
        assert chunks[0] == ["x", "x", "x"]

    def test_chunk_exact_size(self):
        """Data exactly chunk_size → single chunk."""
        data = list(range(10))
        chunks = list(Chunker.iter_chunks(data, chunk_size=10))
        assert len(chunks) == 1

    def test_chunk_large_data(self):
        """Data over chunk_size → multiple chunks."""
        data = list(range(25))
        chunks = list(Chunker.iter_chunks(data, chunk_size=10))
        assert len(chunks) == 3
        assert len(chunks[0]) == 10
        assert len(chunks[1]) == 10
        assert len(chunks[2]) == 5

    def test_chunk_single_element(self):
        """Each chunk has at most chunk_size elements."""
        data = list(range(7))
        chunks = list(Chunker.iter_chunks(data, chunk_size=3))
        assert len(chunks) == 3
        assert chunks[0] == [0, 1, 2]
        assert chunks[1] == [3, 4, 5]
        assert chunks[2] == [6]

    def test_chunk_empty_data(self):
        """Empty input → empty output."""
        chunks = list(Chunker.iter_chunks([], chunk_size=10))
        assert len(chunks) == 0

    def test_chunk_default_size(self):
        """Default chunk_size is 5000."""
        data = list(range(5001))
        chunks = list(Chunker.iter_chunks(data))
        assert len(chunks) == 2
        assert len(chunks[0]) == 5000
        assert len(chunks[1]) == 1

    def test_chunk_generator(self):
        """iter_chunks is a generator — lazy."""
        gen = Chunker.iter_chunks(["x"] * 100, chunk_size=10)
        assert hasattr(gen, "__next__")
