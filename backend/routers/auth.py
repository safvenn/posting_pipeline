"""JWT-based single-user authentication router — with stateful refresh tokens.

Endpoints (all public — no api-key required):
  POST /api/auth/login   — username + password → { access_token, refresh_token }
  POST /api/auth/refresh — refresh_token → { access_token, refresh_token } (rotated)
  GET  /api/auth/me      — verify access_token → { username, sessions }
  POST /api/auth/logout  — revoke current refresh token on server
  POST /api/auth/logout-all — revoke ALL refresh tokens for this user
  GET  /api/auth/sessions — list active sessions for current user

Security improvements over previous version:
  - Refresh tokens are stored as SHA-256 hashes in the database
  - Logout actually revokes the token server-side (can't be reused)
  - Logout-all revokes all sessions (use after password compromise)
  - Token rotation: each refresh invalidates the old token and issues a new one
  - Login success/failure recorded in AuditLog
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models import RefreshToken
from backend.services.audit import AuditService, AuthEvent, Outcome

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

class MeResponse(BaseModel):
    username: str

class SessionInfo(BaseModel):
    session_id: int
    device_id: Optional[str]
    user_agent: Optional[str]
    issued_at: datetime
    last_used_at: Optional[datetime]
    issued_to_ip: Optional[str]

class SessionsResponse(BaseModel):
    username: str
    active_sessions: list[SessionInfo]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_token(raw_token: str) -> str:
    """Return the SHA-256 hex digest of a raw token. Never store raw tokens."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _create_access_token(username: str) -> str:
    """Create a short-lived JWT access token."""
    secret = settings.jwt_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET not configured in environment",
        )
    payload = {
        "sub": username,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": datetime.now(timezone.utc),
        "jti": secrets.token_hex(8),  # JWT ID — unique per token for future revocation if needed
    }
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def _decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token. Raises HTTPException on failure."""
    secret = settings.jwt_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET not configured in environment",
        )
    try:
        return jwt.decode(token, secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def _issue_refresh_token(
    db: Session,
    username: str,
    request: Optional[Request] = None,
) -> str:
    """
    Generate a new opaque refresh token, hash it, and persist a DB record.
    Returns the raw token (caller must send to client).
    """
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

    record = RefreshToken(
        token_hash=token_hash,
        username=username,
        device_id=None,  # extensible: pass device_id from client in future
        user_agent=request.headers.get("User-Agent", "")[:512] if request else None,
        issued_to_ip=request.client.host if request and request.client else None,
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()
    return raw_token


def _validate_refresh_token(db: Session, raw_token: str) -> RefreshToken:
    """
    Look up and validate a raw refresh token.
    Raises HTTPException(401) if not found, revoked, or expired.
    """
    token_hash = _hash_token(raw_token)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found or already used",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if record.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if record.is_expired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired — please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return record


def _revoke_refresh_token(
    db: Session,
    record: RefreshToken,
    reason: str = "logout",
) -> None:
    """Mark a refresh token as revoked."""
    record.is_revoked = True
    record.revoked_at = datetime.now(timezone.utc)
    record.revoke_reason = reason
    db.commit()


def _revoke_all_for_user(db: Session, username: str, reason: str = "logout") -> int:
    """Revoke all active refresh tokens for a user. Returns count revoked."""
    now = datetime.now(timezone.utc)
    active = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.username == username,
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > now,
        )
        .all()
    )
    for record in active:
        record.is_revoked = True
        record.revoked_at = now
        record.revoke_reason = reason
    db.commit()
    return len(active)


# ---------------------------------------------------------------------------
# Dependency: get current user from access token
# ---------------------------------------------------------------------------

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """FastAPI dependency — returns username from a valid JWT access token."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decode_access_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Expected access token",
        )
    username: Optional[str] = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )
    return username


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Authenticate with username and password, return JWT access + refresh tokens."""
    expected_user = settings.admin_username
    expected_hash = settings.admin_password_hash
    audit = AuditService(db, actor=body.username, actor_ip=request.client.host if request.client else None)

    if not expected_hash:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_PASSWORD_HASH not configured in environment",
        )

    if body.username != expected_user or not _verify_password(body.password, expected_hash):
        audit.login_failure(body.username, reason="invalid credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    access_token = _create_access_token(body.username)
    raw_refresh = _issue_refresh_token(db, body.username, request)
    audit.login_success(body.username)
    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    body: RefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Exchange a refresh token for a new access token.

    Implements rotation: the old refresh token is immediately revoked
    and a new one is issued. If the old token is presented again
    (token theft replay), it will be rejected.
    """
    record = _validate_refresh_token(db, body.refresh_token)
    audit = AuditService(db, actor=record.username, actor_ip=request.client.host if request.client else None)

    # Update usage metadata
    record.last_used_at = datetime.now(timezone.utc)
    record.use_count = (record.use_count or 0) + 1
    db.commit()

    # Issue new tokens
    access_token = _create_access_token(record.username)
    raw_new_refresh = _issue_refresh_token(db, record.username, request)

    # Rotate: revoke old refresh token AFTER new one is committed
    _revoke_refresh_token(db, record, reason="rotation")
    audit.token_rotated(record.username)

    return TokenResponse(access_token=access_token, refresh_token=raw_new_refresh)


@router.get("/me", response_model=MeResponse)
def me(username: str = Depends(get_current_user)):
    """Return info for the currently logged-in user."""
    return MeResponse(username=username)


@router.post("/logout")
def logout(
    body: RefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(get_current_user),
):
    """
    Revoke the provided refresh token server-side.

    The client should discard both the access and refresh tokens after calling this.
    The access token will remain valid until it expires (short-lived by design).
    """
    audit = AuditService(db, actor=username, actor_ip=request.client.host if request.client else None)
    try:
        record = _validate_refresh_token(db, body.refresh_token)
        _revoke_refresh_token(db, record, reason="logout")
    except HTTPException:
        # Token already invalid — logout is idempotent
        pass
    audit.logout(username)
    return {"detail": "Logged out successfully. Refresh token has been revoked."}


@router.post("/logout-all")
def logout_all(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(get_current_user),
):
    """
    Revoke ALL active refresh tokens for the current user.

    Use this after a suspected security compromise — forces re-login on all devices.
    """
    audit = AuditService(db, actor=username, actor_ip=request.client.host if request.client else None)
    count = _revoke_all_for_user(db, username, reason="logout-all")
    audit.token_revoke_all(username)
    return {
        "detail": f"All sessions terminated. {count} refresh token(s) revoked.",
        "revoked_count": count,
    }


@router.get("/sessions", response_model=SessionsResponse)
def list_sessions(
    db: Session = Depends(get_db),
    username: str = Depends(get_current_user),
):
    """List all active (non-revoked, non-expired) sessions for the current user."""
    now = datetime.now(timezone.utc)
    active = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.username == username,
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > now,
        )
        .order_by(RefreshToken.issued_at.desc())
        .all()
    )
    return SessionsResponse(
        username=username,
        active_sessions=[
            SessionInfo(
                session_id=r.id,
                device_id=r.device_id,
                user_agent=r.user_agent,
                issued_at=r.issued_at,
                last_used_at=r.last_used_at,
                issued_to_ip=r.issued_to_ip,
            )
            for r in active
        ],
    )
