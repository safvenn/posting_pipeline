"""JWT authentication router — single-user login/refresh/logout/me."""
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
# Helpers
# ---------------------------------------------------------------------------

def _make_token(sub: str, kind: str, expire_delta: timedelta) -> str:
    """Create a signed JWT with a 'kind' claim to distinguish access/refresh."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "kind": kind,
        "iat": now,
        "exp": now + expire_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str, expected_kind: str) -> dict:
    """Decode and validate a JWT; raise 401 on any failure."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("kind") != expected_kind:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong token type",
        )
    return payload


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def is_valid_token_or_key(token: str) -> bool:
    """Validate either static API key or signed JWT access token."""
    if settings.api_key and token == settings.api_key:
        return True
    if settings.jwt_secret:
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
            )
            if payload.get("kind") == "access" and payload.get("sub") == settings.admin_username:
                return True
        except Exception:
            return False
    return False


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """Dependency — extract + validate access token, return username."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decode_token(credentials.credentials, "access")
    return payload["sub"]


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


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    """Verify credentials and return access + refresh tokens."""
    valid_user = (
        body.username == settings.admin_username
        and settings.admin_password_hash
        and verify_password(body.password, settings.admin_password_hash)
    )
    if not valid_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    access_token = _make_token(
        sub=settings.admin_username,
        kind="access",
        expire_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh_token = _make_token(
        sub=settings.admin_username,
        kind="refresh",
        expire_delta=timedelta(days=settings.refresh_token_expire_days),
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(body: RefreshRequest):
    """Exchange a valid refresh token for a new access token."""
    payload = _decode_token(body.refresh_token, "refresh")
    access_token = _make_token(
        sub=payload["sub"],
        kind="access",
        expire_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    return AccessTokenResponse(access_token=access_token)


@router.post("/logout")
def logout():
    """Stateless logout — client is responsible for dropping tokens."""
    return {"detail": "Logged out"}


@router.get("/me")
def me(username: str = Depends(get_current_user)):
    """Return the currently authenticated user's username."""
    return {"username": username}
