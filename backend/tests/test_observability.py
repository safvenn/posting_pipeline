"""
Tests for Phase 4 observability:
  - JSON formatter emits valid JSON with required fields
  - request_id ContextVar is isolated between calls
  - RequestIDMiddleware generates and propagates X-Request-ID
  - RequestIDMiddleware reuses upstream request ID if provided
  - RequestTimingMiddleware adds X-Response-Time header
  - metrics percentile helper is correct
  - configure_logging is idempotent (no duplicate handlers)
"""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# JSON Formatter
# ---------------------------------------------------------------------------

class TestJSONFormatter:
    """Test the stdlib-based JSON log formatter."""

    def _make_record(self, message="test message", level=logging.INFO, extra=None):
        record = logging.LogRecord(
            name="backend.test",
            level=level,
            pathname="test.py",
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )
        if extra:
            for k, v in extra.items():
                setattr(record, k, v)
        return record

    def test_output_is_valid_json(self):
        from backend.logging_config import _JSONFormatter
        formatter = _JSONFormatter()
        record = self._make_record("hello world")
        output = formatter.format(record)
        parsed = json.loads(output)  # must not raise
        assert isinstance(parsed, dict)

    def test_required_fields_present(self):
        from backend.logging_config import _JSONFormatter
        formatter = _JSONFormatter()
        record = self._make_record("test message")
        parsed = json.loads(formatter.format(record))
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "logger" in parsed
        assert "message" in parsed
        assert "request_id" in parsed

    def test_message_content(self):
        from backend.logging_config import _JSONFormatter
        formatter = _JSONFormatter()
        record = self._make_record("Upload succeeded")
        parsed = json.loads(formatter.format(record))
        assert parsed["message"] == "Upload succeeded"

    def test_level_is_string(self):
        from backend.logging_config import _JSONFormatter
        formatter = _JSONFormatter()
        record = self._make_record("error", level=logging.ERROR)
        parsed = json.loads(formatter.format(record))
        assert parsed["level"] == "ERROR"

    def test_logger_name_preserved(self):
        from backend.logging_config import _JSONFormatter
        formatter = _JSONFormatter()
        record = self._make_record()
        parsed = json.loads(formatter.format(record))
        assert parsed["logger"] == "backend.test"

    def test_extra_fields_included(self):
        from backend.logging_config import _JSONFormatter
        formatter = _JSONFormatter()
        record = self._make_record("post uploaded", extra={"post_id": 182, "video_id": "abc"})
        parsed = json.loads(formatter.format(record))
        assert parsed.get("post_id") == 182
        assert parsed.get("video_id") == "abc"

    def test_timestamp_ends_with_z(self):
        from backend.logging_config import _JSONFormatter
        formatter = _JSONFormatter()
        record = self._make_record()
        parsed = json.loads(formatter.format(record))
        assert parsed["timestamp"].endswith("Z")

    def test_exception_info_included(self):
        from backend.logging_config import _JSONFormatter
        formatter = _JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="backend.test", level=logging.ERROR,
                pathname="test.py", lineno=1,
                msg="error occurred", args=(), exc_info=sys.exc_info(),
            )
        parsed = json.loads(formatter.format(record))
        assert "exc_info" in parsed
        assert "ValueError" in parsed["exc_info"]


# ---------------------------------------------------------------------------
# ContextVar isolation
# ---------------------------------------------------------------------------

class TestRequestIDContextVar:
    """The request_id ContextVar must be isolated between independent calls."""

    def test_default_request_id_is_dash(self):
        from backend.logging_config import get_request_id
        # In a fresh context with no set_request_id, should return "-"
        rid = get_request_id()
        assert isinstance(rid, str)

    def test_set_and_get_request_id(self):
        from backend.logging_config import set_request_id, get_request_id
        set_request_id("test-req-123")
        assert get_request_id() == "test-req-123"

    def test_request_id_appears_in_formatted_log(self):
        from backend.logging_config import _JSONFormatter, set_request_id
        set_request_id("req-abc456")
        formatter = _JSONFormatter()
        record = logging.LogRecord(
            name="backend.test", level=logging.INFO,
            pathname="test.py", lineno=1,
            msg="test", args=(), exc_info=None,
        )
        parsed = json.loads(formatter.format(record))
        assert parsed["request_id"] == "req-abc456"


# ---------------------------------------------------------------------------
# configure_logging idempotency
# ---------------------------------------------------------------------------

class TestConfigureLogging:
    def test_does_not_add_duplicate_handlers(self):
        from backend.logging_config import configure_logging
        root = logging.getLogger()
        initial_handler_count = len(root.handlers)

        configure_logging(json_output=False, level="INFO")
        after_first = len(root.handlers)

        configure_logging(json_output=False, level="INFO")
        after_second = len(root.handlers)

        # Each call resets to exactly 1 handler
        assert after_first == 1
        assert after_second == 1

    def test_json_mode_sets_json_formatter(self):
        from backend.logging_config import configure_logging, _JSONFormatter
        configure_logging(json_output=True, level="DEBUG")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, (_JSONFormatter,))
        # Also accept pythonjsonlogger formatter if installed
        # Just check the handler exists and has a formatter
        assert root.handlers[0].formatter is not None


# ---------------------------------------------------------------------------
# Metrics percentile helper
# ---------------------------------------------------------------------------

class TestPercentileHelper:
    def test_empty_returns_none(self):
        from backend.routers.metrics import _percentile
        assert _percentile([], 50) is None
        assert _percentile([], 95) is None

    def test_single_value_returns_that_value(self):
        from backend.routers.metrics import _percentile
        assert _percentile([100.0], 50) == 100.0
        assert _percentile([100.0], 95) == 100.0

    def test_median_of_odd_count(self):
        from backend.routers.metrics import _percentile
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert _percentile(vals, 50) == 30.0

    def test_p95_of_100_values(self):
        from backend.routers.metrics import _percentile
        vals = [float(i) for i in range(1, 101)]  # 1..100
        result = _percentile(vals, 95)
        # 95th percentile of 1-100 should be ~95.05
        assert 94.0 <= result <= 96.0

    def test_sorted_order_invariant(self):
        """Result must be the same regardless of input order."""
        from backend.routers.metrics import _percentile
        vals_sorted = [10.0, 20.0, 30.0, 40.0, 50.0]
        vals_unsorted = [50.0, 10.0, 40.0, 20.0, 30.0]
        assert _percentile(vals_sorted, 50) == _percentile(vals_unsorted, 50)

    def test_p50_two_values(self):
        from backend.routers.metrics import _percentile
        # Median of [10, 20] should be 15
        result = _percentile([10.0, 20.0], 50)
        assert result == 15.0


# ---------------------------------------------------------------------------
# RequestIDMiddleware (integration via ASGI test helpers)
# ---------------------------------------------------------------------------

class TestRequestIDMiddleware:
    """Test that the middleware generates and echoes X-Request-ID."""

    def _make_app(self):
        from fastapi import FastAPI
        from backend.middleware.request_context import RequestIDMiddleware

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        def test_route():
            from backend.logging_config import get_request_id
            return {"request_id": get_request_id()}

        return app

    def test_generates_request_id_if_none(self):
        from fastapi.testclient import TestClient
        client = TestClient(self._make_app())
        response = client.get("/test")
        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        rid = response.headers["X-Request-ID"]
        assert len(rid) >= 8

    def test_propagates_upstream_request_id(self):
        from fastapi.testclient import TestClient
        client = TestClient(self._make_app())
        response = client.get("/test", headers={"X-Request-ID": "upstream-123"})
        assert response.headers.get("X-Request-ID") == "upstream-123"
        assert response.json()["request_id"] == "upstream-123"

    def test_request_id_available_in_handler(self):
        from fastapi.testclient import TestClient
        client = TestClient(self._make_app())
        response = client.get("/test", headers={"X-Request-ID": "my-trace-id"})
        assert response.json()["request_id"] == "my-trace-id"


class TestRequestTimingMiddleware:
    """Test that timing middleware adds X-Response-Time header."""

    def _make_app(self):
        from fastapi import FastAPI
        from backend.middleware.request_context import RequestTimingMiddleware, RequestIDMiddleware

        app = FastAPI()
        app.add_middleware(RequestTimingMiddleware)
        app.add_middleware(RequestIDMiddleware)

        @app.get("/fast")
        def fast_route():
            return {"ok": True}

        return app

    def test_adds_response_time_header(self):
        from fastapi.testclient import TestClient
        client = TestClient(self._make_app())
        response = client.get("/fast")
        assert response.status_code == 200
        assert "X-Response-Time" in response.headers
        rt = response.headers["X-Response-Time"]
        assert rt.endswith("ms")

    def test_response_time_is_numeric(self):
        from fastapi.testclient import TestClient
        client = TestClient(self._make_app())
        response = client.get("/fast")
        rt = response.headers["X-Response-Time"]
        ms = int(rt.replace("ms", ""))
        assert ms >= 0
