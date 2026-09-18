"""Tests for CORS origin allowlist, preflight requests, and video upload endpoints."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from starlette.testclient import TestClient
from backend.main import create_app

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def test_cors_preflight_flow_google(client):
    """CORS preflight for https://flow.google.com must return 200 with Access-Control-Allow-Origin."""
    resp = client.options(
        "/api/extension/upload",
        headers={
            "Origin": "https://flow.google.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,x-api-key,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://flow.google.com"
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_labs_google(client):
    """CORS preflight for https://labs.google must return 200 with Access-Control-Allow-Origin."""
    resp = client.options(
        "/api/extension/upload",
        headers={
            "Origin": "https://labs.google",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,x-api-key,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://labs.google"


def test_cors_preflight_chrome_extension(client):
    """CORS preflight for chrome-extension origin must return 200."""
    resp = client.options(
        "/api/extension/upload",
        headers={
            "Origin": "chrome-extension://abcdefghijklmnop",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,x-api-key",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "chrome-extension://abcdefghijklmnop"


def test_cors_preflight_posts_endpoint(client):
    """CORS preflight for /api/posts from Vercel must return 200."""
    resp = client.options(
        "/api/posts",
        headers={
            "Origin": "https://posting-pipeline-teal.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://posting-pipeline-teal.vercel.app"


def test_extension_ingest_rejects_blob_url(client):
    """Ingest endpoint must reject blob: URLs with HTTP 400."""
    from backend.config import settings
    headers = {"Origin": "https://flow.google.com"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"

    resp = client.post(
        "/api/extension/ingest",
        json={
            "video_url": "blob:https://flow.google.com/1234-5678",
            "title": "Blob Test",
            "channel": "the_indian_kitchen",
        },
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Blob URLs cannot be downloaded directly" in resp.text
    assert resp.headers.get("access-control-allow-origin") == "https://flow.google.com"


def test_global_exception_handler_returns_cors(client):
    """Unhandled server errors must return CORS headers so browser never masks them as Failed to fetch."""
    # Requesting an invalid endpoint or causing internal exception
    resp = client.get(
        "/api/posts/not-an-int",
        headers={"Origin": "https://flow.google.com"},
    )
    # Even on error (422/404/500), CORS headers must be present
    assert resp.headers.get("access-control-allow-origin") == "https://flow.google.com"
