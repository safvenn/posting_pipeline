"""
Social media publishing adapters.

Common interface for all platforms.
Each publisher handles auth, upload, scheduling, retries, rate limits.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """Result from a publishing operation."""
    platform: str
    post_id: str
    url: str | None = None
    published_at: str | None = None
    error_message: str | None = None


class Publisher(ABC):
    """Abstract interface for social media publishers."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        ...

    @abstractmethod
    def publish(
        self,
        title: str,
        description: str,
        tags: list[str],
        video_path: Optional[str] = None,
        video_url: Optional[str] = None,
        scheduled_at: Optional[str] = None,
    ) -> PublishResult:
        """Publish content to the platform."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if this publisher has valid credentials."""
        ...


class YouTubePublisher(Publisher):
    """YouTube Shorts publisher (stub — requires YouTube Data API credentials)."""

    @property
    def platform_name(self) -> str:
        return "youtube"

    def is_configured(self) -> bool:
        # Would check for YouTube OAuth credentials
        return False

    def publish(
        self,
        title: str,
        description: str,
        tags: list[str],
        video_path: Optional[str] = None,
        video_url: Optional[str] = None,
        scheduled_at: Optional[str] = None,
    ) -> PublishResult:
        logger.info("YouTubePublisher: would publish '%s'", title)
        return PublishResult(
            platform="youtube",
            post_id="stub",
            url=None,
            error_message="YouTube publisher not yet configured",
        )


class InstagramPublisher(Publisher):
    """Instagram Reels publisher."""

    @property
    def platform_name(self) -> str:
        return "instagram"

    def _get_credentials(self) -> tuple[str, str] | None:
        from backend.database import SessionLocal
        from backend.models import ChannelConfig
        with SessionLocal() as db:
            ch = db.query(ChannelConfig).filter(ChannelConfig.instagram_enabled == True).first()
            if ch and ch.instagram_account_id and ch.instagram_access_token:
                return ch.instagram_account_id, ch.instagram_access_token
        return None

    def is_configured(self) -> bool:
        return self._get_credentials() is not None

    def publish(
        self,
        title: str,
        description: str,
        tags: list[str],
        video_path: Optional[str] = None,
        video_url: Optional[str] = None,
        scheduled_at: Optional[str] = None,
    ) -> PublishResult:
        import os
        from datetime import datetime, timezone
        from backend.services.instagram import (
            create_reels_container,
            wait_for_container_ready,
            publish_container,
            fetch_media_permalink,
            format_instagram_caption,
            upload_video_resumable
        )
        
        creds = self._get_credentials()
        if not creds:
            return PublishResult(
                platform="instagram",
                post_id="",
                url=None,
                error_message="Instagram publisher not configured (no active channel with instagram_enabled found)",
            )
        
        account_id, access_token = creds
        caption = format_instagram_caption(title=title, description=description, tags=tags)
        
        try:
            logger.info("InstagramPublisher: Creating Reels container for '%s'", title)
            container_data = create_reels_container(
                account_id=account_id,
                access_token=access_token,
                caption=caption,
                video_path=video_path if not video_url else None,
                video_url=video_url,
            )
            container_id = container_data["id"]
            upload_uri = container_data.get("uri")

            if upload_uri and video_path and os.path.exists(video_path):
                logger.info("InstagramPublisher: Uploading video binary (resumable) for '%s'", title)
                upload_video_resumable(
                    upload_uri=upload_uri,
                    access_token=access_token,
                    video_path=video_path,
                )

            logger.info("InstagramPublisher: Waiting for container %s to be ready", container_id)
            wait_for_container_ready(container_id=container_id, access_token=access_token)

            logger.info("InstagramPublisher: Publishing container %s", container_id)
            media_id = publish_container(
                account_id=account_id,
                access_token=access_token,
                container_id=container_id,
            )

            permalink = fetch_media_permalink(media_id=media_id, access_token=access_token)
            if not permalink:
                permalink = f"https://www.instagram.com/reel/{media_id}/"

            logger.info("InstagramPublisher: Successfully published Reel %s", media_id)
            return PublishResult(
                platform="instagram",
                post_id=media_id,
                url=permalink,
                published_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.error("InstagramPublisher failed to publish: %s", exc)
            return PublishResult(
                platform="instagram",
                post_id="",
                url=None,
                error_message=str(exc),
            )
