"""
Video generation provider interface + stub implementation.

Adapter pattern: workflow orchestration calls the interface,
concrete providers handle the actual API.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class VideoStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class VideoResult:
    """Result from a video generation provider."""
    job_id: str
    status: VideoStatus
    url: str | None = None
    storage_key: str | None = None
    size_bytes: int | None = None
    mime_type: str = "video/mp4"
    duration_seconds: float | None = None
    error_message: str | None = None


class VideoGenerationProvider(ABC):
    """Abstract interface for video generation providers."""

    @abstractmethod
    def generate(self, prompt: str, food_item: str) -> VideoResult:
        """Submit a video generation job. Returns immediately with job_id."""
        ...

    @abstractmethod
    def get_status(self, job_id: str) -> VideoResult:
        """Check the status of a video generation job."""
        ...

    @abstractmethod
    def download(self, job_id: str) -> bytes:
        """Download the generated video. Only valid when status is COMPLETED."""
        ...

    @abstractmethod
    def cancel(self, job_id: str) -> None:
        """Cancel a pending/processing video generation job."""
        ...


class StubVideoProvider(VideoGenerationProvider):
    """
    Stub video provider for development/testing.
    Logs the prompt and returns a placeholder result immediately.
    """

    def generate(self, prompt: str, food_item: str) -> VideoResult:
        import uuid
        job_id = f"stub-{uuid.uuid4().hex[:12]}"
        logger.info(
            "StubVideoProvider: generated stub video for '%s' (job_id=%s, prompt_length=%d)",
            food_item, job_id, len(prompt),
        )
        return VideoResult(
            job_id=job_id,
            status=VideoStatus.COMPLETED,
            url=f"https://placeholder.video/asmr/{food_item.replace(' ', '-')}.mp4",
            storage_key=f"asmr/stubs/{job_id}.mp4",
            size_bytes=0,
            duration_seconds=30.0,
        )

    def get_status(self, job_id: str) -> VideoResult:
        return VideoResult(job_id=job_id, status=VideoStatus.COMPLETED)

    def download(self, job_id: str) -> bytes:
        return b""

    def cancel(self, job_id: str) -> None:
        logger.info("StubVideoProvider: cancel called for %s (no-op)", job_id)
