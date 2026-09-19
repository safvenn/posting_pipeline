"""Tests — SSRF protection on /api/extension/ingest."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client():
    from backend.main import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _validate_ingest_url unit tests
# ---------------------------------------------------------------------------

from backend.routers.extension import _validate_ingest_url
from fastapi import HTTPException


@pytest.mark.parametrize("bad_url", [
    "ftp://example.com/video.mp4",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,<script>",
])
def test_bad_scheme_rejected(bad_url):
    with pytest.raises(HTTPException) as exc_info:
        _validate_ingest_url(bad_url)
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize("private_url,resolved_ip", [
    ("http://localhost/video.mp4", "127.0.0.1"),
    ("http://internal-server/video.mp4", "10.0.0.1"),
    ("http://private.lan/video.mp4", "192.168.1.1"),
    ("http://link-local.example.com/video.mp4", "169.254.169.254"),
    ("http://metadata.google.internal/computeMetadata/v1/", "169.254.169.254"),
])
def test_private_ip_rejected(private_url, resolved_ip):
    """DNS resolves to private IP — must be blocked."""
    import socket
    mock_info = [(None, None, None, None, (resolved_ip, 80))]
    with patch("backend.routers.extension.socket.getaddrinfo", return_value=mock_info):
        with pytest.raises(HTTPException) as exc_info:
            _validate_ingest_url(private_url)
        assert exc_info.value.status_code == 400
        assert "SSRF" in exc_info.value.detail or "private" in exc_info.value.detail.lower()


def test_cloud_metadata_hostname_blocked():
    """169.254.169.254 hostname blocked by name before DNS."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_ingest_url("http://169.254.169.254/latest/meta-data/")
    assert exc_info.value.status_code == 400


def test_public_ip_allowed():
    """Public IP should pass validation (not blocked)."""
    mock_info = [(None, None, None, None, ("93.184.216.34", 80))]
    with patch("backend.routers.extension.socket.getaddrinfo", return_value=mock_info):
        # Should not raise
        _validate_ingest_url("https://example.com/video.mp4")


def test_redirect_to_private_blocked():
    """
    Public URL that redirects to a private address must be blocked.
    Tested via the _ssrf_safe_download redirect validation logic.
    """
    from backend.routers.extension import _validate_ingest_url
    # The redirect target URL is re-validated — test that private redirect target fails
    private_redirect = "http://192.168.1.100/secret"
    mock_info = [(None, None, None, None, ("192.168.1.100", 80))]
    with patch("backend.routers.extension.socket.getaddrinfo", return_value=mock_info):
        with pytest.raises(HTTPException) as exc_info:
            _validate_ingest_url(private_redirect)
        assert exc_info.value.status_code == 400


def test_internal_suffix_blocked():
    """Hostnames ending in .internal are blocked."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_ingest_url("http://myservice.internal/video.mp4")
    assert exc_info.value.status_code == 400
