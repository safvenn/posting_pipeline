"""
Tests for stateful auth — refresh token lifecycle, rotation, revocation.

These test the critical security properties:
  1. Tokens are hashed — raw token never stored
  2. Logout revokes token server-side
  3. Rotation invalidates the old token immediately
  4. Expired tokens are rejected
  5. Revoked tokens are rejected
  6. logout-all revokes all sessions
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.routers.auth import (
    _hash_token,
    _create_access_token,
    _validate_refresh_token,
    _revoke_refresh_token,
    _revoke_all_for_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_token() -> str:
    return secrets.token_urlsafe(48)


def _make_refresh_record(
    username="admin",
    is_revoked=False,
    expired=False,
    use_count=0,
):
    record = MagicMock()
    record.username = username
    record.is_revoked = is_revoked
    record.is_expired = expired
    record.is_valid = not is_revoked and not expired
    record.use_count = use_count
    record.expires_at = (
        datetime.now(timezone.utc) - timedelta(hours=1)
        if expired
        else datetime.now(timezone.utc) + timedelta(days=7)
    )
    return record


# ---------------------------------------------------------------------------
# Token hashing
# ---------------------------------------------------------------------------

class TestTokenHashing:
    def test_hash_is_sha256(self):
        raw = "test-token-abc"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert _hash_token(raw) == expected

    def test_hash_is_64_chars(self):
        raw = _raw_token()
        assert len(_hash_token(raw)) == 64

    def test_hash_is_deterministic(self):
        raw = _raw_token()
        assert _hash_token(raw) == _hash_token(raw)

    def test_different_tokens_have_different_hashes(self):
        t1 = _raw_token()
        t2 = _raw_token()
        assert _hash_token(t1) != _hash_token(t2)

    def test_raw_token_not_in_hash(self):
        raw = "super-secret-token"
        h = _hash_token(raw)
        assert "super-secret-token" not in h
        assert raw not in h


# ---------------------------------------------------------------------------
# Access token creation
# ---------------------------------------------------------------------------

class TestAccessTokenCreation:
    def test_creates_valid_jwt(self):
        from unittest.mock import patch
        with patch("backend.routers.auth.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret-12345678"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.access_token_expire_minutes = 30
            token = _create_access_token("admin")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_correct_subject(self):
        from jose import jwt as jose_jwt
        from unittest.mock import patch
        secret = "test-secret-12345678"
        with patch("backend.routers.auth.settings") as mock_settings:
            mock_settings.jwt_secret = secret
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.access_token_expire_minutes = 30
            token = _create_access_token("admin")
        payload = jose_jwt.decode(token, secret, algorithms=["HS256"])
        assert payload["sub"] == "admin"
        assert payload["type"] == "access"

    def test_token_has_jti(self):
        """Each token must have a unique JWT ID for future revocation."""
        from jose import jwt as jose_jwt
        from unittest.mock import patch
        secret = "test-secret-12345678"
        with patch("backend.routers.auth.settings") as mock_settings:
            mock_settings.jwt_secret = secret
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.access_token_expire_minutes = 30
            t1 = _create_access_token("admin")
            t2 = _create_access_token("admin")
        p1 = jose_jwt.decode(t1, secret, algorithms=["HS256"])
        p2 = jose_jwt.decode(t2, secret, algorithms=["HS256"])
        assert p1["jti"] != p2["jti"], "Each token must have a unique jti"


# ---------------------------------------------------------------------------
# Refresh token validation
# ---------------------------------------------------------------------------

class TestRefreshTokenValidation:
    def test_valid_token_is_accepted(self):
        raw = _raw_token()
        token_hash = _hash_token(raw)
        record = _make_refresh_record()

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = record

        result = _validate_refresh_token(db, raw)
        assert result == record

    def test_unknown_token_raises_401(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _validate_refresh_token(db, _raw_token())
        assert exc_info.value.status_code == 401

    def test_revoked_token_raises_401(self):
        raw = _raw_token()
        record = _make_refresh_record(is_revoked=True)

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = record

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _validate_refresh_token(db, raw)
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail.lower()

    def test_expired_token_raises_401(self):
        raw = _raw_token()
        record = _make_refresh_record(expired=True)

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = record

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _validate_refresh_token(db, raw)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Token revocation
# ---------------------------------------------------------------------------

class TestTokenRevocation:
    def test_revoke_sets_revoked_flag(self):
        db = MagicMock()
        record = _make_refresh_record()

        _revoke_refresh_token(db, record, reason="logout")

        assert record.is_revoked is True
        assert record.revoked_at is not None
        assert record.revoke_reason == "logout"
        db.commit.assert_called_once()

    def test_revoke_reason_is_stored(self):
        db = MagicMock()
        record = _make_refresh_record()

        _revoke_refresh_token(db, record, reason="rotation")
        assert record.revoke_reason == "rotation"

    def test_revoke_all_revokes_active_records(self):
        db = MagicMock()
        records = [_make_refresh_record() for _ in range(3)]
        # _revoke_all_for_user uses a single .filter(...).all() call
        db.query.return_value.filter.return_value.all.return_value = records

        count = _revoke_all_for_user(db, "admin", reason="logout-all")

        assert count == 3
        for r in records:
            assert r.is_revoked is True
            assert r.revoke_reason == "logout-all"
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Token rotation security property
# ---------------------------------------------------------------------------

class TestTokenRotationSecurity:
    """
    Critical: After token rotation, the old token MUST be revoked.
    This prevents token theft replay attacks.
    """

    def test_rotation_revokes_old_token(self):
        """
        Simulate rotation: after /api/auth/refresh is called,
        the old refresh token must be revoked.
        """
        old_record = _make_refresh_record(use_count=0)
        old_record.username = "admin"
        old_record.is_revoked = False

        db = MagicMock()
        # Simulate: old token found and valid
        db.query.return_value.filter.return_value.first.return_value = old_record

        # Call revoke as the refresh endpoint does
        _revoke_refresh_token(db, old_record, reason="rotation")

        # Old token must now be revoked
        assert old_record.is_revoked is True
        assert old_record.revoke_reason == "rotation"

    def test_replay_of_old_token_is_rejected(self):
        """After rotation, the old token hash must be rejected on next use."""
        old_record = _make_refresh_record(is_revoked=True)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = old_record

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _validate_refresh_token(db, _raw_token())
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

class TestAuditEvents:
    """Verify audit events are fired on login/logout."""

    def test_login_failure_logs_audit_event(self):
        from backend.services.audit import AuditService, AuthEvent, Outcome
        db = MagicMock()
        audit = AuditService(db, actor="attacker", actor_ip="1.2.3.4")

        # Should not raise
        with patch.object(audit, "log") as mock_log:
            audit.login_failure("admin", reason="wrong password")
            mock_log.assert_called_once_with(
                AuthEvent.LOGIN_FAILURE,
                outcome=Outcome.FAILURE,
                description="Failed login for 'admin': wrong password",
            )

    def test_logout_logs_audit_event(self):
        from backend.services.audit import AuditService, AuthEvent
        db = MagicMock()
        audit = AuditService(db, actor="admin")

        with patch.object(audit, "log") as mock_log:
            audit.logout("admin")
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[0] == AuthEvent.LOGOUT

    def test_token_rotated_logs_audit_event(self):
        from backend.services.audit import AuditService, AuthEvent
        db = MagicMock()
        audit = AuditService(db, actor="admin")

        with patch.object(audit, "log") as mock_log:
            audit.token_rotated("admin")
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            assert args[0] == AuthEvent.TOKEN_ROTATED
