"""Extension ingest router — provides live channels, sheet rows, and video ingestion for the Chrome extension."""
from __future__ import annotations

import ipaddress
import logging
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import SessionLocal, get_db
from backend.models import ChannelConfig, Post
from backend.routers.posts import _validate_video_file, is_valid_video_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extension", tags=["extension"])

# ---------------------------------------------------------------------------
# SSRF — private / reserved network ranges to block
# ---------------------------------------------------------------------------

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),   # Shared address space (RFC 6598)
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),   # Benchmark testing (RFC 2544)
    ipaddress.ip_network("198.51.100.0/24"), # TEST-NET-2 (RFC 5737)
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3 (RFC 5737)
    ipaddress.ip_network("240.0.0.0/4"),     # Reserved
    # IPv6
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),        # Unique local
    ipaddress.ip_network("fe80::/10"),       # Link-local
    ipaddress.ip_network("::ffff:0:0/96"),   # IPv4-mapped
]

_CLOUD_METADATA_HOSTS = {
    "169.254.169.254",  # AWS / GCP / Azure IMDS
    "metadata.google.internal",
    "metadata.internal",
}


def _is_safe_host(hostname: str) -> None:
    """
    Resolve hostname and reject if any resolved IP is private/loopback/cloud-metadata.
    Raises HTTPException(400) on SSRF risk.
    """
    hostname_lower = hostname.lower()
    # Reject cloud metadata hostnames by name
    if hostname_lower in _CLOUD_METADATA_HOSTS or hostname_lower.endswith(".internal"):
        raise HTTPException(status_code=400, detail="SSRF: target host not permitted.")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"Could not resolve host: {hostname}") from exc

    for info in infos:
        addr_str = info[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        for net in _BLOCKED_NETWORKS:
            if addr in net:
                raise HTTPException(
                    status_code=400,
                    detail="SSRF: URL resolves to a private or reserved address and cannot be fetched.",
                )


def _validate_ingest_url(url: str) -> None:
    """Full SSRF validation: scheme, host resolution, private-IP rejection."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail="Invalid URL scheme. Only http and https are permitted.",
        )
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="Invalid URL: missing host.")
    _is_safe_host(host)



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
    title: Optional[str] = None
    channel: str
    description: Optional[str] = ""
    tags: Optional[str] = ""
    sheet_row_id: Optional[str] = None
    scheduled_at: Optional[str] = None


class ExtensionIngestResponse(BaseModel):
    post_id: int
    id: Optional[int] = None
    status: str
    message: str
    title: Optional[str] = None


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
def get_extension_sheet_rows(channel: Optional[str] = "channel_a", unscheduled_only: bool = True, db: Session = Depends(get_db)):
    """Fetch live rows from Google Sheets for the selected channel.
    
    By default (unscheduled_only=True), returns only unscheduled rows.
    Pass unscheduled_only=false to get all rows.
    """
    try:
        from backend.services.sheets import get_all_rows
        all_rows = get_all_rows(channel)
        result = []
        for r in all_rows:
            sched = str(r.get("scheduled", "")).strip()
            upload_id = str(r.get("upload id", "") or r.get("upload_id", "")).strip()
            is_scheduled = bool(sched or upload_id)
            if unscheduled_only and is_scheduled:
                continue
            result.append({
                "id": str(r.get("id", "")).strip(),
                "title": r.get("title", ""),
                "description": r.get("description", ""),
                "tags": r.get("tags", ""),
                "scheduled": sched,
                "is_scheduled": is_scheduled,
                "upload_id": upload_id,
            })
        return {"found": True, "rows": result, "unscheduled_only": unscheduled_only}
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
    background_tasks: BackgroundTasks,
    channel: str = Form(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(""),
    tags: Optional[str] = Form(""),
    sheet_row_id: Optional[str] = Form(None),
    video: UploadFile = File(...),
    _auth: None = Depends(_verify_extension_auth),
):
    """
    Accepts video file directly from the extension as multipart/form-data.
    Full parity with web app /api/posts:
    - Auto-binds Google Sheet row or creates new row if already scheduled
    - Extracts title/description/tags from sheet if left blank
    - Validates real video headers
    - Queues immediately for processing
    """
    channel = (channel or "").strip().lower()
    if not channel:
        raise HTTPException(status_code=422, detail="channel is required")

    # Validate video format and magic bytes
    await _validate_video_file(video)

    clean_row_id = sheet_row_id.strip() if sheet_row_id and sheet_row_id.strip() else None

    # If specific sheet_row_id was selected, fetch row details from Google Sheets
    if clean_row_id:
        try:
            from backend.services.sheets import get_row_by_id, append_new_row
            sheet_data = get_row_by_id(channel, clean_row_id)
            if sheet_data:
                sheet_title = str(sheet_data.get("title", "")).strip()
                sheet_desc = str(sheet_data.get("description", "")).strip()
                sheet_tags = str(sheet_data.get("tags", "")).strip()

                is_already_scheduled = bool(
                    str(sheet_data.get("scheduled", "")).strip()
                    or str(sheet_data.get("upload id", "") or sheet_data.get("upload_id", "")).strip()
                )

                use_title = title.strip() if title and title.strip() else sheet_title
                use_desc = description.strip() if description and description.strip() else sheet_desc
                use_tags = tags.strip() if tags and tags.strip() else sheet_tags

                if is_already_scheduled:
                    new_row = append_new_row(
                        channel=channel,
                        title=use_title or f"Video {clean_row_id} (New)",
                        description=use_desc,
                        tags=use_tags,
                    )
                    clean_row_id = str(new_row.get("id"))
                    title = use_title
                    description = use_desc
                    tags = use_tags
                    logger.info("Extension upload: row %s already scheduled, appended new row %s", sheet_data.get("id"), clean_row_id)
                else:
                    title = use_title
                    description = use_desc
                    tags = use_tags
                    clean_row_id = str(sheet_data.get("id", clean_row_id)).strip()
        except Exception as exc:
            logger.warning("Extension upload: failed to process sheet row %s: %s", clean_row_id, exc)

    elif not title or not title.strip():
        try:
            from backend.services.sheets import get_first_unscheduled_row
            sheet_data = get_first_unscheduled_row(channel)
            if sheet_data:
                title = str(sheet_data.get("title", "")).strip()
                if not description or not description.strip():
                    description = str(sheet_data.get("description", "")).strip()
                if not tags or not tags.strip():
                    tags = str(sheet_data.get("tags", "")).strip()
                clean_row_id = str(sheet_data.get("id", "")).strip() or None
        except Exception as exc:
            logger.warning("Extension upload: auto-fetch unscheduled row failed: %s", exc)

    if not title or not title.strip():
        raw_name = Path(video.filename or "video.mp4").stem
        title = raw_name.replace("-", " ").replace("_", " ").title() or "Google Flow AI Video"

    upload_dir = settings.upload_path()
    filename = f"flow_{uuid.uuid4().hex}.mp4"
    dest = upload_dir / filename

    try:
        with open(dest, "wb") as f:
            while chunk := await video.read(1024 * 256):
                f.write(chunk)
    finally:
        await video.close()

    with SessionLocal() as db:
        post = Post(
            channel=channel,
            title=title,
            description=description or "",
            tags=tags or "",
            video_path=str(dest),
            status="queued",
            scheduled_at=None,
            sheet_row_id=clean_row_id,
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        post_id = post.id

    # Trigger Google Drive upload immediately
    try:
        from backend.services.storage import upload_post_to_drive
        background_tasks.add_task(upload_post_to_drive, post_id)
    except Exception as exc:
        logger.warning("Could not schedule Drive upload: %s", exc)

    # Trigger serial pipeline queue immediately
    try:
        from backend.jobs.job_queue import run_serial_queue
        background_tasks.add_task(run_serial_queue)
    except Exception as exc:
        logger.warning("Could not trigger background task queue: %s", exc)

    logger.info("Extension upload: created Post id=%d (queued) for channel=%s", post_id, channel)

    return ExtensionIngestResponse(
        post_id=post_id,
        id=post_id,
        status="queued",
        message=f"Video queued as post #{post_id}. Pipeline processing will start immediately.",
        title=title,
    )


@router.post("/ingest", response_model=ExtensionIngestResponse)
async def ingest_from_extension(
    body: ExtensionIngestRequest,
    background_tasks: BackgroundTasks,
    _auth: None = Depends(_verify_extension_auth),
):
    """Fallback URL-based ingest with full sheet sync parity."""
    channel = (body.channel or "").strip().lower()
    if not channel:
        raise HTTPException(status_code=422, detail="channel is required")

    url = (body.video_url or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="video_url is required")
    if url.startswith("blob:"):
        raise HTTPException(
            status_code=400,
            detail="Blob URLs cannot be downloaded directly by the server. Please upload the video file directly as multipart/form-data via /api/extension/upload.",
        )
    # Full SSRF validation: scheme + DNS resolution + private-IP check
    _validate_ingest_url(url)

    title = (body.title or "").strip()
    description = (body.description or "").strip()
    tags = (body.tags or "").strip()
    clean_row_id = body.sheet_row_id.strip() if body.sheet_row_id and body.sheet_row_id.strip() else None

    if clean_row_id:
        try:
            from backend.services.sheets import get_row_by_id, append_new_row
            sheet_data = get_row_by_id(channel, clean_row_id)
            if sheet_data:
                sheet_title = str(sheet_data.get("title", "")).strip()
                sheet_desc = str(sheet_data.get("description", "")).strip()
                sheet_tags = str(sheet_data.get("tags", "")).strip()

                is_already_scheduled = bool(
                    str(sheet_data.get("scheduled", "")).strip()
                    or str(sheet_data.get("upload id", "") or sheet_data.get("upload_id", "")).strip()
                )

                use_title = title if title else sheet_title
                use_desc = description if description else sheet_desc
                use_tags = tags if tags else sheet_tags

                if is_already_scheduled:
                    new_row = append_new_row(
                        channel=channel,
                        title=use_title or f"Video {clean_row_id} (New)",
                        description=use_desc,
                        tags=use_tags,
                    )
                    clean_row_id = str(new_row.get("id"))
                    title = use_title
                    description = use_desc
                    tags = use_tags
                else:
                    title = use_title
                    description = use_desc
                    tags = use_tags
                    clean_row_id = str(sheet_data.get("id", clean_row_id)).strip()
        except Exception as exc:
            logger.warning("Extension ingest: failed to process sheet row %s: %s", clean_row_id, exc)
    elif not title:
        try:
            from backend.services.sheets import get_first_unscheduled_row
            sheet_data = get_first_unscheduled_row(channel)
            if sheet_data:
                title = str(sheet_data.get("title", "")).strip()
                if not description:
                    description = str(sheet_data.get("description", "")).strip()
                if not tags:
                    tags = str(sheet_data.get("tags", "")).strip()
                clean_row_id = str(sheet_data.get("id", "")).strip() or None
        except Exception as exc:
            logger.warning("Extension ingest: auto-fetch unscheduled row failed: %s", exc)

    if not title:
        title = "Google Flow AI Video"

    upload_dir = settings.upload_path()
    filename = f"flow_{uuid.uuid4().hex}.mp4"
    dest = upload_dir / filename

    max_download_bytes = settings.max_download_size_mb * 1024 * 1024

    # SSRF-safe redirect handler: validate each redirect destination
    async def _ssrf_safe_download(start_url: str) -> None:
        """Download with redirect validation and size cap."""
        _validate_ingest_url(start_url)
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=None, pool=None)
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
        ) as client:
            current_url = start_url
            redirect_count = 0
            while True:
                async with client.stream("GET", current_url) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        redirect_count += 1
                        if redirect_count > 3:
                            raise HTTPException(status_code=400, detail="Too many redirects.")
                        location = response.headers.get("location", "")
                        if not location:
                            raise HTTPException(status_code=400, detail="Redirect with no Location header.")
                        # Validate redirect target before following
                        _validate_ingest_url(location)
                        current_url = location
                        continue

                    if response.status_code != 200:
                        raise HTTPException(status_code=502, detail=f"Download failed with HTTP {response.status_code}")

                    final_url = str(response.url)
                    content_type = response.headers.get("content-type", "").lower()
                    if "accounts.google.com" in final_url or "login" in final_url:
                        raise HTTPException(
                            status_code=400,
                            detail="This video URL requires Google authentication and cannot be downloaded directly.",
                        )
                    if "text/html" in content_type or "application/json" in content_type:
                        raise HTTPException(
                            status_code=400,
                            detail=f"URL returned {content_type} instead of a video.",
                        )

                    downloaded = 0
                    with open(dest, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                            downloaded += len(chunk)
                            if downloaded > max_download_bytes:
                                dest.unlink(missing_ok=True)
                                raise HTTPException(
                                    status_code=413,
                                    detail=f"Download exceeds maximum allowed size ({settings.max_download_size_mb} MB).",
                                )
                            f.write(chunk)
                    break

    await _ssrf_safe_download(url)

    # Validate downloaded file magic bytes
    try:
        with open(dest, "rb") as f:
            header = f.read(64)
        if not is_valid_video_signature(header):
            dest.unlink(missing_ok=True)
            logger.warning("Downloaded content failed video signature check. First 32 bytes: %r", header[:32])
            raise HTTPException(
                status_code=400,
                detail="Downloaded URL content does not match a valid video format signature (MP4/WebM/MOV). The URL may be an expired link or non-video asset. Please play the video or choose the video file directly.",
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
            description=description or "",
            tags=tags or "",
            video_path=str(dest),
            status="queued",
            scheduled_at=None,
            sheet_row_id=clean_row_id,
        )
        db.add(post)
        db.commit()
        db.refresh(post)
        post_id = post.id

    # Trigger Google Drive upload immediately
    try:
        from backend.services.storage import upload_post_to_drive
        background_tasks.add_task(upload_post_to_drive, post_id)
    except Exception as exc:
        logger.warning("Could not schedule Drive upload: %s", exc)

    try:
        from backend.jobs.job_queue import run_serial_queue
        background_tasks.add_task(run_serial_queue)
    except Exception as exc:
        logger.warning("Could not trigger background task queue: %s", exc)

    return ExtensionIngestResponse(
        post_id=post_id,
        id=post_id,
        status="queued",
        message=f"Video queued as post #{post_id}.",
        title=title,
    )
