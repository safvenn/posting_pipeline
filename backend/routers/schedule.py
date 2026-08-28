"""
Schedule router — generates slot timetable matrix, handles drag-and-drop rescheduling, and queries live scheduled posts.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import pytz
from dateutil.parser import parse as parse_dt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models import ChannelConfig, Post
from backend.schemas import RescheduleRequest, ScheduleSlot, YouTubeScheduledPost
from backend.services.youtube_auth import get_youtube_client, is_quota_error
from backend.services.sheets import update_row_fields

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

IST = pytz.timezone(settings.timezone)

# The 2 Best Viral Peak Times for YouTube Shorts in India:
# Slot A: 12:30 PM IST (Lunchtime traffic peak)
# Slot B: 06:30 PM IST (Evening prime engagement peak)
VIRAL_SLOTS = [
    ("A", 12, 30),
    ("B", 18, 30),
]


def _slot_datetime(d: date, hour: int, minute: int) -> datetime:
    """Build an IST-aware datetime for a slot on a given date."""
    return IST.localize(datetime(d.year, d.month, d.day, hour, minute, 0))


def _to_ist(dt: datetime) -> datetime:
    """Ensure any datetime is converted to an IST-aware datetime."""
    if dt.tzinfo is None:
        return IST.localize(dt)
    return dt.astimezone(IST)


def _categorize_slot(dt: datetime) -> str:
    """
    Categorize a post datetime into Slot A (12:30 PM window), Slot B (6:30 PM window),
    or OFF_SLOT for non-standard times.
    """
    dt_ist = _to_ist(dt)
    total_minutes = dt_ist.hour * 60 + dt_ist.minute

    # Slot A: 12:30 PM ± 60 minutes (11:30 AM to 1:30 PM -> 690 to 810 mins)
    if 690 <= total_minutes <= 810:
        return "A"
    # Slot B: 06:30 PM ± 60 minutes (5:30 PM to 7:30 PM -> 1050 to 1170 mins)
    elif 1050 <= total_minutes <= 1170:
        return "B"
    else:
        return "OFF_SLOT"


def _fetch_youtube_channel_videos(yt, channel_key: str, extra_video_ids: list[str]) -> dict[str, dict]:
    """
    Query YouTube Data API for live video status (publishAt, privacyStatus, snippet).
    Returns mapping of video_id -> info dict.
    """
    yt_info_by_vid: dict[str, dict] = {}
    video_ids_to_query: set[str] = set(extra_video_ids)

    try:
        ch_resp = yt.channels().list(part="contentDetails,snippet", mine=True).execute()
        ch_items = ch_resp.get("items", [])
        if ch_items:
            uploads_id = ch_items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
            if uploads_id:
                pl_resp = yt.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=uploads_id,
                    maxResults=50,
                ).execute()
                for item in pl_resp.get("items", []):
                    vid = item.get("contentDetails", {}).get("videoId")
                    if vid:
                        video_ids_to_query.add(vid)
    except Exception as exc:
        logger.debug("Could not fetch channel uploads playlist for %s: %s", channel_key, exc)

    if not video_ids_to_query:
        return yt_info_by_vid

    # Batch query in chunks of 50
    vid_list = list(video_ids_to_query)
    for i in range(0, len(vid_list), 50):
        chunk = vid_list[i : i + 50]
        try:
            v_resp = yt.videos().list(part="snippet,status", id=",".join(chunk)).execute()
            for v in v_resp.get("items", []):
                vid = v.get("id")
                status_obj = v.get("status", {})
                snippet_obj = v.get("snippet", {})
                pub_str = status_obj.get("publishAt")
                privacy = status_obj.get("privacyStatus", "private")
                published_str = snippet_obj.get("publishedAt")

                dt = None
                is_live_scheduled = False
                is_live_published = False

                if pub_str:
                    try:
                        dt = parse_dt(pub_str).astimezone(IST)
                        is_live_scheduled = True
                    except Exception:
                        pass
                elif privacy == "public" and published_str:
                    try:
                        dt = parse_dt(published_str).astimezone(IST)
                        is_live_published = True
                    except Exception:
                        pass

                thumbnails = snippet_obj.get("thumbnails", {})
                thumb_url = (
                    thumbnails.get("maxres", {}).get("url")
                    or thumbnails.get("standard", {}).get("url")
                    or thumbnails.get("high", {}).get("url")
                    or thumbnails.get("medium", {}).get("url")
                    or thumbnails.get("default", {}).get("url")
                )

                yt_info_by_vid[vid] = {
                    "video_id": vid,
                    "title": snippet_obj.get("title", ""),
                    "description": snippet_obj.get("description", ""),
                    "tags": snippet_obj.get("tags", []),
                    "scheduled_at": dt,
                    "is_live_scheduled": is_live_scheduled,
                    "is_live_published": is_live_published,
                    "privacy_status": privacy,
                    "thumbnail_url": thumb_url,
                }
        except Exception as exc:
            logger.warning("Error fetching YouTube video batch for %s: %s", channel_key, exc)

    return yt_info_by_vid


@router.get("", response_model=List[ScheduleSlot])
def get_schedule_matrix(
    days: int = 7,
    channel: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Generate schedule slot matrix for the next `days` (default 7) for all active channels.
    Fetches real-time publishAt schedule times from YouTube Data API v3 and synchronizes with DB.
    Includes the 2 peak viral slots:
      - Slot A: 12:30 PM IST
      - Slot B: 06:30 PM IST
    Also returns off-slot or custom-time scheduled posts so no video is ever hidden.
    """
    days = max(1, min(days, 60))
    now_ist = datetime.now(IST)
    today = now_ist.date()

    # Query active channels
    query = db.query(ChannelConfig).filter(ChannelConfig.is_active == True)
    if channel and channel != "all":
        query = query.filter(ChannelConfig.key == channel)
    channels = query.all()

    ch_ig_map = {c.key: bool(c.instagram_enabled) for c in channels} if channels else {}

    if not channels:
        active_channel_list = [
            ("the_indian_kitchen", "The Indian Kitchen"),
            ("channel_a", "Channel A"),
            ("channel_b", "Channel B"),
        ]
    else:
        active_channel_list = [(c.key, c.display_name or c.key) for c in channels]

    results: list[ScheduleSlot] = []

    for channel_key, channel_name in active_channel_list:
        ig_enabled = ch_ig_map.get(channel_key, False)

        # 1. Fetch DB posts for this channel with scheduled_at (excluding failed posts)
        db_posts = (
            db.query(Post)
            .filter(
                Post.channel == channel_key,
                Post.scheduled_at.isnot(None),
                Post.status != "failed",
            )
            .all()
        )

        db_video_ids = [p.youtube_video_id for p in db_posts if p.youtube_video_id]

        # 2. Fetch live YouTube videos for this channel
        yt_info_by_vid: dict[str, dict] = {}
        try:
            yt = get_youtube_client(channel_key)
            yt_info_by_vid = _fetch_youtube_channel_videos(yt, channel_key, db_video_ids)
        except Exception as exc:
            logger.debug("Could not connect to YouTube client for %s: %s", channel_key, exc)

        # 3. Build unified deduplicated post list
        unified_posts: list[dict] = []
        processed_yt_vids: set[str] = set()

        for p in db_posts:
            yt_info = yt_info_by_vid.get(p.youtube_video_id) if p.youtube_video_id else None

            if yt_info and yt_info.get("is_live_scheduled") and yt_info.get("scheduled_at"):
                # YouTube has an authoritative schedule time
                yt_sched_dt = yt_info["scheduled_at"]
                if p.scheduled_at != yt_sched_dt:
                    try:
                        p.scheduled_at = yt_sched_dt
                        p.updated_at = datetime.now(timezone.utc)
                        db.commit()
                    except Exception:
                        pass
                final_dt = yt_sched_dt
                final_status = "scheduled"
                thumb_url = yt_info.get("thumbnail_url")
                final_title = yt_info.get("title") or p.enriched_title or p.title or "Untitled"
                processed_yt_vids.add(p.youtube_video_id)
            elif yt_info and yt_info.get("is_live_published"):
                final_dt = yt_info.get("scheduled_at") or _to_ist(p.scheduled_at)
                final_status = "commented" if p.first_comment_posted else "uploaded"
                thumb_url = yt_info.get("thumbnail_url")
                final_title = yt_info.get("title") or p.enriched_title or p.title or "Untitled"
                processed_yt_vids.add(p.youtube_video_id)
            else:
                final_dt = _to_ist(p.scheduled_at)
                final_status = p.status
                thumb_url = yt_info.get("thumbnail_url") if yt_info else None
                final_title = p.enriched_title or p.title or "Untitled"

            unified_posts.append({
                "post_id": p.id,
                "youtube_video_id": p.youtube_video_id,
                "title": final_title,
                "scheduled_at": final_dt,
                "status": final_status,
                "thumbnail_url": thumb_url,
                "instagram_post_url": p.instagram_post_url,
                "instagram_status": p.instagram_status,
                "source": "pipeline",
            })

        # Include any external YouTube scheduled videos not present in local DB
        for vid, yt_info in yt_info_by_vid.items():
            if vid not in processed_yt_vids and yt_info.get("is_live_scheduled") and yt_info.get("scheduled_at"):
                unified_posts.append({
                    "post_id": None,
                    "youtube_video_id": vid,
                    "title": yt_info.get("title") or "YouTube Scheduled Video",
                    "scheduled_at": yt_info["scheduled_at"],
                    "status": "scheduled",
                    "thumbnail_url": yt_info.get("thumbnail_url"),
                    "instagram_post_url": None,
                    "instagram_status": None,
                    "source": "youtube",
                })

        # 4. Group unified posts by date
        posts_by_date: dict[date, list[dict]] = {}
        for item in unified_posts:
            d = item["scheduled_at"].date()
            if d not in posts_by_date:
                posts_by_date[d] = []
            posts_by_date[d].append(item)

        # 5. Generate timetable slots for each day
        for day_offset in range(days):
            d = today + timedelta(days=day_offset)
            day_posts = posts_by_date.get(d, [])
            assigned_indices = set()

            # Process Slot A (12:30 PM) and Slot B (6:30 PM)
            for slot_label, hour, minute in VIRAL_SLOTS:
                slot_dt = _slot_datetime(d, hour, minute)
                is_in_future = (slot_dt > now_ist + timedelta(minutes=5))

                matched_item = None
                for idx, item in enumerate(day_posts):
                    if idx in assigned_indices:
                        continue
                    if _categorize_slot(item["scheduled_at"]) == slot_label:
                        matched_item = item
                        assigned_indices.add(idx)
                        break

                if matched_item:
                    results.append(
                        ScheduleSlot(
                            channel=channel_key,
                            channel_name=channel_name,
                            slot_label=slot_label,
                            scheduled_at=matched_item["scheduled_at"],
                            post_id=matched_item["post_id"],
                            post_title=matched_item["title"],
                            status=matched_item["status"],
                            is_available=False,
                            youtube_video_id=matched_item["youtube_video_id"],
                            thumbnail_url=matched_item.get("thumbnail_url"),
                            is_off_slot=False,
                            slot_time_formatted=matched_item["scheduled_at"].strftime("%I:%M %p"),
                            instagram_post_url=matched_item.get("instagram_post_url"),
                            instagram_status=matched_item.get("instagram_status"),
                            instagram_enabled=ig_enabled,
                        )
                    )
                else:
                    results.append(
                        ScheduleSlot(
                            channel=channel_key,
                            channel_name=channel_name,
                            slot_label=slot_label,
                            scheduled_at=slot_dt,
                            post_id=None,
                            post_title=None,
                            status=None,
                            is_available=is_in_future,
                            is_off_slot=False,
                            slot_time_formatted=f"{hour:02d}:{minute:02d}",
                            instagram_enabled=ig_enabled,
                        )
                    )

            # Any remaining posts on this date go into OFF_SLOT
            for idx, item in enumerate(day_posts):
                if idx not in assigned_indices:
                    results.append(
                        ScheduleSlot(
                            channel=channel_key,
                            channel_name=channel_name,
                            slot_label="OFF_SLOT",
                            scheduled_at=item["scheduled_at"],
                            post_id=item["post_id"],
                            post_title=item["title"],
                            status=item["status"],
                            is_available=False,
                            youtube_video_id=item["youtube_video_id"],
                            thumbnail_url=item.get("thumbnail_url"),
                            is_off_slot=True,
                            slot_time_formatted=item["scheduled_at"].strftime("%I:%M %p"),
                            instagram_post_url=item.get("instagram_post_url"),
                            instagram_status=item.get("instagram_status"),
                            instagram_enabled=ig_enabled,
                        )
                    )

    return results


def _format_youtube_error(exc: Exception) -> str:
    """Format YouTube HttpError into a clear human-readable message."""
    err_str = str(exc)
    if is_quota_error(exc):
        return "YouTube API daily quota limit reached (10,000 units/day)."

    # Try to parse JSON error message from HttpError
    if hasattr(exc, "content"):
        try:
            import json
            data = json.loads(exc.content.decode("utf-8") if isinstance(exc.content, bytes) else str(exc.content))
            err_obj = data.get("error", {})
            msg = err_obj.get("message")
            errors = err_obj.get("errors", [])
            reason = errors[0].get("reason") if errors else None

            if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
                return "YouTube API daily quota limit reached."
            if reason in ("forbidden", "accessNotConfigured") or "permission" in str(msg).lower():
                return f"YouTube permission error: {msg or 'Channel account does not own this video'}"
            if msg:
                return f"YouTube: {msg}"
        except Exception:
            pass

    if "403" in err_str:
        return "YouTube 403 Forbidden (Check channel authorization or quota limit)"
    return f"YouTube: {err_str[:70]}"


@router.post("/reschedule")
def reschedule_post(req: RescheduleRequest, db: Session = Depends(get_db)):
    """
    Drag-and-Drop / manual reschedule endpoint:
    Updates scheduled_at in pipeline database, syncs new publishAt to YouTube API,
    and updates Google Sheet row.
    """
    now_ist = datetime.now(IST)
    new_dt = _to_ist(req.new_scheduled_at)

    if new_dt <= now_ist + timedelta(minutes=2):
        raise HTTPException(status_code=400, detail="New scheduled time must be at least 2 minutes in the future.")

    post = None
    if req.post_id:
        post = db.get(Post, req.post_id)
    elif req.youtube_video_id:
        post = db.query(Post).filter(Post.youtube_video_id == req.youtube_video_id).first()

    video_id_to_update = req.youtube_video_id or (post.youtube_video_id if post else None)
    # Always prioritize the post's actual channel to avoid 403 authorization mismatch
    channel_key = (post.channel if post and post.channel else req.channel) or "channel_a"

    # 1. Update DB post if exists
    if post:
        post.scheduled_at = new_dt
        if post.status == "failed":
            post.status = "scheduled"
            post.error_message = None
        post.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Rescheduled DB Post %s to %s (channel=%s)", post.id, new_dt.isoformat(), channel_key)

        # Update Google Sheet row if post is bound to a sheet row
        if post.sheet_row_id:
            try:
                sheet_iso = new_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
                update_row_fields(channel_key, post.sheet_row_id, {"scheduled": sheet_iso})
                logger.info("Updated Google Sheet row #%s scheduled time to %s", post.sheet_row_id, sheet_iso)
            except Exception as exc:
                logger.warning("Could not update Google Sheet row for rescheduled post %s: %s", post.id, exc)

    # 2. Update YouTube Video publishAt if video is on YouTube
    yt_updated = False
    yt_error_msg = None
    if video_id_to_update:
        try:
            yt = get_youtube_client(channel_key)
            dt_utc = new_dt.astimezone(timezone.utc)
            pub_iso = dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            # Fetch existing snippet & status
            v_resp = yt.videos().list(part="snippet,status", id=video_id_to_update).execute()
            items = v_resp.get("items", [])
            if items:
                v = items[0]
                status_obj = v.get("status", {})
                snippet_obj = v.get("snippet", {})

                if status_obj.get("privacyStatus") == "public":
                    logger.info("Video %s is already public on YouTube, cannot alter publishAt", video_id_to_update)
                    yt_error_msg = "Video is already public on YouTube (time is fixed)"
                else:
                    update_body = {
                        "id": video_id_to_update,
                        "status": {
                            "privacyStatus": "private",
                            "publishAt": pub_iso,
                            "selfDeclaredMadeForKids": bool(status_obj.get("selfDeclaredMadeForKids", False)),
                            "embeddable": bool(status_obj.get("embeddable", True)),
                            "publicStatsViewable": bool(status_obj.get("publicStatsViewable", True)),
                        },
                    }
                    yt.videos().update(part="status", body=update_body).execute()
                    yt_updated = True
                    logger.info("Successfully updated YouTube video %s publishAt to %s on channel %s", video_id_to_update, pub_iso, channel_key)
            else:
                yt_error_msg = f"Video not found on YouTube under channel '{channel_key}'"
        except Exception as exc:
            yt_error_msg = _format_youtube_error(exc)
            logger.warning("Could not update YouTube publishAt for %s: %s", video_id_to_update, exc)

    msg = f"Rescheduled to {new_dt.strftime('%d %b, %I:%M %p')} IST"
    if video_id_to_update and yt_updated:
        msg += " ✓ Synced with YouTube Studio"
    elif video_id_to_update and yt_error_msg:
        msg += f" (DB updated. {yt_error_msg})"

    return {
        "success": True,
        "message": msg,
        "scheduled_at": new_dt.isoformat(),
        "youtube_updated": yt_updated,
        "youtube_note": yt_error_msg,
    }


@router.get("/posts", response_model=List[YouTubeScheduledPost])
def get_scheduled_posts_list(channel: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Fetch list of upcoming scheduled posts directly from YouTube API and the pipeline database.
    """
    results: list[YouTubeScheduledPost] = []
    seen_video_ids = set()

    query = db.query(ChannelConfig).filter(ChannelConfig.is_active == True)
    if channel and channel != "all":
        query = query.filter(ChannelConfig.key == channel)
    channels = query.all()

    for ch in channels:
        channel_key = ch.key
        channel_name = ch.display_name or ch.key

        try:
            yt = get_youtube_client(channel_key)
            ch_resp = yt.channels().list(part="contentDetails,snippet", mine=True).execute()
            ch_items = ch_resp.get("items", [])
            if ch_items:
                channel_name = ch_items[0].get("snippet", {}).get("title", channel_name)
                uploads_playlist_id = ch_items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                
                if uploads_playlist_id:
                    pl_resp = yt.playlistItems().list(
                        part="snippet,contentDetails",
                        playlistId=uploads_playlist_id,
                        maxResults=50,
                    ).execute()
                    
                    video_ids = [item.get("contentDetails", {}).get("videoId") for item in pl_resp.get("items", []) if item.get("contentDetails", {}).get("videoId")]
                    
                    if video_ids:
                        v_resp = yt.videos().list(
                            part="snippet,status",
                            id=",".join(video_ids[:50]),
                        ).execute()
                        
                        for v in v_resp.get("items", []):
                            vid_id = v.get("id")
                            status_obj = v.get("status", {})
                            snippet_obj = v.get("snippet", {})
                            publish_at_str = status_obj.get("publishAt")
                            privacy_status = status_obj.get("privacyStatus", "private")
                            
                            if publish_at_str:
                                try:
                                    pub_at = parse_dt(publish_at_str)
                                    if pub_at.tzinfo is None:
                                        pub_at = pub_at.replace(tzinfo=timezone.utc)
                                except Exception:
                                    pub_at = None
                                
                                thumbnails = snippet_obj.get("thumbnails", {})
                                thumb_url = (
                                    thumbnails.get("maxres", {}).get("url")
                                    or thumbnails.get("standard", {}).get("url")
                                    or thumbnails.get("high", {}).get("url")
                                    or thumbnails.get("medium", {}).get("url")
                                    or thumbnails.get("default", {}).get("url")
                                )

                                seen_video_ids.add(vid_id)
                                results.append(
                                    YouTubeScheduledPost(
                                        video_id=vid_id,
                                        title=snippet_obj.get("title", "Untitled Video"),
                                        channel_key=channel_key,
                                        channel_name=channel_name,
                                        scheduled_at=pub_at,
                                        privacy_status=f"Scheduled ({privacy_status.capitalize()})",
                                        thumbnail_url=thumb_url,
                                        description=snippet_obj.get("description", ""),
                                        tags=snippet_obj.get("tags", []),
                                        source="youtube",
                                    )
                                )
        except Exception as exc:
            logger.debug("Could not fetch live YouTube scheduled posts for %s: %s", channel_key, exc)

        db_query = (
            db.query(Post)
            .filter(
                Post.channel == channel_key,
                Post.status.in_(["scheduled", "uploaded"]),
                Post.scheduled_at.isnot(None),
            )
            .order_by(Post.scheduled_at.asc())
        )
        for post in db_query.all():
            if post.youtube_video_id and post.youtube_video_id in seen_video_ids:
                continue
            
            p_dt = post.scheduled_at
            if p_dt and p_dt.tzinfo is None:
                p_dt = IST.localize(p_dt)

            results.append(
                YouTubeScheduledPost(
                    video_id=post.youtube_video_id or f"db-{post.id}",
                    title=post.enriched_title or post.title or "Untitled",
                    channel_key=channel_key,
                    channel_name=channel_name,
                    scheduled_at=p_dt,
                    privacy_status=f"Pipeline ({post.status.capitalize()})",
                    thumbnail_url=None,
                    description=post.enriched_description or post.description,
                    tags=[t.strip() for t in (post.enriched_tags or post.tags or "").split(";") if t.strip()],
                    source="pipeline",
                    post_id=post.id,
                )
            )

    results.sort(
        key=lambda p: (
            p.scheduled_at.astimezone(timezone.utc).timestamp()
            if p.scheduled_at
            else float("inf")
        )
    )

    return results


from pydantic import BaseModel


class DeleteScheduleRequest(BaseModel):
    post_id: Optional[int] = None
    youtube_video_id: Optional[str] = None
    channel: Optional[str] = None


@router.post("/delete")
def delete_scheduled_video(req: DeleteScheduleRequest, db: Session = Depends(get_db)):
    """
    Permanently delete a scheduled video from YouTube Studio and the database,
    freeing up its scheduled slot immediately.
    """
    channel_key = req.channel
    video_id_to_delete = req.youtube_video_id
    post = None

    if req.post_id:
        post = db.get(Post, req.post_id)
        if post:
            if not video_id_to_delete:
                video_id_to_delete = post.youtube_video_id
            if not channel_key:
                channel_key = post.channel
    elif video_id_to_delete:
        post = db.query(Post).filter(Post.youtube_video_id == video_id_to_delete).first()
        if post and not channel_key:
            channel_key = post.channel

    yt_deleted = False
    yt_error = None
    if video_id_to_delete and channel_key:
        try:
            yt = get_youtube_client(channel_key)
            yt.videos().delete(id=video_id_to_delete).execute()
            yt_deleted = True
            logger.info("Successfully deleted video %s from YouTube Studio for channel %s", video_id_to_delete, channel_key)
        except Exception as exc:
            yt_error = str(exc)
            logger.warning("Could not delete video %s from YouTube: %s", video_id_to_delete, exc)

    db_deleted = False
    if post:
        try:
            from pathlib import Path
            for path_attr in ("video_path", "clean_video_path"):
                p = getattr(post, path_attr, None)
                if p:
                    try:
                        Path(p).unlink(missing_ok=True)
                    except Exception:
                        pass
            db.delete(post)
            db.commit()
            db_deleted = True
            logger.info("Deleted DB Post %s for video %s", post.id, video_id_to_delete)
        except Exception as exc:
            logger.warning("Could not delete post %s from DB: %s", post.id, exc)

    return {
        "success": True,
        "message": "Scheduled video deleted successfully from YouTube Studio and schedule matrix.",
        "youtube_deleted": yt_deleted,
        "database_deleted": db_deleted,
        "youtube_error": yt_error,
    }


@router.post("/clear-failed")
def clear_failed_schedules(db: Session = Depends(get_db)):
    """Reset or clear schedule timestamp for failed posts."""
    failed_posts = db.query(Post).filter(Post.status == "failed").all()
    count = 0
    for p in failed_posts:
        if p.scheduled_at:
            p.scheduled_at = None
            count += 1
    db.commit()
    return {"message": f"Cleared schedule timestamp from {count} failed posts", "count": count}


