"""Extension ingest router — provides live channels, sheet rows, and video ingestion for the Chrome extension."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import SessionLocal, get_db
from backend.models import ChannelConfig, Post
from backend.routers.posts import _validate_video_file, _VIDEO_MAGIC, _MAGIC_READ_BYTES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extension", tags=["extension"])


def _verify_extension_auth(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None),
) -> None:
    """If API_KEY is set in environment, accept matching key from Bearer token, header, or query param."""
    if not settings.api_key or not settings.api_key.strip():
        return
    bearer = ""
    if authorization and authorization.startswith("Bearer "):
        bearer = authorization[7:].strip()
    provided = x_api_key or api_key or bearer
    if not provided or provided.strip() != settings.api_key.strip():
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key for extension ingest.",
        )

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ExtensionIngestRequest(BaseModel):
    video_url: str
    title: str
    channel: str
    description: Optional[str] = ""
    tags: Optional[str] = ""
    sheet_row_id: Optional[str] = None
    scheduled_at: Optional[str] = None


class ExtensionIngestResponse(BaseModel):
    post_id: int
    status: str
    message: str


# ---------------------------------------------------------------------------
# Live Channels & Google Sheets Query Endpoints (Public for extension)
# ---------------------------------------------------------------------------

@router.get("/channels")
def get_extension_channels(db: Session = Depends(get_db)):
    """Return real connected channels list for the extension."""
    channels = []
    try:
        custom = db.query(ChannelConfig).filter(ChannelConfig.is_active == True).all()
        for c in custom:
            channels.append({
                "id": c.key,
                "name": c.display_name or c.key,
                "sheet_id": c.sheet_id,
                "sheet_tab": c.sheet_tab,
            })
    except Exception as exc:
        logger.warning("Could not load extension channels from DB: %s", exc)

    if not channels:
        # Fallback to configured default channels
        channels = [
            {"id": "channel_a", "name": "Channel A (Cooking ASMR)"},
            {"id": "channel_b", "name": "Channel B (Fruit Growth)"},
        ]
    return channels


@router.get("/sheet-rows")
def get_extension_sheet_rows(channel: Optional[str] = "channel_a", db: Session = Depends(get_db)):
    """Fetch live rows from Google Sheets for the selected channel."""
    try:
        from backend.services.sheets import get_all_rows
        all_rows = get_all_rows(channel)
        result = []
        for r in all_rows:
            sched = str(r.get("scheduled", "")).strip()
            result.append({
                "id": str(r.get("id", "")).strip(),
                "title": r.get("title", ""),
                "description": r.get("description", ""),
                "tags": r.get("tags", ""),
                "scheduled": sched,
                "is_scheduled": bool(sched),
                "upload_id": str(r.get("upload id", "") or r.get("upload_id", "")).strip(),
            })
        return {"found": True, "rows": result}
    except Exception as exc:
        logger.warning("Extension could not fetch sheet rows for channel %s: %s", channel, exc)
        return {"found": False, "rows": [], "message": str(exc)}


@router.get("/sheet-row")
def get_extension_sheet_row(channel: Optional[str] = "channel_a", row_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Fetch live metadata for a specific sheet row or next unscheduled."""
    try:
        from backend.services.sheets import get_first_unscheduled_row, get_row_by_id
        if row_id and str(row_id).strip():
            row = get_row_by_id(channel, str(row_id).strip())
        else:
            row = get_first_unscheduled_row(channel)
        if not row:
            return {"found": False, "message": "No matching row found in Google Sheet"}
        return {
            "found": True,
            "id": row.get("id"),
            "title": row.get("title", ""),
            "description": row.get("description", ""),
            "tags": row.get("tags", ""),
            "scheduled": row.get("scheduled", ""),
        }
    except Exception as exc:
        logger.warning("Extension could not fetch sheet row for channel %s: %s", channel, exc)
        return {"found": False, "message": str(exc)}


# ---------------------------------------------------------------------------
# Video Ingest Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=ExtensionIngestResponse)
async def upload_from_extension(
    channel: str = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(""),
    tags: Optional[str] = Form(""),
    sheet_row_id: Optional[str] = Form(None),
    video: UploadFile = File(...),
    _auth: None = Depends(_verify_extension_auth),
):
    """
    Accepts video file directly from the extension as multipart/form-data.
    Queues immediately with NO schedule constraints after validating real video content.
    """
    title = (title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required")
    channel = (channel or "").strip().lower()
    if not channel:
        raise HTTPException(status_code=422, detail="channel is required")

    # Validate video format and magic bytes
    await _validate_video_file(video)

    upload_dir = settings.upload_path()
    filename = f"flow_{uuid.uuid4().hex}.mp4"
    dest = upload_dir / filename

    with open(dest, "wb") as f:
        while chunk := await video.read(1024 * 256):
            f.write(chunk)

    with SessionLocal() as db:
        post = Post(
            channel=channel,
            title=title,
            description=description or "",
            tags=tags or "",
            video_path=str(dest),
            status="queued",
            scheduled_at=None,
            sheet_row_id=sheet_row_id or None,
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        post_id = post.id

    logger.info("Extension upload: created Post id=%d (queued) for channel=%s", post_id, channel)

    return ExtensionIngestResponse(
        post_id=post_id,
        status="queued",
        message=f"Video queued as post #{post_id}. Pipeline processing will start in 30 seconds.",
    )


@router.post("/ingest", response_model=ExtensionIngestResponse)
async def ingest_from_extension(
    body: ExtensionIngestRequest,
    _auth: None = Depends(_verify_extension_auth),
):
    """Fallback URL-based ingest."""
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required")
    channel = (body.channel or "").strip().lower()
    if not channel:
        raise HTTPException(status_code=422, detail="channel is required")

    upload_dir = settings.upload_path()
    filename = f"flow_{uuid.uuid4().hex}.mp4"
    dest = upload_dir / filename

    async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
        async with client.stream("GET", body.video_url) as response:
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Download failed with HTTP {response.status_code}")
            with open(dest, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                    f.write(chunk)

    # Validate downloaded file magic bytes
    try:
        with open(dest, "rb") as f:
            header = f.read(_MAGIC_READ_BYTES)
        matched = any(
            header[offset: offset + len(sig)] == sig
            for offset, sig in _VIDEO_MAGIC
        )
        if not matched:
            dest.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="Downloaded URL content does not match a valid video format signature.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to inspect downloaded video: {exc}")

    with SessionLocal() as db:
        post = Post(
            channel=channel,
            title=title,
            description=body.description or "",
            tags=body.tags or "",
            video_path=str(dest),
            status="queued",
            scheduled_at=None,
            sheet_row_id=body.sheet_row_id or None,
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        post_id = post.id

    return ExtensionIngestResponse(
        post_id=post_id,
        status="queued",
        message=f"Video queued as post #{post_id}.",
    )
