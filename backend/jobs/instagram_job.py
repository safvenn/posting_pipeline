"""
Instagram Scheduled Publishing Job

Logic:
  - Runs every 30s via the APScheduler serial queue
  - Finds posts where:
      1. instagram_enabled is True for the channel
      2. post is 'scheduled' or 'commented' and has a youtube_video_id
      3. scheduled_at has passed (video is now live on YouTube)
      4. instagram_status is 'none', 'container_ready', or 'failed' (not yet published / retry)
  - Waits for YouTube publish time + 5 min buffer (so YT is truly public first)
  - Then publishes the Reel via Instagram Graph API

This ensures Instagram posts at the SAME time as YouTube goes public.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.database import SessionLocal
from backend.models import ChannelConfig, Post

logger = logging.getLogger(__name__)

# How long after YouTube publishAt to wait before posting to Instagram
# YouTube has a ~1-2 min private→public flip delay; 5 min is safe
INSTAGRAM_PUBLISH_BUFFER_MINUTES = 5

# Max retry attempts for failed Instagram posts
MAX_INSTAGRAM_RETRIES = 3


def _to_utc_aware(dt: datetime) -> datetime:
    """
    Normalize any datetime to UTC-aware.
    In this application, naive datetimes (e.g. from SQLite or user input)
    represent local time (Asia/Kolkata). We localize to settings.timezone
    before converting to UTC, avoiding 5.5 hour shifts.
    """
    if dt is None:
        return dt
    if dt.tzinfo is None:
        try:
            import pytz
            from backend.config import settings
            tz_str = getattr(settings, "timezone", "Asia/Kolkata")
            local_tz = pytz.timezone(tz_str)
            return local_tz.localize(dt).astimezone(timezone.utc)
        except Exception:
            return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_next_instagram_publishable_post_id() -> int | None:
    """
    Return the ID of the highest priority post that:
      - has instagram_enabled = True for its channel
      - has youtube_video_id (was uploaded to YouTube)
      - has scheduled_at that has passed the buffer window
      - has instagram_status in ('none', 'container_ready', 'failed')
      - has NOT exceeded MAX_INSTAGRAM_RETRIES
      - is NOT 'permanently_failed' or 'published'

    Priority order:
      1. 'container_ready' (container already on Meta servers — instant publish, no video file needed)
      2. 'none' / 'pending' (fresh scheduled posts due for initial publish)
      3. 'failed' (retries — backoff delay enforced, never starves fresh posts)
    """
    db = SessionLocal()
    try:
        now_utc = datetime.now(timezone.utc)
        buffer = timedelta(minutes=INSTAGRAM_PUBLISH_BUFFER_MINUTES)
        retry_delay = timedelta(minutes=15)

        # Get all Instagram-enabled channel keys
        ig_channels = [
            c.key for c in db.query(ChannelConfig)
            .filter(
                ChannelConfig.instagram_enabled == True,
                ChannelConfig.instagram_account_id.isnot(None),
                ChannelConfig.instagram_access_token.isnot(None),
            ).all()
        ]
        if not ig_channels:
            return None

        # Fetch candidate posts excluding published and permanently_failed
        candidates = (
            db.query(Post)
            .filter(
                Post.channel.in_(ig_channels),
                Post.status.in_(["scheduled", "commented"]),
                Post.youtube_video_id.isnot(None),
                Post.scheduled_at.isnot(None),
                Post.instagram_media_id.is_(None),
                Post.instagram_status.in_(["none", "container_ready", "failed", "pending"]),
            )
            .all()
        )

        eligible: list[tuple[int, datetime, int]] = []
        # item tuple: (priority_rank, sched_utc, post_id)
        # priority_rank: 1 = container_ready, 2 = none/pending, 3 = failed

        for post in candidates:
            # Skip posts that exceeded retry limits
            if (post.retry_count or 0) >= MAX_INSTAGRAM_RETRIES:
                if post.instagram_status != "permanently_failed":
                    post.instagram_status = "permanently_failed"
                    post.updated_at = now_utc
                    db.commit()
                continue

            sched_utc = _to_utc_aware(post.scheduled_at)
            if sched_utc is None:
                continue

            # Check buffer: scheduled_at + buffer must be in the past
            if sched_utc + buffer > now_utc:
                continue

            # For failed posts: enforce retry delay backoff
            if post.instagram_status == "failed":
                updated_utc = _to_utc_aware(post.updated_at)
                if updated_utc and updated_utc + retry_delay > now_utc:
                    continue
                rank = 3
            elif post.instagram_status == "container_ready":
                rank = 1
            else:
                rank = 2

            eligible.append((rank, sched_utc, post.id))

        if not eligible:
            return None

        # Sort by priority rank first, then scheduled_at ascending
        eligible.sort(key=lambda x: (x[0], x[1]))
        return eligible[0][2]

    finally:
        db.close()


def auto_precreate_upcoming_containers(db: SessionLocal | None = None) -> int:
    """
    Look for scheduled posts entering the 23-hour window before publish time
    and pre-create their Instagram container while video file is still available.
    Returns count of pre-created containers.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    count = 0
    try:
        now_utc = datetime.now(timezone.utc)
        max_future = now_utc + timedelta(hours=23)

        # Get all Instagram-enabled channel keys
        ig_channels = [
            c.key for c in db.query(ChannelConfig)
            .filter(
                ChannelConfig.instagram_enabled == True,
                ChannelConfig.instagram_account_id.isnot(None),
                ChannelConfig.instagram_access_token.isnot(None),
            ).all()
        ]
        if not ig_channels:
            return 0

        from backend.services.instagram import pre_create_instagram_container

        upcoming = (
            db.query(Post)
            .filter(
                Post.channel.in_(ig_channels),
                Post.status.in_(["scheduled", "commented"]),
                Post.youtube_video_id.isnot(None),
                Post.scheduled_at.isnot(None),
                Post.instagram_media_id.is_(None),
                Post.instagram_container_id.is_(None),
                Post.instagram_status.in_(["none", "pending"]),
            )
            .all()
        )

        for post in upcoming:
            sched_utc = _to_utc_aware(post.scheduled_at)
            if sched_utc and now_utc < sched_utc <= max_future:
                try:
                    cid = pre_create_instagram_container(post, db)
                    if cid:
                        count += 1
                        logger.info("[Instagram] Auto-precreated container %s for post %s", cid, post.id)
                except Exception as exc:
                    logger.debug("[Instagram] Auto-precreate container skipped for post %s: %s", post.id, exc)

        return count
    finally:
        if close_db:
            db.close()


def publish_instagram_for_post(post_id: int) -> None:
    """
    Trigger Instagram Reels publishing for a single post at its scheduled time.
    Called by the serial job queue runner.
    """
    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        if not post:
            logger.warning("[Instagram] Post %s not found", post_id)
            return

        # Double-check post is eligible
        now_utc = datetime.now(timezone.utc)
        buffer = timedelta(minutes=INSTAGRAM_PUBLISH_BUFFER_MINUTES)

        if not post.youtube_video_id:
            logger.debug("[Instagram] Post %s has no YouTube video ID yet, skipping", post_id)
            return

        if not post.scheduled_at:
            logger.debug("[Instagram] Post %s has no scheduled_at, skipping", post_id)
            return

        # Normalize to UTC-aware
        sched_utc = _to_utc_aware(post.scheduled_at)

        if sched_utc + buffer > now_utc:
            logger.debug(
                "[Instagram] Post %s not ready yet — YouTube goes public at %s UTC, buffer ends at %s UTC (now: %s UTC)",
                post_id,
                sched_utc.strftime("%H:%M"),
                (sched_utc + buffer).strftime("%H:%M"),
                now_utc.strftime("%H:%M"),
            )
            return

        if post.instagram_status == "published" or post.instagram_media_id:
            logger.debug("[Instagram] Post %s already published to Instagram, skipping", post_id)
            return

        logger.info(
            "[Instagram] Publishing Reel for post %s (channel=%s, scheduled_at=%s, YT=%s, container=%s)",
            post_id, post.channel,
            post.scheduled_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(post.scheduled_at, 'strftime') else str(post.scheduled_at),
            post.youtube_video_id,
            post.instagram_container_id,
        )

        from backend.services.instagram import publish_reel_for_post
        result = publish_reel_for_post(post, db)

        if result.get("success"):
            logger.info(
                "[Instagram] ✓ Reel published for post %s: %s",
                post_id, result.get("permalink"),
            )
        elif result.get("skipped"):
            logger.debug("[Instagram] Post %s skipped: %s", post_id, result.get("reason"))
        else:
            logger.warning(
                "[Instagram] ✗ Reel publishing failed for post %s: %s",
                post_id, result.get("error"),
            )

    except Exception:
        logger.exception("[Instagram] Unexpected error publishing Reel for post %s", post_id)
    finally:
        db.close()


def run_instagram_publish_job(max_batch: int = 3) -> None:
    """
    Dedicated scheduler entry point.
    Publishes up to max_batch due Instagram posts per tick to catch up on any lag,
    and auto-precreates containers for upcoming posts.
    """
    # 1. First, check if any upcoming posts (within 23h) can pre-create containers
    try:
        auto_precreate_upcoming_containers()
    except Exception as exc:
        logger.debug("[Instagram] Error in auto_precreate_upcoming_containers: %s", exc)

    # 2. Publish due posts (up to max_batch to clear any backlog)
    processed = 0
    for _ in range(max_batch):
        post_id = get_next_instagram_publishable_post_id()
        if not post_id:
            break
        publish_instagram_for_post(post_id)
        processed += 1

    if processed == 0:
        logger.debug("[Instagram] No posts due for Instagram publishing right now")
    else:
        logger.info("[Instagram] Completed publishing run: %d post(s) processed", processed)
