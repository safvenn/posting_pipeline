"""
Security headers middleware.

Adds production-grade HTTP security headers to every response.

Headers applied:
  X-Content-Type-Options: nosniff         — prevent MIME-type sniffing
  X-Frame-Options: DENY                   — prevent clickjacking
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Cache-Control: no-store (API responses only)

HSTS is intentionally NOT set here — it must be set at the load balancer
/ CDN level (Render, Cloudflare) for proper preload list submission.

Content-Security-Policy is not set for the API (not serving HTML).
The frontend CSP should be set via meta tags or the CDN/serving layer.

Usage (in main.py):
    from backend.middleware.security import add_security_headers
    add_security_headers(app)
"""
from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all API responses."""

    SECURITY_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "X-XSS-Protection": "0",  # Modern browsers use CSP; legacy value disabled
    }

    # For API endpoints: prevent caching of sensitive data
    API_CACHE_CONTROL = "no-store, no-cache, must-revalidate, private"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Apply base security headers to every response
        for header, value in self.SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)

        # For API routes: force no-cache (prevents auth token caching by proxies)
        path = request.url.path
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", self.API_CACHE_CONTROL)

        # For video/media streaming responses: allow caching but restrict
        if path.startswith("/media/") or path.startswith("/api/posts/") and "video" in path:
            # Allow CDN/browser caching for media but restrict cross-origin embedding
            response.headers.setdefault("Cache-Control", "private, max-age=3600")
            response.headers.setdefault("X-Content-Type-Options", "nosniff")

        return response


def add_security_headers(app: FastAPI) -> None:
    """Register security headers middleware on the FastAPI app."""
    app.add_middleware(SecurityHeadersMiddleware)
