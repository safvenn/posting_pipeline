"""JWT-based single-user authentication router.

Endpoints (all public — no api-key required):
  POST /api/auth/login   — username + password → { access_token, refresh_token }
  POST /api/auth/refresh — refresh_token → { access_token }
  GET  /api/auth/me      — verify access_token → { username }
  POST /api/auth/logout  — client-side only (tokens are stateless; just confirm ok)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

from backend.config import settings

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_token(data: dict, expires_delta: timedelta) -> str:
    secret = settings.jwt_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET not configured in .env",
        )
    payload = {**data, "exp": datetime.now(timezone.utc) + expires_delta}
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> dict:
    secret = settings.jwt_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET not configured in .env",
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
    payload = _decode_token(credentials.credentials)
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
def login(body: LoginRequest):
    """Authenticate with username and password, return JWT tokens."""
    expected_user = settings.admin_username
    expected_hash = settings.admin_password_hash

    if not expected_hash:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_PASSWORD_HASH not configured in .env",
        )

    if body.username != expected_user or not _verify_password(body.password, expected_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    access_token = _create_token(
        {"sub": body.username, "type": "access"},
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh_token = _create_token(
        {"sub": body.username, "type": "refresh"},
        timedelta(days=settings.refresh_token_expire_days),
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest):
    """Exchange a refresh token for a new access token."""
    payload = _decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Expected refresh token",
        )
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )
    access_token = _create_token(
        {"sub": username, "type": "access"},
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    # Rotate refresh token too
    new_refresh = _create_token(
        {"sub": username, "type": "refresh"},
        timedelta(days=settings.refresh_token_expire_days),
    )
    return TokenResponse(access_token=access_token, refresh_token=new_refresh)


@router.get("/me", response_model=MeResponse)
def me(username: str = Depends(get_current_user)):
    """Return info for the currently logged-in user."""
    return MeResponse(username=username)


@router.post("/logout")
def logout():
    """Client-side logout. Tokens are stateless; just return success."""
    return {"detail": "Logged out. Delete your tokens client-side."}
