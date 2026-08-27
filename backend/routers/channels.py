from __future__ import annotations

import logging
import urllib.parse
import uuid
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import uuid

from backend.database import get_db
from backend.models import ChannelConfig
from backend.services.youtube_auth import get_youtube_client
from backend.schemas import (
    ChannelCreate,
    ChannelUpdate,
    ChannelStats,
    InstagramTestRequest,
    InstagramTestResponse,
)
from backend.config import settings
from backend.services.sheets import _gc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channels", tags=["channels"])


def get_all_channel_keys(db: Session | None = None) -> list[tuple[str, str, bool]]:
    """Return list of (channel_key, display_name, is_custom) for all active channels from DB."""
    channels = []
    if db:
        try:
            custom = db.query(ChannelConfig).filter(ChannelConfig.is_active == True).all()
            for c in custom:
                channels.append((c.key, c.display_name, True))
        except Exception as exc:
            logger.debug("Could not load channels from DB: %s", exc)
    return channels


@router.get("", response_model=List[ChannelStats])
def get_channels(db: Session = Depends(get_db)):
    results = []
    all_keys = get_all_channel_keys(db)
    for key, name, is_custom in all_keys:
        results.append(_fetch_channel_stats(key, default_name=name, is_custom=is_custom, db=db))
    return results


def _get_redirect_uri(request: Optional[Request] = None) -> str:
    """Dynamically determine OAuth callback URL based on deployment or incoming request."""
    base = settings.backend_public_url.strip().rstrip("/") if settings.backend_public_url else ""
    if not base and request:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", "localhost:8000"))
        base = f"{proto}://{host}".rstrip("/")
    if not base:
        base = "http://localhost:8000"
    return f"{base}/api/channels/oauth/callback"


@router.get("/auth-url")
def get_global_auth_url(request: Request, channel: Optional[str] = None, db: Session = Depends(get_db)):
    """Generate Google OAuth consent URL using shared system Client ID."""
    client_id, _ = settings.get_google_oauth_credentials()
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_CLIENT_ID not configured in .env. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )

    redirect_uri = _get_redirect_uri(request)
    scopes = "https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl"
    
    state = channel or f"new_{uuid.uuid4().hex[:6]}"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return {"auth_url": url, "redirect_uri": redirect_uri}


@router.get("/{channel}/auth-url")
def get_channel_auth_url(channel: str, request: Request, db: Session = Depends(get_db)):
    """Generate Google OAuth consent URL for a specific channel."""
    return get_global_auth_url(request=request, channel=channel, db=db)


public_router = APIRouter(prefix="/api/channels", tags=["channels-oauth"])


@public_router.get("/oauth/callback")
def oauth_callback(code: str, state: str, request: Request, db: Session = Depends(get_db)):
    """
    Handle Google OAuth callback:
    1. Exchange authorization code for refresh_token using shared credentials
    2. Query YouTube API to discover channel title and channel ID automatically
    3. Save / update ChannelConfig in DB with the refresh_token
    """
    client_id, client_secret = settings.get_google_oauth_credentials()
    if not (client_id and client_secret):
        raise HTTPException(status_code=400, detail="Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in .env")

    redirect_uri = _get_redirect_uri(request)
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    with httpx.Client() as client:
        resp = client.post(token_url, data=data)
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Token exchange failed: {resp.text}")
        token_data = resp.json()
        refresh_token = token_data.get("refresh_token")
        access_token = token_data.get("access_token")
        if not refresh_token:
            # If Google didn't return a refresh_token, try using existing from DB if updating
            existing = db.query(ChannelConfig).filter(ChannelConfig.key == state).first()
            if existing and existing.refresh_token:
                refresh_token = existing.refresh_token
            else:
                raise HTTPException(status_code=400, detail="No refresh token returned. Try prompt=consent.")

    # Auto-discover channel details from YouTube API
    channel_title = state
    yt_channel_id = ""
    try:
        with httpx.Client() as client:
            ch_resp = client.get(
                "https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if ch_resp.status_code == 200:
                ch_items = ch_resp.json().get("items", [])
                if ch_items:
                    snippet = ch_items[0].get("snippet", {})
                    channel_title = snippet.get("title") or channel_title
                    yt_channel_id = ch_items[0].get("id", "")
    except Exception as exc:
        logger.warning("Could not auto-fetch YouTube channel details during callback: %s", exc)

    # Determine channel key
    if state and not state.startswith("new_"):
        key = state
    else:
        # Generate slug from channel title or YouTube ID
        raw = channel_title or yt_channel_id or uuid.uuid4().hex[:6]
        key = "".join(c if c.isalnum() else "_" for c in raw.lower()).strip("_")
        if not key:
            key = f"channel_{uuid.uuid4().hex[:6]}"

    # Check if channel already exists in DB
    cfg = db.query(ChannelConfig).filter(ChannelConfig.key == key).first()
    if not cfg and yt_channel_id:
        # Check by display name or existing
        cfg = db.query(ChannelConfig).filter(ChannelConfig.display_name == channel_title).first()

    if cfg:
        cfg.refresh_token = refresh_token
        cfg.display_name = channel_title or cfg.display_name
        cfg.is_active = True
        db.commit()
    else:
        new_ch = ChannelConfig(
            key=key,
            display_name=channel_title,
            client_id="",
            client_secret="",
            refresh_token=refresh_token,
            is_active=True,
        )
        db.add(new_ch)
        db.commit()

    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding:40px;background:#0a0a0f;color:#e2e8f0;'>"
        f"<h2 style='color:#22c55e;'>✅ YouTube Channel '{channel_title}' Connected!</h2>"
        "<p style='color:#94a3b8;'>Your channel is authenticated and ready to use in the automation pipeline.</p>"
        "<p style='color:#64748b;font-size:12px;'>Closing this window and refreshing...</p>"
        "<script>window.opener && window.opener.location.reload(); setTimeout(() => window.close(), 2000);</script>"
        "</body></html>"
    )


@router.post("", response_model=ChannelStats, status_code=201)
def create_channel(body: ChannelCreate, db: Session = Depends(get_db)):
    if not body.display_name.strip():
        raise HTTPException(status_code=400, detail="Display name is required")
    
    raw_key = body.key.strip() if body.key and body.key.strip() else body.display_name.strip()
    key = "".join(c if c.isalnum() else "_" for c in raw_key.lower()).strip("_")
    if not key:
        key = f"channel_{uuid.uuid4().hex[:6]}"
    
    existing = db.query(ChannelConfig).filter(ChannelConfig.key == key).first()
    if existing:
        existing.display_name = body.display_name
        if body.client_id:
            existing.client_id = body.client_id
        if body.client_secret:
            existing.client_secret = body.client_secret
        if body.refresh_token:
            existing.refresh_token = body.refresh_token
        existing.sheet_id = body.sheet_id
        existing.sheet_tab = body.sheet_tab
        existing.seo_tags = body.seo_tags
        existing.is_active = True
        db.commit()
        db.refresh(existing)
    else:
        new_ch = ChannelConfig(
            key=key,
            display_name=body.display_name,
            client_id=body.client_id or "",
            client_secret=body.client_secret or "",
            refresh_token=body.refresh_token or "",
            sheet_id=body.sheet_id,
            sheet_tab=body.sheet_tab,
            seo_tags=body.seo_tags,
            instagram_account_id=body.instagram_account_id,
            instagram_access_token=body.instagram_access_token,
            instagram_enabled=body.instagram_enabled,
            instagram_username=body.instagram_username,
            is_active=True,
        )
        db.add(new_ch)
        db.commit()

    return _fetch_channel_stats(key, default_name=body.display_name, is_custom=True, db=db)


@router.put("/{channel}", response_model=ChannelStats)
def update_channel(channel: str, body: ChannelUpdate, db: Session = Depends(get_db)):
    cfg = db.query(ChannelConfig).filter(ChannelConfig.key == channel).first()
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Channel {channel} not found")

    if body.display_name is not None:
        cfg.display_name = body.display_name
    if body.sheet_id is not None:
        cfg.sheet_id = body.sheet_id
    if body.sheet_tab is not None:
        cfg.sheet_tab = body.sheet_tab
    if body.seo_tags is not None:
        cfg.seo_tags = body.seo_tags
    if body.client_id is not None:
        cfg.client_id = body.client_id
    if body.client_secret is not None:
        cfg.client_secret = body.client_secret
    if body.instagram_account_id is not None:
        cfg.instagram_account_id = body.instagram_account_id
    if body.instagram_access_token is not None:
        cfg.instagram_access_token = body.instagram_access_token
    if body.instagram_enabled is not None:
        cfg.instagram_enabled = body.instagram_enabled
    if body.instagram_username is not None:
        cfg.instagram_username = body.instagram_username

    db.commit()
    db.refresh(cfg)
    return _fetch_channel_stats(channel, default_name=cfg.display_name, is_custom=True, db=db)


@router.post("/instagram/test")
def test_instagram_global(body: InstagramTestRequest):
    """Test Instagram account ID and access token directly."""
    from backend.services.instagram import test_instagram_connection
    res = test_instagram_connection(account_id=body.account_id, access_token=body.access_token)
    return res


@router.post("/{channel}/instagram/test")
def test_instagram_channel(channel: str, body: Optional[InstagramTestRequest] = None, db: Session = Depends(get_db)):
    """Test Instagram credentials for a specific channel and optionally cache the verified username."""
    from backend.services.instagram import test_instagram_connection

    cfg = db.query(ChannelConfig).filter(ChannelConfig.key == channel).first()
    account_id = body.account_id if body and body.account_id else (cfg.instagram_account_id if cfg else "")
    access_token = body.access_token if body and body.access_token else (cfg.instagram_access_token if cfg else "")

    if not account_id or not access_token:
        raise HTTPException(status_code=400, detail="Instagram Account ID and Access Token must be provided.")

    res = test_instagram_connection(account_id=account_id, access_token=access_token)
    if res.get("success") and res.get("username") and cfg:
        cfg.instagram_username = res["username"]
        db.commit()
    return res


@router.delete("/{channel}", status_code=204)
def delete_channel(channel: str, db: Session = Depends(get_db)):
    cfg = db.query(ChannelConfig).filter(ChannelConfig.key == channel).first()
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Channel {channel} not found")
    db.delete(cfg)
    db.commit()


@router.get("/google-sheets")
def list_google_sheets(sheet_id: Optional[str] = None):
    """
    List all spreadsheets accessible to the service account, 
    or list tabs if a specific sheet_id is provided.
    """
    try:
        client = _gc()
        if not sheet_id:
            # List all spreadsheets
            sheets = client.list_spreadsheet_files()
            return {"spreadsheets": [{"id": s["id"], "name": s["name"]} for s in sheets]}
        else:
            # List tabs within a spreadsheet
            sh = client.open_by_key(sheet_id)
            worksheets = sh.worksheets()
            return {"tabs": [{"id": str(ws.id), "name": ws.title} for ws in worksheets]}
    except Exception as exc:
        logger.error(f"Error fetching Google Sheets info: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch Google Sheets: {str(exc)}"
        )


@router.get("/{channel}", response_model=ChannelStats)
def get_channel(channel: str, db: Session = Depends(get_db)):
    all_keys = dict((k, (n, c)) for k, n, c in get_all_channel_keys(db))
    if channel not in all_keys:
        raise HTTPException(status_code=404, detail=f"Unknown channel: {channel}")
    name, is_custom = all_keys[channel]
    return _fetch_channel_stats(channel, default_name=name, is_custom=is_custom, db=db)


def _fetch_channel_stats(channel: str, default_name: str = "", is_custom: bool = True, db: Session | None = None) -> ChannelStats:
    sheet_id = None
    sheet_tab = None
    ig_account_id = None
    ig_enabled = False
    ig_username = None
    ig_ok = False

    if db:
        cfg = db.query(ChannelConfig).filter(ChannelConfig.key == channel).first()
        if cfg:
            sheet_id = cfg.sheet_id
            sheet_tab = cfg.sheet_tab
            default_name = cfg.display_name or default_name
            ig_account_id = cfg.instagram_account_id
            ig_enabled = cfg.instagram_enabled or False
            ig_username = cfg.instagram_username
            ig_ok = bool(cfg.instagram_account_id and cfg.instagram_access_token)

    try:
        yt = get_youtube_client(channel)

        ch_resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
        items = ch_resp.get("items", [])
        if not items:
            raise ValueError("No channel found for authenticated user")

        ch = items[0]
        stats = ch.get("statistics", {})
        snippet = ch.get("snippet", {})

        subscriber_count = int(stats.get("subscriberCount", 0))
        video_count = int(stats.get("videoCount", 0))
        display_name = snippet.get("title", default_name or channel)

        uploads_playlist = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
        recent_uploads: list[dict] = []

        if uploads_playlist:
            pl_resp = (
                yt.playlistItems()
                .list(part="snippet", playlistId=uploads_playlist, maxResults=10)
                .execute()
            )
            for item in pl_resp.get("items", []):
                sn = item.get("snippet", {})
                recent_uploads.append(
                    {
                        "video_id": sn.get("resourceId", {}).get("videoId", ""),
                        "title": sn.get("title", ""),
                        "published_at": sn.get("publishedAt", ""),
                    }
                )

        return ChannelStats(
            channel=channel,
            display_name=display_name,
            subscriber_count=subscriber_count,
            video_count=video_count,
            recent_uploads=recent_uploads,
            auth_ok=True,
            is_custom=is_custom,
            sheet_id=sheet_id,
            sheet_tab=sheet_tab,
            instagram_account_id=ig_account_id,
            instagram_enabled=ig_enabled,
            instagram_username=ig_username,
            instagram_ok=ig_ok,
        )

    except Exception as exc:
        logger.debug("Failed to fetch stats for %s: %s", channel, exc)
        return ChannelStats(
            channel=channel,
            display_name=default_name or channel,
            subscriber_count=0,
            video_count=0,
            recent_uploads=[],
            auth_ok=False,
            is_custom=is_custom,
            sheet_id=sheet_id,
            sheet_tab=sheet_tab,
            instagram_account_id=ig_account_id,
            instagram_enabled=ig_enabled,
            instagram_username=ig_username,
            instagram_ok=ig_ok,
        )


@router.post("/refresh-sheets", status_code=200)
def refresh_sheets_client():
    """Invalidate the cached gspread client so new credentials take effect immediately.
    Normally the cache auto-expires every 10 minutes; call this endpoint right after
    updating the service account JSON to skip the wait.
    """
    from backend.services.sheets import invalidate_gspread_client
    invalidate_gspread_client()
    return {"message": "Google Sheets client cache cleared. Next request will re-authenticate."}
