"""
Tests for core/tracer.py — Tracer span timing, summary, error tracking.
"""

from __future__ import annotations

import logging
import time

import pytest

from core.tracer import Span, Tracer


class TestSpan:
    """Span dataclass — timing mechanics."""

    def test_duration_zero_when_not_complete(self):
        span = Span(name="test", start=100.0)
        assert span.duration_ms == 0.0

    def test_duration_calculated_when_complete(self):
        span = Span(name="test", start=100.0, end=101.5)
        assert span.duration_ms == 1500.0

    def test_is_complete_false(self):
        span = Span(name="test", start=0)
        assert span.is_complete is False

    def test_is_complete_true(self):
        span = Span(name="test", start=0, end=1)
        assert span.is_complete is True

    def default_tags_empty(self):
        span = Span(name="test", start=0)
        assert span.tags == {}

    def default_error_none(self):
        span = Span(name="test", start=0)
        assert span.error is None


class TestTracer:
    """Tracer — trace lifecycle and span management."""

    def test_start_generates_trace_id(self):
        t = Tracer()
        tid = t.start()
        assert len(tid) == 12
        assert tid == t.trace_id

    def test_unique_trace_ids(self):
        ids = {Tracer().start() for _ in range(100)}
        assert len(ids) == 100

    def test_span_records_duration(self):
        t = Tracer()
        t.start()
        with t.span("op1"):
            pass
        s = t.summary()
        assert len(s["spans"]) == 1
        assert s["spans"][0]["name"] == "op1"
        assert s["spans"][0]["duration_ms"] >= 0

    def test_nested_spans(self):
        t = Tracer()
        t.start()
        with t.span("outer"):
            with t.span("inner"):
                pass
        s = t.summary()
        assert len(s["spans"]) == 2
        names = [sp["name"] for sp in s["spans"]]
        assert names == ["outer", "inner"]

    def test_total_ms_summed(self):
        t = Tracer()
        t.start()
        with t.span("a"):
            pass
        with t.span("b"):
            pass
        s = t.summary()
        assert s["total_ms"] >= 0
        assert s["by_name"]["a"]["count"] == 1
        assert s["by_name"]["b"]["count"] == 1

    def test_by_name_aggregates_multi_calls(self):
        t = Tracer()
        t.start()
        for _ in range(3):
            with t.span("ping"):
                pass
        s = t.summary()
        assert s["by_name"]["ping"]["count"] == 3

    def test_start_clears_previous_spans(self):
        t = Tracer()
        t.start()
        with t.span("old_op"):
            pass

        t.start()  # new trace
        s = t.summary()
        assert len(s["spans"]) == 0  # old spans cleared

    def test_span_tags_in_summary(self):
        t = Tracer()
        t.start()
        with t.span("provider", provider="DeepSeek", model="v4"):
            pass
        s = t.summary()
        assert s["spans"][0]["tags"]["provider"] == "DeepSeek"
        assert s["spans"][0]["tags"]["model"] == "v4"

    def test_set_tag_on_current_span(self):
        t = Tracer()
        t.start()
        with t.span("op"):
            t.set_tag("status", "ok")
        s = t.summary()
        assert s["spans"][0]["tags"]["status"] == "ok"

    def test_set_tag_no_active_span_no_error(self):
        t = Tracer()
        t.start()
        t.set_tag("key", "val")  # no active span — should not crash
        # no assertion needed

    def test_failing_span_records_error(self):
        t = Tracer()
        t.start()
        try:
            with t.span("fail"):
                msg = "oops"
                raise ValueError(msg)
        except ValueError:
            pass
        s = t.summary()
        assert s["spans"][0]["error"] is not None
        assert "oops" in s["spans"][0]["error"]
        assert s["by_name"]["fail"]["errors"] == 1

    def test_log_summary_does_not_crash(self, caplog):
        t = Tracer()
        t.start()
        with t.span("op"):
            pass
        caplog.set_level(logging.INFO)
        t.log_summary()
        assert "op" in caplog.text

    def test_multiple_errors_aggregated(self):
        t = Tracer()
        t.start()
        for _ in range(3):
            try:
                with t.span("fragile"):
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
        s = t.summary()
        assert s["by_name"]["fragile"]["errors"] == 3
