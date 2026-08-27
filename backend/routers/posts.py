"""Posts router — ingest, list, detail, delete, retry."""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models import Post
from backend.schemas import PostCreate, PostList, PostRead, RetryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/posts", tags=["posts"])

# ---------------------------------------------------------------------------
# Video file validation
# ---------------------------------------------------------------------------

# Allowed MIME types declared by the client
_ALLOWED_MIME_TYPES = {
    "video/mp4", "video/quicktime", "video/x-msvideo", "video/x-matroska",
    "video/webm", "video/mpeg", "video/3gpp", "video/x-flv",
    "video/x-ms-wmv", "video/ogg", "application/octet-stream",  # ffmpeg output
}

# Magic byte signatures  (offset, bytes)
_VIDEO_MAGIC: list[tuple[int, bytes]] = [
    (0,  b"\x00\x00\x00\x18ftyp"),   # MP4 / M4V / HEVC (18 atom)
    (0,  b"\x00\x00\x00\x1cftyp"),   # MP4 / M4V (28 atom)
    (0,  b"\x00\x00\x00 ftyp"),      # MP4 (32 atom, space = 0x20)
    (0,  b"\x00\x00\x00\x08ftyp"),   # MP4 (8 atom)
    (4,  b"ftyp"),                    # generic MP4/MOV (atom at byte 4)
    (0,  b"\x1aE\xdf\xa3"),          # Matroska / WebM EBML header
    (0,  b"RIFF"),                    # AVI
    (0,  b"\x00\x00\x01\xba"),       # MPEG-PS
    (0,  b"\x00\x00\x01\xb3"),       # MPEG video
    (0,  b"FLV\x01"),                # FLV
    (0,  b"OggS"),                   # Ogg / Theora
    (0,  b"\x30\x26\xb2\x75"),       # WMV / ASF
]

_MAGIC_READ_BYTES = 16  # how many bytes to read for signature check


async def _validate_video_file(video: UploadFile) -> None:
    """Raise HTTP 400 if the upload is not a recognisable video file."""
    # 1. MIME type check (not trusted alone — client can lie)
    ct = (video.content_type or "").split(";")[0].strip().lower()
    if ct and ct not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ct}'. Please upload a video file (MP4, MOV, MKV, AVI, WebM).",
        )

    # 2. Magic bytes check — read first 16 bytes
    header = await video.read(_MAGIC_READ_BYTES)
    await video.seek(0)  # rewind so the file can be saved normally

    matched = any(
        header[offset: offset + len(sig)] == sig
        for offset, sig in _VIDEO_MAGIC
    )
    if not matched:
        raise HTTPException(
            status_code=400,
            detail="File signature does not match a supported video format. Ensure you are uploading a real video file.",
        )

# Status rollback map for retry — go back to last good stage
_RETRY_STATUS_MAP: dict[str, str] = {
    "failed": "queued",       # default: restart from scratch
    "cleaning": "queued",     # cleaning got stuck
    "cleaned": "cleaned",     # skip re-cleaning, re-schedule
    "scheduled": "cleaned",   # re-pick slot
    "uploaded": "uploaded",   # retry comment only
}


@router.get("/sheet-rows")
def get_sheet_rows(channel: Optional[str] = None, db: Session = Depends(get_db)):
    """Fetch all rows from Google Sheets for the channel to allow row selection."""
    try:
        if not channel:
            from backend.models import ChannelConfig
            first_ch = db.query(ChannelConfig).filter(ChannelConfig.is_active == True).first()
            channel = first_ch.key if first_ch else "default"

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
        logger.warning("Could not fetch sheet rows for channel %s: %s", channel, exc)
        return {"found": False, "rows": [], "message": str(exc)}


@router.get("/sheet-row")
def get_sheet_row(channel: Optional[str] = None, row_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Fetch metadata from Google Sheets for the channel by row_id or next unscheduled."""
    try:
        if not channel:
            from backend.models import ChannelConfig
            first_ch = db.query(ChannelConfig).filter(ChannelConfig.is_active == True).first()
            channel = first_ch.key if first_ch else "default"

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
        logger.warning("Could not fetch sheet row: %s", exc)
        return {"found": False, "message": str(exc)}


@router.post("", response_model=PostRead, status_code=201)
async def create_post(
    background_tasks: BackgroundTasks,
    channel: str = Form(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(""),
    tags: Optional[str] = Form(""),
    sheet_row_id: Optional[str] = Form(None),
    video: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Ingest a new video. If sheet_row_id is provided, fetches and binds that specific row."""
    # Validate file type before doing anything else
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

                # Check if the selected row was ALREADY scheduled / uploaded in Google Sheet
                is_already_scheduled = bool(
                    str(sheet_data.get("scheduled", "")).strip()
                    or str(sheet_data.get("upload id", "") or sheet_data.get("upload_id", "")).strip()
                )

                # Prioritize user-provided custom inputs, fallback to sheet values
                use_title = title.strip() if title and title.strip() else sheet_title
                use_desc = description.strip() if description and description.strip() else sheet_desc
                use_tags = tags.strip() if tags and tags.strip() else sheet_tags

                if is_already_scheduled:
                    # Create a brand new row with fresh incremental ID so previous scheduled row is never overwritten
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
                    logger.info("Selected row %s was already scheduled; created new sheet row ID %s", sheet_data.get("id"), clean_row_id)
                else:
                    title = use_title
                    description = use_desc
                    tags = use_tags
                    clean_row_id = str(sheet_data.get("id", clean_row_id)).strip()
        except Exception as exc:
            logger.warning("Failed to process selected sheet row %s: %s", clean_row_id, exc)

    # If no sheet_row_id was provided and title is empty, auto-fetch first unscheduled row
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
            logger.warning("Auto-fetch next unscheduled row failed: %s", exc)

    # Fallback title if sheet is empty or unavailable
    if not title or not title.strip():
        raw_name = Path(video.filename or "video.mp4").stem
        title = raw_name.replace("-", " ").replace("_", " ").title()

    # Persist video to upload dir
    upload_dir = settings.upload_path()
    suffix = Path(video.filename or "video.mp4").suffix or ".mp4"
    filename = f"{uuid.uuid4().hex}{suffix}"
    dest = (upload_dir / filename).resolve()

    try:
        with dest.open("wb") as f:
            shutil.copyfileobj(video.file, f)
    except Exception as exc:
        logger.exception("Failed to save uploaded video")
        raise HTTPException(status_code=500, detail=f"File save failed: {exc}")
    finally:
        await video.close()

    post = Post(
        channel=channel,
        title=title,
        description=description or "",
        tags=tags or "",
        sheet_row_id=clean_row_id,
        video_path=str(dest),
        status="queued",
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    logger.info(
        "Post %s created (channel=%s, title=%s, sheet_row_id=%s, file=%s)",
        post.id, channel, title, clean_row_id, dest,
    )
    name_map = _get_channel_name_map(db)
    return _to_post_read(post, name_map)


def _get_channel_name_map(db: Session) -> dict[str, str]:
    mapping = {
        "channel_a": "Channel A",
        "channel_b": "Channel B",
        "the_indian_kitchen": "The Indian Kitchen",
    }
    try:
        from backend.models import ChannelConfig
        for cfg in db.query(ChannelConfig).all():
            mapping[cfg.key] = cfg.display_name
    except Exception:
        pass
    return mapping


def _to_post_read(post: Post, name_map: dict[str, str]) -> PostRead:
    read = PostRead.model_validate(post)
    read.channel_display_name = name_map.get(post.channel, post.channel.replace("_", " ").title())
    return read


@router.get("", response_model=PostList)
def list_posts(
    channel: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(Post)
    if channel and channel != "all":
        query = query.filter(Post.channel == channel)
    if status and status != "all":
        query = query.filter(Post.status == status)
    total = query.count()
    items = query.order_by(Post.created_at.desc()).offset(skip).limit(limit).all()
    name_map = _get_channel_name_map(db)
    return PostList(total=total, items=[_to_post_read(p, name_map) for p in items])


@router.get("/{post_id}", response_model=PostRead)
def get_post(post_id: int, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    name_map = _get_channel_name_map(db)
    return _to_post_read(post, name_map)


@router.delete("/failed/clear", status_code=200)
def clear_failed_posts(db: Session = Depends(get_db)):
    """Bulk delete all failed posts and clean up any lingering local files."""
    failed_posts = db.query(Post).filter(Post.status == "failed").all()
    count = len(failed_posts)
    for p in failed_posts:
        for path_attr in ("video_path", "clean_video_path"):
            path_val = getattr(p, path_attr, None)
            if path_val:
                try:
                    Path(path_val).unlink(missing_ok=True)
                except Exception:
                    pass
        db.delete(p)
    db.commit()
    logger.info("Cleared %s failed posts from database", count)
    return {"message": f"Cleared {count} failed posts", "count": count}


@router.delete("/{post_id}", status_code=204)
def delete_post(post_id: int, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # 1. Immediately kill remote process & delete files on AWS EC2 worker
    try:
        from backend.services.watermark import cancel_cleaning_job
        cancel_cleaning_job(post_id)
    except Exception as exc:
        logger.warning("Error cancelling worker cleaning job for post %s: %s", post_id, exc)

    # 2. Clean up local files on disk
    for path_attr in ("video_path", "clean_video_path"):
        p = getattr(post, path_attr, None)
        if p:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass

    # 3. Delete database record
    db.delete(post)
    db.commit()
    logger.info("Post %s deleted: worker process killed and files cleared", post_id)


@router.post("/{post_id}/retry", response_model=RetryResponse)
def retry_post(post_id: int, db: Session = Depends(get_db)):
    """Re-queue a failed/stuck post from its last known good stage."""
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    new_status = _RETRY_STATUS_MAP.get(post.status)
    if not new_status:
        raise HTTPException(
            status_code=400,
            detail=f"Post with status '{post.status}' cannot be retried",
        )

    old_status = post.status
    post.status = new_status
    post.error_message = None
    db.commit()
    logger.info("Post %s retried: %s -> %s", post.id, old_status, new_status)
    return RetryResponse(
        post_id=post.id,
        new_status=new_status,
        message=f"Post reset from '{old_status}' to '{new_status}'",
    )


@router.get("/{post_id}/video")
@router.get("/{post_id}/video/clean")
def get_post_video(post_id: int, db: Session = Depends(get_db)):
    """Serve video file for playback, download, or Instagram Graph API crawler fetching."""
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    from backend.services.watermark import resolve_video_path
    video_p = resolve_video_path(post.clean_video_path, is_clean=True)
    if not video_p or not video_p.exists():
        video_p = resolve_video_path(post.video_path, is_clean=False)

    if not video_p or not video_p.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    return FileResponse(
        path=str(video_p),
        media_type="video/mp4",
        filename=f"video-{post.id}.mp4",
    )


@router.post("/{post_id}/instagram/publish")
def publish_instagram_post(post_id: int, db: Session = Depends(get_db)):
    """Trigger or retry Instagram Reels publishing for a post."""
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    from backend.services.instagram import publish_reel_for_post
    res = publish_reel_for_post(post, db)
    if not res.get("success"):
        raise HTTPException(
            status_code=400,
            detail=res.get("error") or res.get("reason") or "Failed to publish Instagram Reel.",
        )
    return res

