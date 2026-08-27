"""Extension ingest router — receives video URL from Chrome extension, downloads, queues."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import SessionLocal
from backend.models import Post

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extension", tags=["extension"])

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class ExtensionIngestRequest(BaseModel):
    video_url: str          # signed URL from Google Flow
    title: str
    channel: str
    description: Optional[str] = ""
    tags: Optional[str] = ""
    scheduled_at: Optional[str] = None   # ISO-8601 string or None


class ExtensionIngestResponse(BaseModel):
    post_id: int
    status: str
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DOWNLOAD_TIMEOUT = 120.0   # seconds — Flow videos are short but GCS can be slow
_MAX_VIDEO_BYTES  = 500 * 1024 * 1024   # 500 MB safety cap


async def _download_video(url: str, dest: Path) -> None:
    """Stream-download video from a signed URL to dest path."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=_DOWNLOAD_TIMEOUT) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to download video from Flow (HTTP {response.status_code})"
                )
            content_length = int(response.headers.get("content-length", 0))
            if content_length > _MAX_VIDEO_BYTES:
                raise HTTPException(status_code=413, detail="Video exceeds 500 MB limit")

            bytes_written = 0
            with open(dest, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                    bytes_written += len(chunk)
                    if bytes_written > _MAX_VIDEO_BYTES:
                        dest.unlink(missing_ok=True)
                        raise HTTPException(status_code=413, detail="Video exceeds 500 MB limit")
                    f.write(chunk)

    if bytes_written == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail="Downloaded file is empty")

    logger.info("Extension ingest: downloaded %.1f MB to %s", bytes_written / 1e6, dest)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/ingest", response_model=ExtensionIngestResponse)
async def ingest_from_extension(body: ExtensionIngestRequest):
    """
    Called by the Chrome extension on Google Flow.
    Downloads the video from the signed URL and queues it for pipeline processing.
    No API-key auth — this route is public (local/self-hosted use only).
    """
    # Basic validation
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required")
    channel = (body.channel or "").strip().lower()
    if not channel:
        raise HTTPException(status_code=422, detail="channel is required")
    if not body.video_url:
        raise HTTPException(status_code=422, detail="video_url is required")

    # Parse optional scheduled_at
    scheduled_at: Optional[datetime] = None
    if body.scheduled_at:
        try:
            scheduled_at = datetime.fromisoformat(body.scheduled_at)
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid scheduled_at format: {body.scheduled_at!r}")

    # Build destination path
    upload_dir = settings.upload_path()
    filename = f"flow_{uuid.uuid4().hex}.mp4"
    dest = upload_dir / filename

    # Download
    logger.info("Extension ingest: downloading video for channel=%s title=%r", channel, title)
    try:
        await _download_video(body.video_url, dest)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Extension ingest: unexpected download error")
        raise HTTPException(status_code=502, detail=f"Download failed: {exc}") from exc

    # Create Post record
    with SessionLocal() as db:
        post = Post(
            channel=channel,
            title=title,
            description=body.description or "",
            tags=body.tags or "",
            video_path=str(dest),
            status="queued",
            scheduled_at=scheduled_at,
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        post_id = post.id

    logger.info("Extension ingest: created Post id=%d (status=queued) for channel=%s", post_id, channel)

    return ExtensionIngestResponse(
        post_id=post_id,
        status="queued",
        message=f"Video queued as post #{post_id}. Pipeline will process within 30 seconds.",
    )
