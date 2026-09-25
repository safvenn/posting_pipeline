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
import threading
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
from backend.services.workflow_logger import (
    wlog,
    YOUTUBE_UPLOAD_STARTED,
    YOUTUBE_UPLOAD_COMPLETED,
    ENRICHMENT_COMPLETED,
    SCHEDULE_ASSIGNED,
    SHEET_UPDATED,
    SHEET_UPDATE_FAILED,
    FAILED,
)
from backend.services.retry import schedule_retry, is_permanent_error, clear_retry_state
from backend.services.idempotency import IdempotencyService, youtube_publish_key, instagram_container_key
from backend.services.job_tracker import JobTracker
from backend.repositories.job_repository import JobType


logger = logging.getLogger(__name__)


def _enforce_title_seo(title: str, tags_str: str) -> str:
    """
    Post-process title to meet YouTube SEO requirements:
    1. Ensure primary tag from enriched_tags appears in title (if not already)
    2. Title ends with '#shorts' if not already
    3. Hard cap at 100 characters (YouTube limit)
    """
    title = (title or "").strip()

    # Get primary tag (first non-empty tag)
    tags = [t.strip() for t in tags_str.split(";") if t.strip()] if tags_str else []
    primary_tag = tags[0] if tags else ""

    # Embed primary tag if not already in title
    if primary_tag and primary_tag.lower() not in title.lower():
        candidate = f"{title} {primary_tag}"
        if len(candidate) <= 95:  # leave room for #shorts
            title = candidate

    # Ensure #shorts at end
    if "#shorts" not in title.lower():
        shorts_suffix = " #shorts"
        if len(title) + len(shorts_suffix) <= 100:
            title = title + shorts_suffix
        else:
            # Truncate title to fit #shorts within 100 chars
            title = title[:91].rstrip() + " #shorts"

    # Final hard cap
    if len(title) > 100:
        title = title[:97].rstrip() + "..."

    return title


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
        slot = post.scheduled_at or pick_next_slot(channel, db)
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
        logger.warning("Gemini enrichment failed for channel %s (falling back to rule-based): %s", channel, exc)
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
        logger.warning("Gemini enrichment returned no result, using rule-based scheduler for post %s", post.id)
        from backend.services._enrichment_rules import enrich_post as rule_enrich
        from backend.services.scheduler_logic import pick_next_slot
        sub_count = _get_subscriber_count(post.channel)
        enriched = rule_enrich(post.channel, post.title or "", post.description or "", post.tags or "", sub_count)
        try:
            scheduled_at = post.scheduled_at or pick_next_slot(post.channel, db)
        except Exception as exc:
            logger.error("Could not pick next slot for post %s (channel %s): %s", post.id, post.channel, exc)
            _set_status(db, post, "failed", f"Scheduling error: {exc}")
            return False
        result = {
            "id": post.sheet_row_id,
            "title": enriched.get("enriched_title") or post.title,
            "description": enriched.get("enriched_description") or post.description,
            "tags": [t.strip() for t in (enriched.get("enriched_tags") or "").split(";") if t.strip()],
            "firstComment": enriched.get("first_comment_text") or "",
            "date": scheduled_at.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
        }
    else:
        # Authoritative deterministic slot calculation
        from backend.services.scheduler_logic import pick_next_slot
        try:
            scheduled_at = post.scheduled_at or pick_next_slot(post.channel, db)
        except Exception as exc:
            logger.error("Could not pick next slot for post %s (channel %s): %s", post.id, post.channel, exc)
            _set_status(db, post, "failed", f"Scheduling error: {exc}")
            return False

    # Ensure result date reflects the exact scheduled slot
    result["date"] = scheduled_at.strftime("%Y-%m-%dT%H:%M:%S+05:30")

    # If Gemini resolved a sheet row id and post didn't have one, persist it
    if result.get("id") and not post.sheet_row_id:
        post.sheet_row_id = str(result["id"])

    # Save enriched content to Post DB row
    post.enriched_title = result.get("title") or post.title
    post.enriched_description = result.get("description") or post.description
    tags_list = result.get("tags", [])
    post.enriched_tags = ";".join(tags_list) if isinstance(tags_list, list) else (tags_list or post.tags)
    post.first_comment_text = result.get("firstComment") or ""
    post.scheduled_at = scheduled_at

    post.error_message = None
    _set_status(db, post, "scheduled")
    wlog(db, post_id=post.id, event_type=SCHEDULE_ASSIGNED, status="success",
         sheet_row_id=post.sheet_row_id,
         message=f"Scheduled at {result['date']}")
    logger.info(
        "Post %s scheduled at %s (sheet_row_id=%s) — Sheet will be updated only after YouTube upload succeeds",
        post.id, result["date"], post.sheet_row_id,
    )

    # NOTE: Google Sheet is NOT written here.
    # Sheet writeback (scheduled + upload_id + title) happens in _sheet_writeback
    # ONLY after the YouTube upload confirms a valid video_id.
    # This prevents orphan rows in the Sheet when upload fails after scheduling.

    return True


def _upload_single_post(post: Post, db) -> bool:
    """Upload a single scheduled post to YouTube. Returns True on success."""
    # --- IDEMPOTENCY CHECK ---
    # Before calling YouTube, check if we already successfully uploaded this post.
    # This prevents duplicate videos when: worker crashes after YouTube accepts upload
    # but before DB update; or when the same post is retried after a timeout.
    idempotency = IdempotencyService(db)
    idem_key = youtube_publish_key(post.id)
    idem_entry = idempotency.get_or_create(idem_key)

    if idem_entry.already_succeeded:
        # Upload already completed — recover the video_id and continue
        recovered_video_id = idem_entry.external_id or idem_entry.result_data.get("video_id")
        if recovered_video_id:
            logger.warning(
                "[Idempotency] Post %s: YouTube upload already succeeded (video_id=%s) — skipping duplicate upload",
                post.id, recovered_video_id,
            )
            post.youtube_video_id = recovered_video_id
            _set_status(db, post, "scheduled")
            clear_retry_state(post, db)
            # Trigger sheet writeback in case it was also missed
            _sheet_writeback(post.channel, post, recovered_video_id, db)
            return True
        # external_id not stored — fall through to re-attempt (safe: YouTube deduplicates by content)
        logger.warning("[Idempotency] Post %s: idempotency record succeeded but no video_id stored — re-uploading", post.id)

    try:
        yt = get_youtube_client(post.channel)
    except Exception as exc:
        logger.error("YouTube auth failed for %s: %s", post.channel, exc)
        idempotency.mark_failed(idem_key, f"auth error: {exc}")
        _clear_schedule_and_fail(db, post, f"auth error: {exc}")
        return False

    from backend.services.watermark import resolve_video_path, ensure_video_file_on_disk
    video_p = resolve_video_path(post.clean_video_path, is_clean=True)
    if not video_p or not video_p.exists():
        video_p = resolve_video_path(post.video_path, is_clean=False)

    # Auto-restore from Google Drive if missing locally (e.g. after Render ephemeral disk restart)
    if not video_p or not video_p.exists():
        if post.clean_drive_file_id:
            video_p = ensure_video_file_on_disk(
                post.clean_video_path or f"clean_{post.id}.mp4",
                is_clean=True,
                drive_file_id=post.clean_drive_file_id,
                channel=post.channel,
            )
        if (not video_p or not video_p.exists()) and post.drive_file_id:
            video_p = ensure_video_file_on_disk(
                post.video_path or f"input_{post.id}.mp4",
                is_clean=False,
                drive_file_id=post.drive_file_id,
                channel=post.channel,
            )

    if not video_p or not video_p.exists():
        err = f"Video file not found on server: {post.clean_video_path or post.video_path}"
        idempotency.mark_failed(idem_key, err)
        _clear_schedule_and_fail(db, post, err)
        return False
    video_path = str(video_p)

    # Note: 1080p Full HD remastering is already applied on the SSH worker (watermark.py Step 2.5).
    # No local FFmpeg re-encoding needed — avoids blocking Render's queue for 10+ minutes.

    try:
        # Emit STARTED before calling API — so crash mid-upload is detectable
        wlog(db, post_id=post.id, event_type=YOUTUBE_UPLOAD_STARTED, status="info",
             sheet_row_id=post.sheet_row_id, attempt=(post.retry_count or 0) + 1)

        video_id = _do_upload(yt, post, video_path)

        # Guard: only proceed if YouTube returned a real video ID
        if not video_id or not video_id.strip():
            err = "YouTube upload returned empty video_id — upload may have failed silently"
            logger.error("Post %s: %s", post.id, err)
            wlog(db, post_id=post.id, event_type=FAILED, status="failure", message=err)
            idempotency.mark_failed(idem_key, err)
            _clear_schedule_and_fail(db, post, err)
            return False

        # Mark idempotency SUCCEEDED immediately after receiving video_id
        # This ensures even if the next DB commit fails, a restart will recover
        idempotency.mark_succeeded(idem_key, external_id=video_id, result_data={"video_id": video_id})

        post.youtube_video_id = video_id
        _set_status(db, post, "scheduled")
        clear_retry_state(post, db)

        wlog(db, post_id=post.id, event_type=YOUTUBE_UPLOAD_COMPLETED, status="success",
             youtube_video_id=video_id, sheet_row_id=post.sheet_row_id)

        # Sheet is written ONLY here — with upload_id confirmed.
        # scheduled_at + upload_id + enriched_title all written in one atomic call.
        _sheet_writeback(post.channel, post, video_id, db)

        # Pre-create Instagram container while video file is still hot on disk.
        # IMPORTANT: Use post.id (not the post ORM object) to avoid sharing the
        # parent thread's SQLAlchemy session across threads (not thread-safe).
        _post_id_for_ig = post.id
        try:
            def _run_ig_precontainer(pid=_post_id_for_ig):
                from backend.database import SessionLocal
                from backend.services.instagram import pre_create_instagram_container
                _db = SessionLocal()
                try:
                    _post = _db.get(Post, pid)
                    if _post:
                        pre_create_instagram_container(_post, _db)
                except Exception as _exc:
                    logger.warning("Instagram pre-container failed for post %s: %s", pid, _exc)
                finally:
                    _db.close()

            threading.Thread(
                target=_run_ig_precontainer,
                name=f"ig-precontainer-{_post_id_for_ig}",
                daemon=True,
            ).start()
        except Exception as ig_exc:
            logger.warning("Could not spawn Instagram pre-container thread for post %s: %s", post.id, ig_exc)

        logger.info(
            "Post %s uploaded to YouTube (%s) — Instagram container will be pre-created; publishing at scheduled_at=%s",
            post.id, video_id,
            post.scheduled_at.strftime("%Y-%m-%d %H:%M UTC") if post.scheduled_at else "N/A",
        )

        return True
    except Exception as exc:
        if is_quota_error(exc):
            err = quota_error_message(exc)
            logger.warning("Quota error uploading post %s: %s", post.id, err)
            wlog(db, post_id=post.id, event_type=FAILED, status="failure", message=err)
            idempotency.mark_failed(idem_key, err)
            _clear_schedule_and_fail(db, post, err)
        elif is_permanent_error(exc):
            err = f"Permanent error: {exc}"
            logger.error("Permanent upload error for post %s: %s", post.id, err)
            wlog(db, post_id=post.id, event_type=FAILED, status="failure", message=err)
            idempotency.mark_failed(idem_key, err)
            _clear_schedule_and_fail(db, post, err)
        else:
            err = f"upload error: {exc}"
            logger.exception("Upload failed for post %s", post.id)
            wlog(db, post_id=post.id, event_type=FAILED, status="failure", message=err)
            idempotency.mark_failed(idem_key, err)
            decision = schedule_retry(post, db, err)
            if decision.exhausted:
                _clear_schedule_and_fail(db, post, err)
        return False



def _clear_schedule_and_fail(db, post: Post, error: str) -> None:
    """
    Mark post as failed AND clear scheduled_at so the slot is not blocked.
    Also clears Google Sheet entry if bound (avoids orphan scheduled rows).
    """
    post.scheduled_at = None
    post.status = "failed"
    post.error_message = error
    post.updated_at = datetime.now(timezone.utc)
    db.commit()
    logger.error("Post %s failed, schedule cleared: %s", post.id, error)

    # Clear sheet row if bound — free the slot
    if post.sheet_row_id and post.channel:
        try:
            from backend.services.sheets import update_row_fields
            update_row_fields(
                post.channel,
                post.sheet_row_id,
                {"scheduled": "", "upload id": ""},
            )
            logger.info(
                "Cleared Google Sheet row #%s for failed post %s",
                post.sheet_row_id, post.id,
            )
        except Exception as sheet_exc:
            logger.warning(
                "Could not clear Google Sheet row for failed post %s: %s",
                post.id, sheet_exc,
            )




# NOTE: _gemini_result_cache removed — enriched data persisted directly in
# Post.enriched_title / enriched_description / enriched_tags / first_comment_text columns.
# This ensures sheet write-back survives process restarts.


def enrich_one_post(post_id: int) -> None:
    """
    Step A (fast, runs IN the queue tick):
    Gemini enrichment + schedule slot assignment only.
    Transitions post: cleaned → scheduled.
    YouTube upload happens in the NEXT step (upload_one_post) in a background thread.
    """
    with JobTracker(post_id, JobType.ENRICH, input_data={"post_id": post_id}) as tracker:
        db = SessionLocal()
        try:
            post = db.get(Post, post_id)
            if not post:
                logger.warning("Post %s not found for enrichment", post_id)
                return
            if post.status != "cleaned":
                logger.warning("Post %s is %s not cleaned, skipping enrich", post_id, post.status)
                return
            success = _schedule_single_post(post, db)
            if success:
                tracker.set_output({"scheduled_at": str(post.scheduled_at), "channel": post.channel})
        except Exception:
            logger.exception("Error enriching post %s", post_id)
            raise
        finally:
            db.close()


def upload_one_post(post_id: int) -> None:
    """
    Step B (slow, runs in background thread spawned by queue):
    YouTube API upload only. Post must already be in 'scheduled' status with enriched data.
    Transitions post: scheduled → uploaded (status set by _upload_single_post).
    """
    with JobTracker(post_id, JobType.YOUTUBE_UPLOAD, input_data={"post_id": post_id}) as tracker:
        db = SessionLocal()
        try:
            post = db.get(Post, post_id)
            if not post:
                logger.warning("Post %s not found for YouTube upload", post_id)
                return
            if post.status != "scheduled":
                logger.warning("Post %s is %s not scheduled, skipping upload", post_id, post.status)
                return
            if post.youtube_video_id:
                logger.info("Post %s already has video_id %s, skipping upload", post_id, post.youtube_video_id)
                tracker.set_output({"video_id": post.youtube_video_id, "skipped": True},
                                   external_ref=post.youtube_video_id)
                return
            success = _upload_single_post(post, db)
            # Re-fetch video_id that _upload_single_post stored on post
            db.refresh(post)
            if success and post.youtube_video_id:
                tracker.set_output({"video_id": post.youtube_video_id},
                                   external_ref=post.youtube_video_id)
        except Exception:
            logger.exception("Error uploading post %s to YouTube", post_id)
            raise
        finally:
            db.close()


# Keep for backwards compatibility (called by some tests)
def enrich_and_upload_one_post(post_id: int) -> None:
    """Deprecated: use enrich_one_post + upload_one_post separately."""
    enrich_one_post(post_id)
    # Re-fetch to get updated status before upload
    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        if post and post.status == "scheduled" and not post.youtube_video_id:
            upload_one_post(post_id)
    finally:
        db.close()


def get_next_enrichable_post_id() -> int | None:
    """Return oldest `cleaned` post needing Gemini enrichment, or None."""
    db = SessionLocal()
    try:
        row = (
            db.query(Post.id)
            .filter(Post.status == "cleaned")
            .order_by(Post.created_at.asc())
            .first()
        )
        return row.id if row else None
    finally:
        db.close()


def get_next_uploadable_post_id() -> int | None:
    """Return oldest `scheduled` post needing YouTube upload (no video_id yet), or None."""
    db = SessionLocal()
    try:
        row = (
            db.query(Post.id)
            .filter(
                Post.status == "scheduled",
                Post.youtube_video_id.is_(None),
            )
            .order_by(Post.created_at.asc())
            .first()
        )
        return row.id if row else None
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

    # Build status body — always upload as private+publishAt
    # YouTube auto-publishes at publishAt time. NEVER upload as public directly.
    # If no scheduled_at: upload as private (no publishAt) — user must set time manually.
    status_body: dict = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
    }
    if publish_at_iso:
        status_body["publishAt"] = publish_at_iso
    else:
        logger.warning(
            "Post %s has no scheduled_at — uploading as private (no auto-publish time set)",
            post.id,
        )

    # Apply SEO title enforcement: primary tag in title, #shorts suffix, ≤ 100 chars
    raw_title = post.enriched_title or post.title or ""
    tags_str = post.enriched_tags or post.tags or ""
    seo_title = _enforce_title_seo(raw_title, tags_str)

    body = {
        "snippet": {
            "title": seo_title,
            "description": post.enriched_description or post.description,
            "tags": tags_list[:500],
            "categoryId": "22",
        },
        "status": status_body,
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=10 * 1024 * 1024)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response.get("id", "")
    logger.info("Post %s uploaded → YouTube video_id=%s (publishAt=%s)", post.id, video_id, publish_at_iso)
    return video_id


def _sheet_writeback(channel: str, post: Post, video_id: str, db) -> None:
    """
    Write scheduled date, upload_id, enriched title back to Google Sheet.
    Only called AFTER a confirmed youtube_video_id — never marks rows before that.

    On success: emits SHEET_UPDATED, then advances next unscheduled row's slot.
    On failure: emits SHEET_UPDATE_FAILED, retries up to 3 times with short backoff.
    """
    import time as _time
    if not settings.google_sheets_service_account_json:
        return

    sheet_row_id = post.sheet_row_id
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

    # Retry loop (3 attempts, 5s then 15s backoff)
    last_exc = None
    for attempt in range(1, 4):
        try:
            from backend.services.sheets import update_row_after_upload
            update_row_after_upload(
                channel=channel,
                row_id=sheet_row_id,
                scheduled_at=scheduled_str,
                upload_id=video_id,
                enriched_title=post.enriched_title or post.title,
            )
            wlog(db, post_id=post.id, event_type=SHEET_UPDATED, status="success",
                 youtube_video_id=video_id, sheet_row_id=sheet_row_id,
                 message=f"Sheet row {sheet_row_id} marked completed")
            logger.info(
                "Sheet write-back succeeded for post %s: row_id=%s, upload_id=%s, scheduled_at=%s",
                post.id, sheet_row_id, video_id, scheduled_str,
            )

            # Advance next eligible unscheduled row with next slot time
            try:
                from backend.services.sheets import get_first_unscheduled_row, update_row_fields
                from backend.services.scheduler_logic import pick_next_slot
                next_slot = pick_next_slot(channel, db)
                next_row = get_first_unscheduled_row(channel)
                if next_row and next_row.get("id"):
                    next_slot_str = next_slot.strftime("%Y-%m-%dT%H:%M:%S+05:30")
                    update_row_fields(channel, str(next_row["id"]), {"scheduled": next_slot_str})
                    logger.info(
                        "Sheet next-slot advanced: channel=%s row=%s slot=%s",
                        channel, next_row["id"], next_slot_str,
                    )
            except Exception as slot_exc:
                logger.warning("Could not advance next Sheet slot for channel %s: %s", channel, slot_exc)
            return

        except Exception as exc:
            last_exc = exc
            wlog(db, post_id=post.id, event_type=SHEET_UPDATE_FAILED, status="failure",
                 sheet_row_id=sheet_row_id, attempt=attempt, message=str(exc)[:500])
            logger.warning(
                "Sheet write-back attempt %d/3 failed for post %s row %s: %s",
                attempt, post.id, sheet_row_id, exc,
            )
            if attempt < 3:
                _time.sleep(5 * attempt)

    logger.error(
        "Sheet write-back failed after 3 attempts for post %s row %s: %s",
        post.id, sheet_row_id, last_exc,
    )
    # Non-fatal — video IS uploaded, sheet sync can be re-triggered manually


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
    """Upload all scheduled posts that do not yet have a YouTube video ID.
    Posts upload immediately after scheduling — they upload as private+publishAt
    so YouTube auto-publishes at the correct time. We do NOT wait until scheduled_at
    has passed (that would be too late).
    """
    due_posts = (
        db.query(Post)
        .filter(
            Post.channel == channel,
            Post.status == "scheduled",
            Post.youtube_video_id.is_(None),  # not yet uploaded
        )
        .order_by(Post.created_at.asc())
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

