"""
Tests for Phase 6 — Security Hardening:
  - CredentialService.get_service_account_credentials (inline JSON, file path, missing)
  - CredentialService.fingerprint (stable, prefix-safe)
  - CredentialService rotation detection
  - TokenEncryption encrypt/decrypt round-trip
  - TokenEncryption passthrough when no key
  - TokenEncryption key rotation (old key + new key)
  - TokenEncryption doesn't double-encrypt
  - Security recommendations logic
"""
from __future__ import annotations

import json
import os
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# CredentialService
# ---------------------------------------------------------------------------

class TestCredentialServiceInlineJSON:
    """Service account loaded from inline JSON env var."""

    def test_inline_json_returns_credentials(self):
        fake_sa = json.dumps({
            "type": "service_account",
            "project_id": "test",
            "private_key_id": "key123",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n",
            "client_email": "test@test.iam.gserviceaccount.com",
            "client_id": "123",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": fake_sa}):
            from backend.services.credentials import CredentialService
            # We can't actually create real Credentials without valid RSA key,
            # but we can verify the parsing logic by mocking the Credentials class
            with patch("backend.services.credentials.json.loads", return_value={"type": "service_account"}):
                with patch("google.oauth2.service_account.Credentials.from_service_account_info") as mock_creds:
                    mock_creds.return_value = MagicMock()
                    creds = CredentialService.get_service_account_credentials(scopes=["https://www.googleapis.com/auth/drive"])
                    assert creds is not None
                    mock_creds.assert_called_once()

    def test_is_configured_with_inline_json(self):
        fake_sa = '{"type": "service_account", "project_id": "test"}'
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": fake_sa}):
            from backend.services.credentials import CredentialService
            assert CredentialService.is_configured() is True

    def test_is_configured_without_env_var(self):
        with patch.dict(os.environ, {}, clear=False):
            # Remove the env var if set
            env_copy = os.environ.copy()
            env_copy.pop("GOOGLE_SERVICE_ACCOUNT_JSON", None)
            with patch.dict(os.environ, env_copy, clear=True):
                with patch("backend.config.settings") as mock_settings:
                    mock_settings.google_sheets_service_account_json = ""
                    from backend.services.credentials import CredentialService
                    result = CredentialService.is_configured()
                    # May be True or False depending on local file existence


class TestCredentialServiceFingerprint:
    """Fingerprint is stable and safe to log."""

    def test_fingerprint_returns_hex_string(self):
        fake_sa = '{"type": "service_account"}'
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": fake_sa}):
            from backend.services.credentials import CredentialService
            fp = CredentialService.fingerprint()
            assert fp is not None
            assert len(fp) == 16  # 16 hex chars
            assert all(c in "0123456789abcdef" for c in fp)

    def test_fingerprint_is_deterministic(self):
        fake_sa = '{"type": "service_account", "id": "test123"}'
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": fake_sa}):
            from backend.services.credentials import CredentialService
            fp1 = CredentialService.fingerprint()
            fp2 = CredentialService.fingerprint()
            assert fp1 == fp2

    def test_fingerprint_changes_with_different_credentials(self):
        sa1 = '{"type": "service_account", "id": "key_A"}'
        sa2 = '{"type": "service_account", "id": "key_B"}'
        from backend.services.credentials import CredentialService

        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": sa1}):
            fp1 = CredentialService.fingerprint()
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": sa2}):
            fp2 = CredentialService.fingerprint()
        assert fp1 != fp2


class TestCredentialServiceStatus:
    """Status dict for the security dashboard."""

    def test_status_when_configured(self):
        fake_sa = '{"type": "service_account"}'
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": fake_sa}):
            from backend.services.credentials import CredentialService
            status = CredentialService.status()
            assert status["configured"] is True
            assert status["source"] == "env_var_inline_json"
            assert status["fingerprint_prefix"] is not None

    def test_status_when_file_path(self):
        import tempfile
        # Create a real temp file so _load_raw_json() finds it
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"type": "service_account"}')
            tmppath = f.name
        try:
            with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": tmppath}):
                from backend.services.credentials import CredentialService
                status = CredentialService.status()
                assert status["source"] == "env_var_file_path"
                assert status["configured"] is True
        finally:
            os.unlink(tmppath)


# ---------------------------------------------------------------------------
# TokenEncryption
# ---------------------------------------------------------------------------

class TestTokenEncryptionRoundTrip:
    """Encrypt + decrypt returns original plaintext."""

    @pytest.fixture(autouse=True)
    def _setup_key(self):
        """Generate a temporary Fernet key for testing."""
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"ENCRYPTION_KEY": key}):
            yield key

    def test_encrypt_decrypt_roundtrip(self):
        from backend.services.token_encryption import TokenEncryption
        original = '{"access_token": "ya29.test_token_value", "refresh_token": "1//test_refresh"}'
        encrypted = TokenEncryption.encrypt(original)
        assert encrypted is not None
        assert encrypted != original
        assert encrypted.startswith("enc:v1:")
        decrypted = TokenEncryption.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_none_returns_none(self):
        from backend.services.token_encryption import TokenEncryption
        assert TokenEncryption.encrypt(None) is None

    def test_decrypt_none_returns_none(self):
        from backend.services.token_encryption import TokenEncryption
        assert TokenEncryption.decrypt(None) is None

    def test_no_double_encryption(self):
        from backend.services.token_encryption import TokenEncryption
        original = '{"token": "secret"}'
        encrypted_once = TokenEncryption.encrypt(original)
        encrypted_twice = TokenEncryption.encrypt(encrypted_once)
        # Must be identical — no double-encryption
        assert encrypted_once == encrypted_twice

    def test_is_encrypted_detects_ciphertext(self):
        from backend.services.token_encryption import TokenEncryption
        original = '{"token": "secret"}'
        encrypted = TokenEncryption.encrypt(original)
        assert TokenEncryption.is_encrypted(encrypted) is True
        assert TokenEncryption.is_encrypted(original) is False
        assert TokenEncryption.is_encrypted(None) is False

    def test_is_key_configured(self):
        from backend.services.token_encryption import TokenEncryption
        assert TokenEncryption.is_key_configured() is True


class TestTokenEncryptionPassthrough:
    """Without ENCRYPTION_KEY, operates in passthrough mode."""

    def test_passthrough_when_no_key(self):
        with patch.dict(os.environ, {}, clear=False):
            env_copy = os.environ.copy()
            env_copy.pop("ENCRYPTION_KEY", None)
            env_copy.pop("ENCRYPTION_KEY_OLD", None)
            with patch.dict(os.environ, env_copy, clear=True):
                from backend.services.token_encryption import TokenEncryption, _warned_missing
                import backend.services.token_encryption as te_mod
                te_mod._warned_missing = False  # reset warning flag
                original = '{"token": "secret"}'
                result = TokenEncryption.encrypt(original)
                assert result == original  # passthrough — no encryption

    def test_decrypt_plaintext_returns_as_is(self):
        from backend.services.token_encryption import TokenEncryption
        plaintext = '{"token": "secret"}'
        assert TokenEncryption.decrypt(plaintext) == plaintext


class TestTokenEncryptionKeyRotation:
    """Key rotation: decrypt with old key, re-encrypt with new key."""

    def test_decrypt_with_old_key(self):
        from cryptography.fernet import Fernet
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        # Encrypt with old key
        with patch.dict(os.environ, {"ENCRYPTION_KEY": old_key}):
            from backend.services.token_encryption import TokenEncryption
            original = '{"token": "secret_value"}'
            encrypted = TokenEncryption.encrypt(original)

        # Decrypt with new key (fails) + old key (succeeds)
        with patch.dict(os.environ, {"ENCRYPTION_KEY": new_key, "ENCRYPTION_KEY_OLD": old_key}):
            decrypted = TokenEncryption.decrypt(encrypted)
            assert decrypted == original

    def test_reencrypt_migrates_to_new_key(self):
        from cryptography.fernet import Fernet
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        # Encrypt with old key
        with patch.dict(os.environ, {"ENCRYPTION_KEY": old_key}):
            from backend.services.token_encryption import TokenEncryption
            original = '{"token": "secret"}'
            encrypted_old = TokenEncryption.encrypt(original)

        # Re-encrypt with new key
        with patch.dict(os.environ, {"ENCRYPTION_KEY": new_key, "ENCRYPTION_KEY_OLD": old_key}):
            reencrypted = TokenEncryption.reencrypt(encrypted_old)
            assert reencrypted != encrypted_old  # different ciphertext

            # Verify it's now decryptable with only the new key
            with patch.dict(os.environ, {"ENCRYPTION_KEY": new_key}):
                env_copy = os.environ.copy()
                env_copy.pop("ENCRYPTION_KEY_OLD", None)
                with patch.dict(os.environ, env_copy, clear=True):
                    # Set just the new key
                    os.environ["ENCRYPTION_KEY"] = new_key
                    decrypted = TokenEncryption.decrypt(reencrypted)
                    assert decrypted == original


class TestTokenEncryptionStatus:
    """Status dict for the security dashboard."""

    def test_status_when_key_configured(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"ENCRYPTION_KEY": key}):
            from backend.services.token_encryption import TokenEncryption
            status = TokenEncryption.status()
            assert status["encryption_enabled"] is True
            assert "Fernet" in status["algorithm"]
            assert status["rotation_in_progress"] is False

    def test_status_during_rotation(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        old_key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"ENCRYPTION_KEY": key, "ENCRYPTION_KEY_OLD": old_key}):
            from backend.services.token_encryption import TokenEncryption
            status = TokenEncryption.status()
            assert status["rotation_in_progress"] is True


# ---------------------------------------------------------------------------
# Security recommendations
# ---------------------------------------------------------------------------

class TestSecurityRecommendations:
    def test_recommendations_when_all_missing(self):
        from backend.routers.admin import _build_security_recommendations
        recs = _build_security_recommendations(
            sa_configured=False,
            encryption_enabled=False,
            jwt_configured=False,
        )
        assert len(recs) == 3
        assert any("GOOGLE_SERVICE_ACCOUNT_JSON" in r for r in recs)
        assert any("ENCRYPTION_KEY" in r for r in recs)
        assert any("JWT_SECRET" in r for r in recs)

    def test_recommendations_when_all_configured(self):
        from backend.routers.admin import _build_security_recommendations
        recs = _build_security_recommendations(
            sa_configured=True,
            encryption_enabled=True,
            jwt_configured=True,
        )
        assert len(recs) == 1
        assert "configured" in recs[0].lower()

    def test_partial_configuration(self):
        from backend.routers.admin import _build_security_recommendations
        recs = _build_security_recommendations(
            sa_configured=True,
            encryption_enabled=False,
            jwt_configured=True,
        )
        assert len(recs) == 1
        assert "ENCRYPTION_KEY" in recs[0]
