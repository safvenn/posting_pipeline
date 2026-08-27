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
from backend.services.youtube_auth import get_youtube_client

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


@router.get("", response_model=List[ScheduleSlot])
def get_schedule_matrix(
    days: int = 7,
    channel: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Generate schedule slot matrix for the next `days` (default 7) for all active channels.
    Includes the 2 peak viral slots:
      - Slot A: 12:30 PM IST
      - Slot B: 06:30 PM IST
    Also returns any off-slot or custom-time scheduled posts so no video is ever hidden.
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

        # 1. Fetch live YouTube scheduled videos
        yt_scheduled_list: list[dict] = []
        try:
            yt = get_youtube_client(channel_key)
            ch_resp = yt.channels().list(part="contentDetails,snippet", mine=True).execute()
            ch_items = ch_resp.get("items", [])
            if ch_items:
                uploads_id = ch_items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                if uploads_id:
                    pl_resp = yt.playlistItems().list(part="snippet,contentDetails", playlistId=uploads_id, maxResults=50).execute()
                    vid_ids = [item.get("contentDetails", {}).get("videoId") for item in pl_resp.get("items", []) if item.get("contentDetails", {}).get("videoId")]
                    if vid_ids:
                        v_resp = yt.videos().list(part="snippet,status", id=",".join(vid_ids[:50])).execute()
                        for v in v_resp.get("items", []):
                            status_obj = v.get("status", {})
                            pub_str = status_obj.get("publishAt")
                            if pub_str:
                                try:
                                    dt = parse_dt(pub_str).astimezone(IST)
                                    yt_scheduled_list.append({
                                        "title": v.get("snippet", {}).get("title"),
                                        "video_id": v.get("id"),
                                        "scheduled_at": dt,
                                        "status": "scheduled",
                                        "thumbnail_url": v.get("snippet", {}).get("thumbnails", {}).get("medium", {}).get("url"),
                                    })
                                except Exception:
                                    pass
        except Exception as exc:
            logger.debug("Could not fetch live YouTube scheduled for %s: %s", channel_key, exc)

        # 2. Fetch database posts for this channel with scheduled_at (excluding failed posts)
        db_posts = (
            db.query(Post)
            .filter(
                Post.channel == channel_key,
                Post.scheduled_at.isnot(None),
                Post.status != "failed",
            )
            .all()
        )

        # Build day-indexed post lists
        posts_by_date: dict[date, list[dict]] = {}

        for p in db_posts:
            dt = _to_ist(p.scheduled_at)
            d = dt.date()
            if d not in posts_by_date:
                posts_by_date[d] = []
            posts_by_date[d].append({
                "source": "db",
                "post_id": p.id,
                "title": p.enriched_title or p.title or "Untitled",
                "status": p.status,
                "scheduled_at": dt,
                "youtube_video_id": p.youtube_video_id,
                "thumbnail_url": None,
                "instagram_post_url": p.instagram_post_url,
                "instagram_status": p.instagram_status,
            })

        for yt_item in yt_scheduled_list:
            dt = yt_item["scheduled_at"]
            d = dt.date()
            # Avoid duplicate if already matched by DB post youtube_video_id
            if d in posts_by_date and any(x.get("youtube_video_id") == yt_item["video_id"] for x in posts_by_date[d]):
                continue
            if d not in posts_by_date:
                posts_by_date[d] = []
            posts_by_date[d].append({
                "source": "youtube",
                "post_id": None,
                "title": yt_item["title"],
                "status": yt_item["status"],
                "scheduled_at": dt,
                "youtube_video_id": yt_item["video_id"],
                "thumbnail_url": yt_item["thumbnail_url"],
                "instagram_post_url": None,
                "instagram_status": None,
            })

        # 3. Generate slots for each day
        for day_offset in range(days):
            d = today + timedelta(days=day_offset)
            day_posts = posts_by_date.get(d, [])

            assigned_posts = set()

            # Process Slot A (12:30 PM) and Slot B (6:30 PM)
            for slot_label, hour, minute in VIRAL_SLOTS:
                slot_dt = _slot_datetime(d, hour, minute)
                is_in_future = (slot_dt > now_ist + timedelta(minutes=15))

                # Find if any post falls in this slot category
                matched_item = None
                for idx, item in enumerate(day_posts):
                    if idx in assigned_posts:
                        continue
                    if _categorize_slot(item["scheduled_at"]) == slot_label:
                        matched_item = item
                        assigned_posts.add(idx)
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

            # Any remaining posts on this date are OFF_SLOT / Custom-time posts
            for idx, item in enumerate(day_posts):
                if idx not in assigned_posts:
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


@router.post("/reschedule")
def reschedule_post(req: RescheduleRequest, db: Session = Depends(get_db)):
    """
    Drag-and-Drop / manual reschedule endpoint:
    Updates scheduled_at in pipeline database and syncs new publishAt to YouTube API.
    """
    now_ist = datetime.now(IST)
    new_dt = _to_ist(req.new_scheduled_at)

    if new_dt <= now_ist + timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="New scheduled time must be at least 5 minutes in the future.")

    post = None
    if req.post_id:
        post = db.get(Post, req.post_id)
    elif req.youtube_video_id:
        post = db.query(Post).filter(Post.youtube_video_id == req.youtube_video_id).first()

    video_id_to_update = req.youtube_video_id or (post.youtube_video_id if post else None)
    channel_key = req.channel or (post.channel if post else "the_indian_kitchen")

    # 1. Update DB post if exists
    if post:
        post.scheduled_at = new_dt
        if post.status == "failed":
            post.status = "scheduled"
            post.error_message = None
        post.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Rescheduled DB Post %s to %s", post.id, new_dt.isoformat())

    # 2. Update YouTube Video publishAt if video is on YouTube
    yt_updated = False
    if video_id_to_update:
        try:
            yt = get_youtube_client(channel_key)
            dt_utc = new_dt.astimezone(timezone.utc)
            pub_iso = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Fetch existing status & snippet
            v_resp = yt.videos().list(part="snippet,status", id=video_id_to_update).execute()
            items = v_resp.get("items", [])
            if items:
                v = items[0]
                status_obj = v.get("status", {})
                snippet_obj = v.get("snippet", {})

                if status_obj.get("privacyStatus") != "public":
                    status_obj["publishAt"] = pub_iso
                    status_obj["privacyStatus"] = "private"

                    update_body = {
                        "id": video_id_to_update,
                        "snippet": {
                            "title": snippet_obj.get("title", ""),
                            "description": snippet_obj.get("description", ""),
                            "tags": snippet_obj.get("tags", []),
                            "categoryId": snippet_obj.get("categoryId", "22"),
                        },
                        "status": status_obj,
                    }
                    yt.videos().update(part="snippet,status", body=update_body).execute()
                    yt_updated = True
                    logger.info("Updated YouTube video %s publishAt to %s", video_id_to_update, pub_iso)
        except Exception as exc:
            logger.warning("Could not update YouTube publishAt for %s: %s", video_id_to_update, exc)

    return {
        "success": True,
        "message": f"Successfully rescheduled to {new_dt.strftime('%d %b %Y, %I:%M %p')} IST",
        "scheduled_at": new_dt.isoformat(),
        "youtube_updated": yt_updated,
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


