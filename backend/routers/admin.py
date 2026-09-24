"""
Admin security router — credential health dashboard + JWT rotation.

Endpoints (all require api-key auth):
  GET  /api/admin/security-status  — credential health snapshot
  POST /api/admin/rotate-secret    — zero-downtime JWT secret rotation

JWT Secret Rotation design:
  - The JWT secret is held in memory (settings.jwt_secret at startup).
  - Rotation = replace the in-memory secret + revoke ALL existing refresh tokens.
  - All users are forced to re-login after rotation.
  - The new secret MUST also be set in the Render env var (JWT_SECRET) before
    the next process restart — otherwise the next deploy reverts to the old secret
    and all tokens from the rotated period become invalid.
  - The endpoint accepts a ?new_secret parameter. If omitted, a cryptographically
    secure 64-char hex secret is auto-generated.

WARNING: This is a destructive operation. All active sessions are invalidated.
         Only operators with the API key can call this endpoint.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.audit import AuditService, SystemEvent, ConfigEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class CredentialStatus(BaseModel):
    configured: bool
    source: str
    fingerprint_prefix: Optional[str]


class EncryptionStatus(BaseModel):
    encryption_enabled: bool
    rotation_in_progress: bool
    algorithm: str


class JWTStatus(BaseModel):
    secret_configured: bool
    algorithm: str
    access_token_expire_minutes: int
    refresh_token_expire_days: int
    active_sessions: int


class SecurityStatusResponse(BaseModel):
    service_account: CredentialStatus
    token_encryption: EncryptionStatus
    jwt: JWTStatus
    security_recommendations: list[str]
    checked_at: str


class RotateSecretResponse(BaseModel):
    detail: str
    sessions_revoked: int
    rotated_at: str
    new_secret_preview: str  # first 8 chars only — for verification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_active_session_count(db: Session) -> int:
    from backend.models import RefreshToken
    from sqlalchemy import func
    now = datetime.now(timezone.utc)
    return (
        db.query(func.count(RefreshToken.id))
        .filter(
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > now,
        )
        .scalar() or 0
    )


def _build_security_recommendations(
    sa_configured: bool,
    encryption_enabled: bool,
    jwt_configured: bool,
) -> list[str]:
    recommendations = []
    if not sa_configured:
        recommendations.append(
            "Set GOOGLE_SERVICE_ACCOUNT_JSON env var with your service account JSON "
            "(raw JSON string, not a file path) for Google Sheets/Drive integration."
        )
    if not encryption_enabled:
        recommendations.append(
            "Set ENCRYPTION_KEY env var to enable at-rest encryption for stored OAuth tokens. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    if not jwt_configured:
        recommendations.append(
            "Set JWT_SECRET env var to a cryptographically random 64-char hex value. "
            "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if not recommendations:
        recommendations.append(
            "All critical security settings are configured. "
            "Rotate JWT_SECRET and ENCRYPTION_KEY every 90 days."
        )
    return recommendations


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/security-status", response_model=SecurityStatusResponse)
def security_status(db: Session = Depends(get_db)):
    """
    Return a security health snapshot.

    Checks:
      - Google service account credential configuration and source
      - OAuth token at-rest encryption status
      - JWT configuration and active session count
      - Security recommendations

    No sensitive values are ever returned — only presence/absence and
    fingerprint prefixes safe to log.
    """
    from backend.services.credentials import CredentialService
    from backend.services.token_encryption import TokenEncryption
    from backend.config import settings

    sa_status = CredentialService.status()
    enc_status = TokenEncryption.status()
    jwt_secret_configured = bool(settings.jwt_secret)

    active_sessions = _get_active_session_count(db)

    recommendations = _build_security_recommendations(
        sa_configured=sa_status["configured"],
        encryption_enabled=enc_status["encryption_enabled"],
        jwt_configured=jwt_secret_configured,
    )

    return SecurityStatusResponse(
        service_account=CredentialStatus(**sa_status),
        token_encryption=EncryptionStatus(**enc_status),
        jwt=JWTStatus(
            secret_configured=jwt_secret_configured,
            algorithm=settings.jwt_algorithm,
            access_token_expire_minutes=settings.access_token_expire_minutes,
            refresh_token_expire_days=settings.refresh_token_expire_days,
            active_sessions=active_sessions,
        ),
        security_recommendations=recommendations,
        checked_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    )


@router.post("/rotate-secret", response_model=RotateSecretResponse)
def rotate_jwt_secret(
    db: Session = Depends(get_db),
    actor: str = Query("operator", description="Who is performing the rotation"),
    new_secret: Optional[str] = Query(
        None,
        description=(
            "New JWT secret. If omitted, a cryptographically secure "
            "64-char hex secret is auto-generated."
        ),
        min_length=32,
    ),
    confirm: bool = Query(False, description="Must be true — rotation invalidates ALL sessions"),
):
    """
    Rotate the JWT signing secret. ALL active sessions are invalidated.

    **This is a destructive operation.** All users will be logged out.

    After calling this endpoint, you MUST also update JWT_SECRET in your
    Render environment variables before the next deploy, otherwise the
    next restart will revert to the old secret.

    Requires ?confirm=true to execute.
    """
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Pass ?confirm=true to execute. "
                "WARNING: This will invalidate ALL active sessions."
            ),
        )

    # Generate or validate new secret
    if new_secret:
        if len(new_secret) < 32:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="new_secret must be at least 32 characters",
            )
        secret_value = new_secret
    else:
        secret_value = secrets.token_hex(32)  # 64-char hex = 256-bit entropy

    # Revoke ALL active refresh tokens (forces re-login)
    from backend.models import RefreshToken
    now = datetime.now(timezone.utc)
    active_tokens = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > now,
        )
        .all()
    )
    revoked_count = 0
    for token in active_tokens:
        token.is_revoked = True
        token.revoked_at = now
        revoked_count += 1
    db.commit()

    # Rotate the in-memory secret
    from backend.config import settings
    old_prefix = (settings.jwt_secret or "")[:4] + "..." if settings.jwt_secret else "none"
    settings.jwt_secret = secret_value

    # Audit
    audit = AuditService(db, actor=actor)
    audit.log(
        SystemEvent.SECURITY_ALERT,
        description=(
            f"JWT secret rotated by {actor}. "
            f"Revoked {revoked_count} active refresh tokens. "
            f"Old secret prefix: {old_prefix}"
        ),
    )

    logger.warning(
        "security.jwt_secret_rotated actor=%s sessions_revoked=%d "
        "new_secret_prefix=%s... "
        "ACTION REQUIRED: Update JWT_SECRET env var in Render before next deploy.",
        actor, revoked_count, secret_value[:8],
    )

    return RotateSecretResponse(
        detail=(
            f"JWT secret rotated. {revoked_count} sessions revoked. "
            f"IMPORTANT: Update JWT_SECRET={secret_value} in Render env vars before next deploy."
        ),
        sessions_revoked=revoked_count,
        rotated_at=now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        new_secret_preview=secret_value[:8] + "...",
    )
