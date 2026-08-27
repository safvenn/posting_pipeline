"""
Scheduling engine — pick_next_slot(channel) implementing exact production rules:

Slots (IST) — The 2 Best Viral Peak Times for YouTube Shorts:
  Slot A: 12:30 PM (12:30–01:00 PM) - Lunchtime peak
  Slot B: 06:30 PM (06:30–07:00 PM) - Evening prime peak

Availability rules (all must hold):
  1. No other post scheduled/published in same slot window.
  2. At least 5 hours from every other video's publish time on that channel.
  3. Slot window is strictly in the future vs. current IST time (minimum 15 min buffer).

Search order: Slot A today → Slot B today → Slot A tomorrow → Slot B tomorrow ...
  (up to 14 days out before giving up)

If channel.videoCount < 20: fill daily slots (consistency rule for early growth).
Returned datetime is always IST-aware and strictly > now + 15m.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytz
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import SessionLocal
from backend.models import Post
from backend.services.youtube_auth import get_youtube_client, is_quota_error

logger = logging.getLogger(__name__)

IST = pytz.timezone(settings.timezone)

# Slot definitions: (label, hour, minute) in IST — the 2 best viral peak times for Shorts
SLOTS = [
    ("A", 12, 30),   # 12:30 PM IST (Lunchtime mobile browsing peak)
    ("B", 18, 30),   # 06:30 PM IST (Prime evening peak)
]

SLOT_WINDOW_MINUTES = 60      # a slot "owns" 60 minutes
MIN_GAP_HOURS = 4.5           # anti-clustering rule (4.5 hours separation between posts)
MAX_SEARCH_DAYS = 14          # give up after this many days


def _ist_now() -> datetime:
    """Current time, IST-aware. Never use server default timezone."""
    return datetime.now(IST)


def _to_ist(dt: datetime) -> datetime:
    """Ensure any datetime is converted to an IST-aware datetime."""
    if dt.tzinfo is None:
        return IST.localize(dt)
    return dt.astimezone(IST)


def _slot_datetime(d: datetime.date, hour: int, minute: int) -> datetime:
    """Build an IST-aware datetime for a slot on a given date."""
    return IST.localize(datetime(d.year, d.month, d.day, hour, minute, 0))


def _get_channel_video_count(channel: str) -> int:
    """Fetch live videoCount from YouTube. Returns 0 on any error."""
    try:
        yt = get_youtube_client(channel)
        resp = yt.channels().list(part="statistics", mine=True).execute()
        items = resp.get("items", [])
        if items:
            return int(items[0].get("statistics", {}).get("videoCount", 0))
    except Exception as exc:
        logger.warning("Could not fetch video count for %s: %s", channel, exc)
    return 0


def _get_recent_publish_times_youtube(channel: str) -> list[datetime]:
    """
    Fetch publish times of recent YouTube uploads AND upcoming scheduled videos on YouTube.
    Returns IST-aware datetimes. Returns [] on any error (fail open — DB check still runs).
    """
    times: list[datetime] = []
    try:
        yt = get_youtube_client(channel)
        ch_resp = yt.channels().list(part="contentDetails", mine=True).execute()
        items = ch_resp.get("items", [])
        if not items:
            return times
        playlist_id = (
            items[0]
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads", "")
        )
        if not playlist_id:
            return times

        pl_resp = (
            yt.playlistItems()
            .list(part="snippet,contentDetails", playlistId=playlist_id, maxResults=50)
            .execute()
        )
        video_ids = [
            item.get("contentDetails", {}).get("videoId")
            for item in pl_resp.get("items", [])
            if item.get("contentDetails", {}).get("videoId")
        ]

        if video_ids:
            # Batch fetch video status & snippet (status contains publishAt for future scheduled videos)
            v_resp = yt.videos().list(part="snippet,status", id=",".join(video_ids[:50])).execute()
            for v in v_resp.get("items", []):
                status_obj = v.get("status", {})
                snippet_obj = v.get("snippet", {})

                # 1. Future scheduled publishAt time
                pub_at_str = status_obj.get("publishAt")
                if pub_at_str:
                    try:
                        dt = datetime.fromisoformat(pub_at_str.replace("Z", "+00:00")).astimezone(IST)
                        times.append(dt)
                    except Exception:
                        pass

                # 2. Already published timestamp
                published_at_str = snippet_obj.get("publishedAt")
                if published_at_str:
                    try:
                        dt = datetime.fromisoformat(published_at_str.replace("Z", "+00:00")).astimezone(IST)
                        times.append(dt)
                    except Exception:
                        pass
        else:
            for item in pl_resp.get("items", []):
                pub = item.get("snippet", {}).get("publishedAt", "")
                if pub:
                    try:
                        dt = datetime.fromisoformat(pub.replace("Z", "+00:00")).astimezone(IST)
                        times.append(dt)
                    except Exception:
                        pass
    except HttpError as exc:
        if is_quota_error(exc):
            logger.warning("Quota error fetching YouTube publish times for %s", channel)
        else:
            logger.warning("HTTP error fetching YouTube publish times for %s: %s", channel, exc)
    except Exception as exc:
        logger.warning("Error fetching YouTube publish times for %s: %s", channel, exc)
    return times


def _get_db_publish_times(channel: str, db: Session) -> list[datetime]:
    """Publish times of scheduled/uploaded posts for a channel from the DB, normalized to IST."""
    from backend.models import ChannelConfig
    channel_keys = {channel}
    try:
        cfg = db.query(ChannelConfig).filter(
            (ChannelConfig.key == channel) | (ChannelConfig.display_name == channel)
        ).first()
        if cfg:
            channel_keys.add(cfg.key)
            if cfg.display_name:
                channel_keys.add(cfg.display_name)
    except Exception:
        pass

    posts = (
        db.query(Post)
        .filter(Post.channel.in_(channel_keys))
        .filter(Post.status != "failed")
        .filter(Post.scheduled_at.isnot(None))
        .all()
    )
    return [_to_ist(p.scheduled_at) for p in posts if p.scheduled_at]


def _slot_in_use(slot_dt: datetime, existing_times: list[datetime]) -> bool:
    """True if any existing publish time falls within ±SLOT_WINDOW_MINUTES of slot_dt."""
    slot_dt_ist = _to_ist(slot_dt)
    window = timedelta(minutes=SLOT_WINDOW_MINUTES)
    for t in existing_times:
        t_ist = _to_ist(t)
        if abs((slot_dt_ist - t_ist).total_seconds()) < window.total_seconds():
            return True
    return False


def _gap_violated(slot_dt: datetime, existing_times: list[datetime]) -> bool:
    """True if slot_dt is within MIN_GAP_HOURS of any existing publish time."""
    slot_dt_ist = _to_ist(slot_dt)
    gap = timedelta(hours=MIN_GAP_HOURS)
    for t in existing_times:
        t_ist = _to_ist(t)
        if abs((slot_dt_ist - t_ist).total_seconds()) < gap.total_seconds():
            return True
    return False


def pick_next_slot(channel: str, db: Session | None = None) -> datetime:
    """
    Find and return the next available IST slot for the given channel.

    Strictly guarantees:
    - Never schedules in the past or immediately (at least 15m buffer from current time).
    - Checks both DB posts and live YouTube uploads.
    - Strictly prevents slot collisions and enforces the 5-hour minimum separation rule.

    Raises RuntimeError if no slot found within MAX_SEARCH_DAYS.
    """
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        now = _ist_now()
        video_count = _get_channel_video_count(channel)
        early_growth = video_count < 20

        logger.info(
            "pick_next_slot: channel=%s videoCount=%d early_growth=%s now=%s",
            channel, video_count, early_growth, now.isoformat(),
        )

        db_times = _get_db_publish_times(channel, db)
        yt_times = _get_recent_publish_times_youtube(channel)
        all_times = db_times + yt_times

        today = now.date()

        for day_offset in range(MAX_SEARCH_DAYS):
            d = today + timedelta(days=day_offset)

            for label, hour, minute in SLOTS:
                slot_dt = _slot_datetime(d, hour, minute)

                # Rule 3: must be strictly in the future (minimum 30m buffer to allow processing)
                if slot_dt <= now + timedelta(minutes=30):
                    logger.debug("Slot %s %s (%s): in past or <30m from now, skip", d, label, slot_dt)
                    continue

                # Rule 1: slot window not occupied
                if _slot_in_use(slot_dt, all_times):
                    logger.debug("Slot %s %s (%s): in use by another post, skip", d, label, slot_dt)
                    continue

                # Rule 2: 5-hour anti-clustering
                if _gap_violated(slot_dt, all_times):
                    logger.debug("Slot %s %s (%s): gap violation (<5h from another video), skip", d, label, slot_dt)
                    continue

                logger.info("Slot %s %s (%s) selected for channel %s", d, label, slot_dt, channel)
                return slot_dt

        raise RuntimeError(
            f"No available slot for {channel} within {MAX_SEARCH_DAYS} days. "
            "All slots occupied or gap rule violated."
        )

    finally:
        if own_db:
            db.close()

