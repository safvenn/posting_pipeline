"""YouTube OAuth2 client builder using stored refresh tokens."""
from __future__ import annotations

import logging

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from backend.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

TOKEN_URI = "https://oauth2.googleapis.com/token"


def get_youtube_client(channel: str):
    """
    Build and return an authenticated YouTube API client for the given channel.
    Uses system-wide Google OAuth client ID/secret, with channel refresh token from DB.
    """
    default_client_id, default_client_secret = settings.get_google_oauth_credentials()
    client_id = default_client_id
    client_secret = default_client_secret
    refresh_token = ""

    # Check DB ChannelConfig first
    try:
        from backend.database import SessionLocal
        from backend.models import ChannelConfig
        with SessionLocal() as db:
            cfg = db.query(ChannelConfig).filter(ChannelConfig.key == channel, ChannelConfig.is_active == True).first()
            if cfg:
                if cfg.client_id:
                    client_id = cfg.client_id
                if cfg.client_secret:
                    client_secret = cfg.client_secret
                if cfg.refresh_token:
                    refresh_token = cfg.refresh_token
    except Exception as exc:
        logger.debug("ChannelConfig DB lookup skipped: %s", exc)

    # Fallback to legacy .env settings if not found in DB
    if not refresh_token:
        if channel == "channel_a":
            client_id = client_id or settings.yt_client_id_channel_a
            client_secret = client_secret or settings.yt_client_secret_channel_a
            refresh_token = settings.yt_refresh_token_channel_a
        elif channel == "channel_b":
            client_id = client_id or settings.yt_client_id_channel_b
            client_secret = client_secret or settings.yt_client_secret_channel_b
            refresh_token = settings.yt_refresh_token_channel_b

    if not (client_id and client_secret and refresh_token):
        raise ValueError(
            f"YouTube credentials not configured for channel '{channel}'. "
            "Please click 'Authorize with Google' on the Channels page."
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )

    # Force a token refresh to validate credentials
    if not creds.valid:
        creds.refresh(Request())

    service = build("youtube", "v3", credentials=creds, cache_discovery=False)
    logger.debug("YouTube client built for %s", channel)
    return service


def is_quota_error(exc: Exception) -> bool:
    """Detect YouTube API quota exhaustion errors. Does NOT match auth/permission 403 errors."""
    s = str(exc)
    return (
        "quotaExceeded" in s
        or "dailyLimitExceeded" in s
        or "rateLimitExceeded" in s
        or "userRateLimitExceeded" in s
        or "429" in s
    )


def quota_error_message(exc: Exception) -> str:
    """Return a standardised quota error message for the dashboard."""
    return f"YouTube API quota exceeded (10,000 units/day limit): {exc}"
