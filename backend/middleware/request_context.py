"""
Request ID + Timing middleware.

RequestIDMiddleware
  - Reads X-Request-ID from incoming request (if provided by upstream proxy/CDN)
  - Falls back to generating a new uuid4 short-form ID
  - Stores it in the ContextVar (so all log lines within the request carry it)
  - Echoes it back in X-Request-ID response header

RequestTimingMiddleware
  - Records wall-clock time for each request
  - Emits a structured log line at the end:
      {"method": "POST", "path": "/api/posts", "status": 200, "duration_ms": 142, ...}
  - Adds X-Response-Time response header (milliseconds)

Both middleware are stacked in main.py BEFORE any route handlers.
Order: RequestIDMiddleware → RequestTimingMiddleware → route handler

Usage (in main.py create_app):
    from backend.middleware.request_context import RequestIDMiddleware, RequestTimingMiddleware
    app.add_middleware(RequestTimingMiddleware)
    app.add_middleware(RequestIDMiddleware)
"""
from __future__ import annotations

import logging
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.logging_config import set_request_id, get_request_id

logger = logging.getLogger(__name__)


def _short_id() -> str:
    """Return a compact 12-char hex correlation ID."""
    return uuid.uuid4().hex[:12]


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assigns a unique X-Request-ID to every incoming request.

    If the upstream (Render load balancer, CDN, or test client) sends an
    X-Request-ID header, that value is trusted and propagated. Otherwise
    a fresh ID is generated.

    The ID is stored in a ContextVar so it appears in every log line
    emitted during that request's handler execution — across threads that
    access the same ContextVar.
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(self.header_name) or _short_id()
        set_request_id(request_id)

        response = await call_next(request)
        response.headers[self.header_name] = request_id
        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """
    Structured access logging with request timing.

    Replaces uvicorn.access logger (which is suppressed in logging_config.py)
    with a clean structured log line per request containing:
      method, path, status_code, duration_ms, request_id, client_host

    Also adds X-Response-Time header for frontend / monitoring use.

    Excludes:
      - /api/health/* endpoints (very chatty, log at DEBUG not INFO)
      - Static files (not served by this app, but guard anyway)
    """

    _HEALTH_PATHS = frozenset({"/api/health/live", "/api/health/ready"})

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        path = request.url.path
        method = request.method

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000)
            logger.error(
                "Unhandled request exception",
                extra={
                    "method": method,
                    "path": path,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                    "request_id": get_request_id(),
                },
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000)
        response.headers["X-Response-Time"] = f"{duration_ms}ms"

        log_level = logging.DEBUG if path in self._HEALTH_PATHS else logging.INFO

        logger.log(
            log_level,
            "%s %s %s",
            method,
            path,
            response.status_code,
            extra={
                "method": method,
                "path": path,
                "query": str(request.url.query) or None,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client": request.client.host if request.client else None,
                "request_id": get_request_id(),
            },
        )

        return response
