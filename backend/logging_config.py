"""
Structured JSON logging for the posting pipeline.

Design goals:
  1. Every log line is valid JSON — parseable by Render log drain, Datadog, etc.
  2. Every log line carries a request_id (correlation ID) when inside a request context
  3. Standard fields on every line: timestamp, level, logger, message, request_id
  4. Extra structured fields passed as kwargs are serialized into the JSON object
  5. No external dependencies at startup — falls back to stdlib if python-json-logger
     is not installed (produces a readable but non-JSON format for local dev)

Usage:
    from backend.logging_config import configure_logging, get_logger

    # Called once at application startup:
    configure_logging(json_output=True, level="INFO")

    # In any module:
    logger = get_logger(__name__)
    logger.info("Post uploaded", extra={"post_id": 182, "video_id": "abc"})

    # With request context (set by RequestIDMiddleware):
    # Request-scoped logs automatically carry request_id field.

Output format (JSON mode):
    {
      "timestamp": "2026-09-24T10:00:00.123Z",
      "level": "INFO",
      "logger": "backend.jobs.upload_job",
      "message": "Post uploaded",
      "request_id": "req-8f3a2b1c",
      "post_id": 182,
      "video_id": "abc"
    }
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Context var for correlation ID (set by RequestIDMiddleware)
# ---------------------------------------------------------------------------
from contextvars import ContextVar

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return _request_id_var.get()


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id)


# ---------------------------------------------------------------------------
# JSON Formatter (stdlib-only, no external deps)
# ---------------------------------------------------------------------------

class _JSONFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.

    Included fields:
      timestamp   ISO-8601 UTC
      level       INFO / WARNING / ERROR / etc.
      logger      logger name (e.g. backend.jobs.upload_job)
      message     formatted log message
      request_id  correlation ID from ContextVar (set by middleware)
      exc_info    exception traceback as string (only on exceptions)

    Any extra fields set on the log record (e.g. via extra={...}) are
    included as top-level fields if they don't clash with standard fields.
    """

    _RESERVED = frozenset({
        "args", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message",
        "module", "msecs", "msg", "name", "pathname", "process",
        "processName", "relativeCreated", "stack_info", "taskName",
        "thread", "threadName",
    })

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        # Base fields
        obj: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }

        # Include extra fields (anything not in the reserved set)
        for key, val in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                try:
                    json.dumps(val)  # ensure serialisable
                    obj[key] = val
                except (TypeError, ValueError):
                    obj[key] = str(val)

        # Exception info
        if record.exc_info:
            obj["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            obj["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(obj, ensure_ascii=False, default=str)


class _ReadableFormatter(logging.Formatter):
    """
    Human-readable formatter for local development.
    Includes request_id but does NOT output JSON.
    """
    def format(self, record: logging.LogRecord) -> str:
        rid = get_request_id()
        rid_part = f" [{rid}]" if rid and rid != "-" else ""
        base = super().format(record)
        return f"{base}{rid_part}"


# ---------------------------------------------------------------------------
# Try to use python-json-logger if available, otherwise use our own
# ---------------------------------------------------------------------------

def _make_json_formatter() -> logging.Formatter:
    try:
        from pythonjsonlogger import jsonlogger  # type: ignore

        class _EnhancedJsonFormatter(jsonlogger.JsonFormatter):
            def add_fields(self, log_record, record, message_dict):
                super().add_fields(log_record, record, message_dict)
                log_record["timestamp"] = datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                log_record["level"] = record.levelname
                log_record["logger"] = record.name
                log_record["request_id"] = get_request_id()

        return _EnhancedJsonFormatter(
            "%(timestamp)s %(level)s %(logger)s %(message)s %(request_id)s"
        )
    except ImportError:
        # Fall back to our pure-stdlib JSON formatter
        return _JSONFormatter()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def configure_logging(
    json_output: bool = True,
    level: str = "INFO",
    suppress_noisy_loggers: bool = True,
) -> None:
    """
    Configure the root logger for the application.

    Call once at application startup (in main.py lifespan or module top-level).

    Args:
        json_output:             If True, emit structured JSON. If False, emit
                                 human-readable format (good for local dev).
        level:                   Root log level. Defaults to "INFO".
        suppress_noisy_loggers:  Silence known verbose third-party loggers.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers (avoids duplicate lines when called multiple times)
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    if json_output:
        handler.setFormatter(_make_json_formatter())
    else:
        handler.setFormatter(
            _ReadableFormatter(
                fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )

    root.addHandler(handler)

    if suppress_noisy_loggers:
        _suppress = [
            "apscheduler",
            "apscheduler.executors.default",
            "apscheduler.scheduler",
            "googleapiclient.discovery_cache",
            "googleapiclient.discovery",
            "urllib3",
            "httpx",
            "httpcore",
            "paramiko",
            "uvicorn.access",        # replaced by RequestTimingMiddleware
        ]
        for name in _suppress:
            logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging configured",
        extra={"json_output": json_output, "level": level},
    )


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger. Prefer this over logging.getLogger() for
    consistency — allows future centralized logger configuration.
    """
    return logging.getLogger(name)
