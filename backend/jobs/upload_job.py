"""
APScheduler job — schedule + upload.

Ported from n8n workflow:
  1. For each channel, find cleaned posts
  2. Call Gemini AI agent (reads Google Sheet + live YT data) → get enriched content + scheduled date
  3. Upload to YouTube (private, publishAt = Gemini-chosen slot)
  4. Write back to Google Sheet: scheduled, upload_id, enriched title
  5. Save enriched content to Post DB row for comment job

Channel isolation: each channel in its own try/except.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from googleapiclient.http import MediaFileUpload

from backend.config import settings
from backend.database import SessionLocal
from backend.models import Post
from backend.services.youtube_auth import (
    get_youtube_client,
    is_quota_error,
    quota_error_message,
)

logger = logging.getLogger(__name__)

def _get_active_channels(db) -> list[str]:
    """Retrieve all active channels from database."""
    try:
        from backend.models import ChannelConfig
        channels = [c.key for c in db.query(ChannelConfig).filter(ChannelConfig.is_active == True).all()]
        if channels:
            return channels
    except Exception:
        pass
    distinct = [r[0] for r in db.query(Post.channel).distinct().all() if r[0]]
    return distinct or ["default"]


def _set_status(db, post: Post, status: str, error: str | None = None) -> None:
    post.status = status
    post.error_message = error
    post.updated_at = datetime.now(timezone.utc)
    db.commit()


# --------------------------------------------------------------------------- #
# Gemini enrichment (reads sheet, returns AI-chosen slot + content)            #
# --------------------------------------------------------------------------- #

def _gemini_enrich_and_schedule(channel: str, post: Post, db) -> Optional[dict]:
    """
    Call Gemini AI agent to get enriched content + scheduled slot.
    Returns Gemini dict {id, title, description, tags, firstComment, date} or None.
    """
    if not settings.gemini_api_key:
        # Fallback: rule-based enrichment + pick_next_slot
        logger.warning("GEMINI_API_KEY not set — using rule-based enrichment for post %s", post.id)
        from backend.services._enrichment_rules import enrich_post as rule_enrich
        from backend.services.scheduler_logic import pick_next_slot
        sub_count = _get_subscriber_count(channel)
        enriched = rule_enrich(channel, post.title, post.description, post.tags, sub_count)
        slot = pick_next_slot(channel, db)
        return {
            "id": post.sheet_row_id,  # preserve bound sheet row id
            "title": enriched["enriched_title"],
            "description": enriched["enriched_description"],
            "tags": [t.strip() for t in (enriched["enriched_tags"] or "").split(";") if t.strip()],
            "firstComment": enriched["first_comment_text"],
            "date": slot.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
        }

    try:
        from backend.services.enrichment import enrich_post_gemini
        return enrich_post_gemini(
            channel=channel,
            target_row_id=post.sheet_row_id,
            target_post=post,
        )
    except Exception as exc:
        logger.error("Gemini enrichment failed for channel %s: %s", channel, exc)
        _set_status(db, post, "failed", f"Gemini enrichment error: {exc}")
        return None


def _get_subscriber_count(channel: str) -> int:
    try:
        yt = get_youtube_client(channel)
        resp = yt.channels().list(part="statistics", mine=True).execute()
        items = resp.get("items", [])
        if items:
            return int(items[0].get("statistics", {}).get("subscriberCount", 0))
    except Exception:
        pass
    return 0


# --------------------------------------------------------------------------- #
# Schedule + upload a single post                                               #
# --------------------------------------------------------------------------- #

def _schedule_single_post(post: Post, db) -> bool:
    """Enrich and schedule a single cleaned post. Returns True on success."""
    result = _gemini_enrich_and_schedule(post.channel, post, db)
    if not result:
        return False

    # Authoritative deterministic slot calculation
    from backend.services.scheduler_logic import pick_next_slot
    try:
        scheduled_at = pick_next_slot(post.channel, db)
    except Exception as exc:
        logger.error("Could not pick next slot for post %s (channel %s): %s", post.id, post.channel, exc)
        _set_status(db, post, "failed", f"Scheduling error: {exc}")
        return False

    # Ensure result date reflects the exact scheduled slot for sheet writeback
    result["date"] = scheduled_at.strftime("%Y-%m-%dT%H:%M:%S+05:30")

    # If Gemini resolved a sheet row id and post didn't have one, persist it
    if result.get("id") and not post.sheet_row_id:
        post.sheet_row_id = str(result["id"])

    # Save enriched content to Post
    post.enriched_title = result.get("title") or post.title
    post.enriched_description = result.get("description") or post.description
    tags_list = result.get("tags", [])
    post.enriched_tags = ";".join(tags_list) if isinstance(tags_list, list) else (tags_list or post.tags)
    post.first_comment_text = result.get("firstComment") or ""
    post.scheduled_at = scheduled_at

    post.error_message = None
    _set_status(db, post, "scheduled")
    logger.info("Post %s scheduled at %s (sheet_row_id=%s)", post.id, result["date"], post.sheet_row_id)

    # Cache Gemini result for sheet write-back after upload
    _gemini_result_cache[post.id] = result
    return True


def _upload_single_post(post: Post, db) -> bool:
    """Upload a single scheduled post to YouTube. Returns True on success."""
    try:
        yt = get_youtube_client(post.channel)
    except Exception as exc:
        logger.error("YouTube auth failed for %s: %s", post.channel, exc)
        _set_status(db, post, "failed", f"auth error: {exc}")
        return False

    from backend.services.watermark import resolve_video_path
    video_p = resolve_video_path(post.clean_video_path, is_clean=True)
    if not video_p or not video_p.exists():
        video_p = resolve_video_path(post.video_path, is_clean=False)

    if not video_p or not video_p.exists():
        _set_status(db, post, "failed", f"Video file not found on server: {post.clean_video_path or post.video_path}")
        return False
    video_path = str(video_p)

    try:
        video_id = _do_upload(yt, post, video_path)
        post.youtube_video_id = video_id
        _set_status(db, post, "uploaded")
        _sheet_writeback(post.channel, post, video_id)

        # Multi-platform: Trigger Instagram Reels publishing if enabled for this channel
        try:
            from backend.services.instagram import publish_reel_for_post
            ig_res = publish_reel_for_post(post, db)
            if ig_res.get("success"):
                logger.info("Instagram Reel published for post %s: %s", post.id, ig_res.get("permalink"))
            elif not ig_res.get("skipped"):
                logger.warning("Instagram publishing status for post %s: %s", post.id, ig_res)
        except Exception as ig_exc:
            logger.warning("Instagram auto-publishing error for post %s: %s", post.id, ig_exc)

        return True
    except Exception as exc:
        if is_quota_error(exc):
            err = quota_error_message(exc)
            logger.warning("Quota error uploading post %s: %s", post.id, err)
            _set_status(db, post, "failed", err)
        else:
            logger.exception("Upload failed for post %s", post.id)
            _set_status(db, post, "failed", f"upload error: {exc}")
        return False


# In-memory cache: post_id -> Gemini result dict (for sheet write-back after upload)
_gemini_result_cache: dict[int, dict] = {}


def enrich_and_upload_one_post(post_id: int) -> None:
    """
    Process a single post: enrich → schedule → upload to YouTube with publishAt → writeback.
    Called by the serial job queue runner.
    """
    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        if not post:
            logger.warning("Post %s not found for upload", post_id)
            return

        if post.status == "cleaned":
            # Step 1: Enrich + schedule
            success = _schedule_single_post(post, db)
            if not success:
                return
            # Refresh post after schedule
            db.refresh(post)

        if post.status == "scheduled":
            # Step 2: Upload to YouTube immediately with publishAt
            _upload_single_post(post, db)

    except Exception:
        logger.exception("Error processing post %s in upload pipeline", post_id)
    finally:
        db.close()


def get_next_uploadable_post_id() -> int | None:
    """Return the ID of the oldest cleaned or scheduled post needing YouTube upload, or None."""
    db = SessionLocal()
    try:
        # Priority 1: cleaned posts needing enrichment + scheduling
        cleaned = (
            db.query(Post.id)
            .filter(Post.status == "cleaned")
            .order_by(Post.created_at.asc())
            .first()
        )
        if cleaned:
            return cleaned.id

        # Priority 2: scheduled posts needing upload to YouTube
        scheduled = (
            db.query(Post.id)
            .filter(
                Post.status == "scheduled",
                Post.youtube_video_id.is_(None),
            )
            .order_by(Post.created_at.asc())
            .first()
        )
        return scheduled.id if scheduled else None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Internal helpers                                                               #
# --------------------------------------------------------------------------- #

def _do_upload(yt, post: Post, video_path: str) -> str:
    """YouTube videos.insert. Returns video_id."""
    tags_list = [t.strip() for t in (post.enriched_tags or post.tags or "").split(";") if t.strip()]

    # Ensure scheduled_at is correctly converted to UTC ISO format for YouTube
    dt = post.scheduled_at
    if dt:
        if dt.tzinfo is None:
            import pytz
            dt = pytz.timezone(settings.timezone).localize(dt)
        dt_utc = dt.astimezone(timezone.utc)
        publish_at_iso = dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    else:
        publish_at_iso = None

    status_body = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
    }
    if publish_at_iso:
        status_body["publishAt"] = publish_at_iso

    body = {
        "snippet": {
            "title": (post.enriched_title or post.title)[:100],
            "description": post.enriched_description or post.description,
            "tags": tags_list[:500],
            "categoryId": "22",
        },
        "status": status_body,
    }

    media = MediaFileUpload(video_path, mimetype="video/*", resumable=True, chunksize=10 * 1024 * 1024)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response.get("id", "")
    logger.info("Post %s uploaded → YouTube video_id=%s (publishAt=%s)", post.id, video_id, publish_at_iso)
    return video_id


def _sheet_writeback(channel: str, post: Post, video_id: str) -> None:
    """
    Write scheduled date, upload_id, enriched title back to Google Sheet.
    Mirrors n8n "Append or update row in sheet" node.
    """
    if not settings.google_sheets_service_account_json:
        return

    # Prioritize post.sheet_row_id directly from the database record
    gemini_result = _gemini_result_cache.get(post.id)
    sheet_row_id = post.sheet_row_id or (gemini_result.get("id") if gemini_result else None)

    if not sheet_row_id:
        logger.debug("No sheet row id for post %s, skipping sheet write-back", post.id)
        return

    # Format scheduled_at with +05:30 IST timezone offset
    scheduled_str = ""
    if post.scheduled_at:
        import pytz
        dt = post.scheduled_at
        if dt.tzinfo is None:
            dt = pytz.timezone(settings.timezone).localize(dt)
        scheduled_str = dt.astimezone(pytz.timezone(settings.timezone)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
    elif gemini_result:
        scheduled_str = gemini_result.get("date", "")

    try:
        from backend.services.sheets import update_row_after_upload
        update_row_after_upload(
            channel=channel,
            row_id=sheet_row_id,
            scheduled_at=scheduled_str,
            upload_id=video_id,
            enriched_title=post.enriched_title or post.title,
        )
        logger.info(
            "Sheet write-back succeeded for post %s: row_id=%s, upload_id=%s, scheduled_at=%s",
            post.id, sheet_row_id, video_id, scheduled_str,
        )
        # Clean cache entry
        _gemini_result_cache.pop(post.id, None)
    except Exception as exc:
        logger.error("Sheet write-back failed for post %s on row %s: %s", post.id, sheet_row_id, exc)
        # Non-fatal — video is uploaded, sheet sync can be retried manually


# --------------------------------------------------------------------------- #
# Legacy entry points (kept for backward compat)                                #
# --------------------------------------------------------------------------- #

def _schedule_cleaned_posts(channel: str, db) -> None:
    cleaned_posts = (
        db.query(Post)
        .filter(Post.channel == channel, Post.status == "cleaned")
        .order_by(Post.created_at.asc())
        .all()
    )
    if not cleaned_posts:
        return

    for post in cleaned_posts:
        _schedule_single_post(post, db)


def _upload_due_posts(channel: str, db) -> None:
    now = datetime.now(timezone.utc)
    due_posts = (
        db.query(Post)
        .filter(
            Post.channel == channel,
            Post.status == "scheduled",
            Post.scheduled_at <= now,
        )
        .order_by(Post.scheduled_at.asc())
        .all()
    )
    if not due_posts:
        return

    for post in due_posts:
        _upload_single_post(post, db)


def run_upload_job() -> None:
    """Legacy APScheduler entry point — every 60 seconds."""
    db = SessionLocal()
    try:
        for channel in _get_active_channels(db):
            try:
                _schedule_cleaned_posts(channel, db)
            except Exception:
                logger.exception("Error scheduling posts for %s", channel)
            try:
                _upload_due_posts(channel, db)
            except Exception:
                logger.exception("Error uploading posts for %s", channel)
    finally:
        db.close()

