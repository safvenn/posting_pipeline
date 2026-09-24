"""
Token Encryption Service — at-rest encryption for OAuth tokens stored in DB.

Threat model:
  - If an attacker gets read access to the PostgreSQL database (e.g. via
    SQL injection), raw OAuth tokens would give them full Google API access.
  - This service encrypts token data before DB storage using Fernet symmetric
    encryption (AES-128-CBC with HMAC-SHA256 authentication).
  - The ENCRYPTION_KEY env var is the only thing that must stay secret.
  - Without the ENCRYPTION_KEY, existing ciphertext is unreadable.

Key management:
  - ENCRYPTION_KEY must be a 32-byte (44-char base64url) Fernet key.
  - Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  - Store ONLY in the Render environment variables / secrets manager.
  - NEVER commit to the repository.
  - Key rotation: set ENCRYPTION_KEY_OLD=<old_key> + ENCRYPTION_KEY=<new_key>.
    The service will decrypt with old key then re-encrypt with new key
    transparently on next read (lazy re-encryption pattern).

Fallback:
  - If ENCRYPTION_KEY is not set, the service operates in PASSTHROUGH mode:
    data is stored as-is (same as before this feature was added).
  - This ensures zero-downtime rollout — existing unencrypted tokens keep
    working, and new tokens start being encrypted once the key is set.
  - A WARNING is logged at startup if the key is not configured.

Usage:
    from backend.services.token_encryption import TokenEncryption

    # Encrypting before DB write:
    channel.token_data = TokenEncryption.encrypt(raw_token_json)

    # Decrypting after DB read:
    raw = TokenEncryption.decrypt(channel.token_data)
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_warned_missing = False


def _get_fernet(key_env: str = "ENCRYPTION_KEY"):
    """Return a Fernet instance for the given key env var, or None."""
    key = os.environ.get(key_env, "").strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode())
    except Exception as exc:
        logger.error("token_encryption.invalid_key env=%s error=%s", key_env, exc)
        return None


def _warn_missing_key() -> None:
    global _warned_missing
    if not _warned_missing:
        logger.warning(
            "token_encryption.no_key: ENCRYPTION_KEY is not set. "
            "OAuth tokens are stored in plaintext. "
            "Generate a key with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
            "and set ENCRYPTION_KEY in Render environment variables."
        )
        _warned_missing = True


class TokenEncryption:
    """
    Transparent at-rest encryption for OAuth tokens.

    All methods are safe to call even if the key is not configured —
    they fall back to passthrough (plain text storage).
    """

    # Prefix on encrypted blobs so we can distinguish them from plaintext
    _PREFIX = "enc:v1:"

    @classmethod
    def encrypt(cls, plaintext: Optional[str]) -> Optional[str]:
        """
        Encrypt a token string for DB storage.

        Returns:
          - "enc:v1:<fernet_ciphertext>" if key is configured
          - plaintext as-is if key is not configured (passthrough)
          - None if plaintext is None
        """
        if plaintext is None:
            return None

        # Don't double-encrypt already encrypted values
        if plaintext.startswith(cls._PREFIX):
            return plaintext

        fernet = _get_fernet()
        if fernet is None:
            _warn_missing_key()
            return plaintext  # passthrough

        try:
            ciphertext = fernet.encrypt(plaintext.encode()).decode()
            return f"{cls._PREFIX}{ciphertext}"
        except Exception as exc:
            logger.error("token_encryption.encrypt_failed: %s", exc)
            return plaintext  # safe fallback to plaintext

    @classmethod
    def decrypt(cls, value: Optional[str]) -> Optional[str]:
        """
        Decrypt a token string retrieved from DB.

        Handles:
          - Encrypted values (prefixed with "enc:v1:")
          - Legacy plaintext values (no prefix) — returned as-is
          - Key rotation: tries ENCRYPTION_KEY first, then ENCRYPTION_KEY_OLD
          - None input

        Returns:
          - Decrypted plaintext string
          - Original value if not encrypted (backwards compatible)
          - None if input is None
        """
        if value is None:
            return None

        if not value.startswith(cls._PREFIX):
            return value  # plaintext passthrough (pre-encryption or key not set)

        ciphertext = value[len(cls._PREFIX):]

        # Try current key first
        fernet = _get_fernet("ENCRYPTION_KEY")
        if fernet is not None:
            try:
                return fernet.decrypt(ciphertext.encode()).decode()
            except Exception:
                pass  # may be encrypted with old key — try rotation

        # Try old key (rotation support)
        fernet_old = _get_fernet("ENCRYPTION_KEY_OLD")
        if fernet_old is not None:
            try:
                plaintext = fernet_old.decrypt(ciphertext.encode()).decode()
                logger.info(
                    "token_encryption.rotation: "
                    "Decrypted with ENCRYPTION_KEY_OLD. "
                    "Re-encrypt this token by updating the channel credentials."
                )
                return plaintext
            except Exception as exc:
                logger.error("token_encryption.decrypt_failed_both_keys: %s", exc)

        logger.error(
            "token_encryption.decrypt_failed: "
            "Cannot decrypt token — key may be wrong or token is corrupted"
        )
        return None  # caller must handle None

    @classmethod
    def is_encrypted(cls, value: Optional[str]) -> bool:
        """Return True if the value is encrypted by this service."""
        return bool(value and value.startswith(cls._PREFIX))

    @classmethod
    def is_key_configured(cls) -> bool:
        """Return True if ENCRYPTION_KEY is set and valid."""
        return _get_fernet("ENCRYPTION_KEY") is not None

    @classmethod
    def reencrypt(cls, value: Optional[str]) -> Optional[str]:
        """
        Decrypt (using current or old key) and re-encrypt with the current key.
        Used during key rotation to migrate stored tokens.
        """
        if value is None:
            return None
        plaintext = cls.decrypt(value)
        if plaintext is None:
            return value  # can't decrypt, leave as-is
        return cls.encrypt(plaintext)

    @classmethod
    def status(cls) -> dict:
        """Return encryption status for the security dashboard."""
        key_configured = cls.is_key_configured()
        old_key_present = bool(os.environ.get("ENCRYPTION_KEY_OLD", "").strip())
        return {
            "encryption_enabled": key_configured,
            "rotation_in_progress": key_configured and old_key_present,
            "algorithm": "Fernet(AES-128-CBC + HMAC-SHA256)" if key_configured else "none (plaintext)",
        }
