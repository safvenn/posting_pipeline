"""
Unit tests for autonomous Google Flow authentication, pure-Python TOTP generation,
and session validation.
"""
from unittest.mock import patch
import os
import pytest

from backend.services.flow_playwright import (
    generate_totp_code,
    _get_google_credentials,
    check_session_exists,
)


class TestAutonomousFlowAuth:
    def test_rfc6238_totp_test_vectors(self):
        """Verify generate_totp_code matches standard RFC 6238 test vectors."""
        # Secret: "12345678901234567890" in Base32:
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

        # Test vector 1: T=59 (time.time() = 59) -> 287082
        with patch("time.time", return_value=59):
            assert generate_totp_code(secret) == "287082"

        # Test vector 2: T=1111111109 -> 081804
        with patch("time.time", return_value=1111111109):
            assert generate_totp_code(secret) == "081804"

        # Test vector 3: T=1111111111 -> 050471
        with patch("time.time", return_value=1111111111):
            assert generate_totp_code(secret) == "050471"

        # Test vector 4: T=1234567890 -> 005924
        with patch("time.time", return_value=1234567890):
            assert generate_totp_code(secret) == "005924"

        # Test vector 5: T=2000000000 -> 279037
        with patch("time.time", return_value=2000000000):
            assert generate_totp_code(secret) == "279037"

    def test_totp_handles_spaces_and_hyphens(self):
        """TOTP generator should tolerate spaces and hyphens commonly found in Google Authenticator keys."""
        secret_raw = "GEZD GNBV-GY3T QOJQ GEZD-GNBV GY3T QOJQ"
        with patch("time.time", return_value=59):
            assert generate_totp_code(secret_raw) == "287082"

    def test_get_google_credentials(self):
        """_get_google_credentials reads FEMAIL, FPASS, and FTOTP_SECRET from env."""
        with patch.dict(os.environ, {
            "FEMAIL": "test@example.com",
            "FPASS": "secretpass123",
            "FTOTP_SECRET": "JBSWY3DPEHPK3PXP",
        }):
            email, password, totp = _get_google_credentials()
            assert email == "test@example.com"
            assert password == "secretpass123"
            assert totp == "JBSWY3DPEHPK3PXP"

    def test_check_session_exists_with_credentials(self, tmp_path):
        """check_session_exists returns True when credentials are present even if files don't exist."""
        with patch("backend.services.flow_playwright.AUTH_FILE", tmp_path / "nonexistent.json"), \
             patch("backend.services.flow_playwright.PROFILE_DIR", tmp_path / "nonexistent_dir"), \
             patch.dict(os.environ, {
                 "FEMAIL": "test@example.com",
                 "FPASS": "secretpass123",
             }):
            assert check_session_exists() is True
