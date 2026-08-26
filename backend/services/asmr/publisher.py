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
    """Instagram Reels publisher (stub — requires Instagram Graph API credentials)."""

    @property
    def platform_name(self) -> str:
        return "instagram"

    def is_configured(self) -> bool:
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
        logger.info("InstagramPublisher: would publish '%s'", title)
        return PublishResult(
            platform="instagram",
            post_id="stub",
            url=None,
            error_message="Instagram publisher not yet configured",
        )
