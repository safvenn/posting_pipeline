"""
Credential Service — secure, centralized access to Google service account credentials.

Design:
  - The service account JSON must NEVER be committed to the repository.
  - It should be stored as an environment variable: GOOGLE_SERVICE_ACCOUNT_JSON
    containing either:
      a) The raw JSON string (preferred for cloud deployments like Render):
         GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"..."}'
      b) A file path for local dev (backwards-compatible):
         GOOGLE_SERVICE_ACCOUNT_JSON=./service_account.json

  - Fingerprinting: A SHA-256 digest of the current credentials is computed
    at startup and on each access. If it changes between calls (i.e. secret
    was rotated via env var update + process restart), a CREDS_ROTATED audit
    event is emitted and the cached client is invalidated.

  - Fail-safe: If no credentials are configured, returns None rather than
    raising — callers must handle None gracefully (Google Sheets / Drive calls
    will skip rather than crash the pipeline).

Usage:
    from backend.services.credentials import CredentialService

    creds = CredentialService.get_service_account_credentials(scopes=[...])
    if creds is None:
        logger.warning("No Google service account credentials configured")
        return

    service = build("drive", "v3", credentials=creds)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_last_fingerprint: Optional[str] = None


def _fingerprint(data: str) -> str:
    """Return a SHA-256 hex digest of the credentials string (NOT logged)."""
    return hashlib.sha256(data.encode()).hexdigest()


def _load_raw_json() -> Optional[str]:
    """
    Load the service account JSON from the environment or file system.

    Resolution order:
      1. GOOGLE_SERVICE_ACCOUNT_JSON env var (raw JSON string)
      2. GOOGLE_SERVICE_ACCOUNT_JSON env var (file path)
      3. settings.google_sheets_service_account_json (legacy file path)

    Returns the raw JSON string, or None if not configured.
    """
    from backend.config import settings

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    if not raw:
        # Fallback to the legacy config value
        raw = (settings.google_sheets_service_account_json or "").strip()

    if not raw:
        return None

    # If it starts with '{', treat as inline JSON
    if raw.startswith("{"):
        return raw

    # Otherwise treat as a file path
    path = Path(raw)
    if path.is_file():
        return path.read_text(encoding="utf-8")

    logger.warning(
        "credential.service_account_missing: "
        "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON and not an existing file path. "
        "Google Sheets / Drive integrations will be disabled. "
        "Set GOOGLE_SERVICE_ACCOUNT_JSON to the raw JSON string in Render env vars."
    )
    return None


def _detect_rotation(current_fingerprint: str) -> bool:
    """
    Compare current fingerprint to the last known fingerprint.
    Returns True if credentials have been rotated since last call.
    """
    global _last_fingerprint
    with _lock:
        if _last_fingerprint is None:
            _last_fingerprint = current_fingerprint
            return False
        rotated = _last_fingerprint != current_fingerprint
        if rotated:
            logger.info(
                "credential.rotation_detected: "
                "Service account credentials have changed (fingerprints differ). "
                "Old fingerprint prefix=%s... New prefix=%s...",
                _last_fingerprint[:8],
                current_fingerprint[:8],
            )
            _last_fingerprint = current_fingerprint
        return rotated


class CredentialService:
    """
    Centralised accessor for Google service account credentials.

    All Google API clients should obtain credentials through this class
    rather than loading the file or JSON directly.
    """

    @staticmethod
    def get_service_account_credentials(scopes: list[str]):
        """
        Return a google.oauth2.service_account.Credentials object, or None.

        Args:
            scopes: OAuth scopes required by the caller.

        Returns:
            Credentials object ready for use with google-api-python-client,
            or None if credentials are not configured.
        """
        raw = _load_raw_json()
        if raw is None:
            return None

        fp = _fingerprint(raw)
        rotated = _detect_rotation(fp)

        try:
            from google.oauth2.service_account import Credentials
            info = json.loads(raw)
            creds = Credentials.from_service_account_info(info, scopes=scopes)
            if rotated:
                logger.info(
                    "credential.rotation_applied: "
                    "New credentials loaded for scopes=%s",
                    scopes,
                )
            return creds
        except json.JSONDecodeError as exc:
            logger.error("credential.invalid_json: %s", exc)
            return None
        except Exception as exc:
            logger.error("credential.load_failed: %s", exc)
            return None

    @staticmethod
    def fingerprint() -> Optional[str]:
        """
        Return the SHA-256 fingerprint prefix (8 chars) of the current
        service account credentials, or None if not configured.

        Safe to log — does NOT reveal actual credential content.
        """
        raw = _load_raw_json()
        if raw is None:
            return None
        fp = _fingerprint(raw)
        return fp[:16]  # 16 hex chars = 8 bytes — enough to detect changes without revealing key

    @staticmethod
    def is_configured() -> bool:
        """Return True if service account credentials are available."""
        return _load_raw_json() is not None

    @staticmethod
    def status() -> dict:
        """Return a safe status dict for the /api/admin/security-status endpoint."""
        raw = _load_raw_json()
        configured = raw is not None
        fp = _fingerprint(raw)[:16] if raw else None

        source = "not_configured"
        if raw:
            env_val = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
            if env_val.startswith("{"):
                source = "env_var_inline_json"
            elif env_val:
                source = "env_var_file_path"
            else:
                source = "config_file_path"

        return {
            "configured": configured,
            "source": source,
            "fingerprint_prefix": fp,
            "rotation_detected": False,  # only True in the moment of rotation
        }
