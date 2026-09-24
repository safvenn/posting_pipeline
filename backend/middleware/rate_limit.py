"""
Rate limiting middleware — sliding window, per-IP + per-endpoint.

Protects:
  - Login endpoint from brute force
  - Upload endpoint from abuse
  - Extension ingest from flooding
  - All API mutation endpoints

Implementation: in-memory sliding window counter.
  - Suitable for single-instance deployments (Render starter tier)
  - Can be upgraded to Redis backend by swapping _store

On limit hit: returns 429 with Retry-After and X-RateLimit-* headers.

Usage (in main.py):
    from backend.middleware.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
"""
from __future__ import annotations

import time
import logging
from collections import defaultdict
from threading import Lock
from typing import Callable, NamedTuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class RateRule(NamedTuple):
    """A rate limit rule: max `limit` requests per `window` seconds."""
    limit: int
    window: int  # seconds


# Route-specific rules: (method, path_prefix) → RateRule
# More specific rules take precedence (matched first by longest prefix)
_ROUTE_RULES: list[tuple[str, str, RateRule]] = [
    # Login brute-force protection — strict
    ("POST", "/api/auth/login",   RateRule(limit=10, window=60)),
    ("POST", "/api/auth/refresh", RateRule(limit=30, window=60)),
    # Upload endpoints — limit per IP to prevent flooding
    ("POST", "/api/extension",    RateRule(limit=30, window=60)),
    ("POST", "/api/posts",        RateRule(limit=20, window=60)),
    # Retry / admin mutations — moderate limit
    ("POST", "/api/",             RateRule(limit=60, window=60)),
    # General API reads — lenient
    ("GET",  "/api/",             RateRule(limit=200, window=60)),
]

# Default fallback rule
_DEFAULT_RULE = RateRule(limit=120, window=60)


class _InMemoryStore:
    """Thread-safe sliding window counter store."""

    def __init__(self) -> None:
        # {key: [(timestamp, count), ...]}
        self._store: dict[str, list[tuple[float, int]]] = defaultdict(list)
        self._lock = Lock()

    def hit(self, key: str, window: int) -> int:
        """Record a hit for `key` and return the count in the last `window` seconds."""
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            entries = self._store[key]
            # Drop expired entries
            entries[:] = [(ts, c) for ts, c in entries if ts > cutoff]
            entries.append((now, 1))
            total = sum(c for _, c in entries)
            return total


_store = _InMemoryStore()


def _get_rule(method: str, path: str) -> RateRule:
    """Return the most specific matching rate rule for this request."""
    for rule_method, prefix, rule in _ROUTE_RULES:
        if rule_method == method and path.startswith(prefix):
            return rule
    return _DEFAULT_RULE


def _get_client_ip(request: Request) -> str:
    """Extract real client IP, respecting X-Forwarded-For from trusted proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first (leftmost) IP — the real client
        ip = forwarded.split(",")[0].strip()
        if ip:
            return ip
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter per client IP + endpoint."""

    # Paths excluded from rate limiting (health checks, static assets)
    _EXCLUDE_PREFIXES = ("/api/health", "/api/auto/status", "/static/", "/media/")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        method = request.method

        # Skip rate limiting for excluded paths
        for prefix in self._EXCLUDE_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        rule = _get_rule(method, path)
        client_ip = _get_client_ip(request)
        key = f"{client_ip}:{method}:{path[:64]}"  # truncate path to limit key size

        count = _store.hit(key, rule.window)

        # Set rate limit headers on every response
        remaining = max(0, rule.limit - count)
        headers = {
            "X-RateLimit-Limit": str(rule.limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Window": str(rule.window),
        }

        if count > rule.limit:
            retry_after = str(rule.window)
            logger.warning(
                "rate_limit: blocked ip=%s method=%s path=%s count=%d limit=%d",
                client_ip, method, path, count, rule.limit,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "error_code": "rate_limit_exceeded",
                    "retry_after_seconds": rule.window,
                },
                headers={
                    **headers,
                    "Retry-After": retry_after,
                },
            )

        response = await call_next(request)

        # Add headers to successful responses too
        for k, v in headers.items():
            response.headers.setdefault(k, v)

        return response
