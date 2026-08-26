"""ORM models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="")
    video_path: Mapped[str] = mapped_column(Text, nullable=False)
    clean_video_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status lifecycle:
    # queued -> cleaning -> cleaned -> scheduled -> uploaded -> commented -> failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)

    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    youtube_video_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_comment_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Instagram Reels integration
    instagram_media_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    instagram_post_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    instagram_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    instagram_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Google Sheets Row Matching
    sheet_row_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Enriched content (written during enrichment phase)
    enriched_title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    enriched_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enriched_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_comment_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Post id={self.id} channel={self.channel} status={self.status}>"


# --------------------------------------------------------------------------- #
# ASMR Content Workflow models                                                 #
# --------------------------------------------------------------------------- #

class FoodItem(Base):
    __tablename__ = "food_items"
    __table_args__ = (
        UniqueConstraint("normalized_name", "cycle_number", name="uq_food_cycle"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<FoodItem id={self.id} name={self.name!r} status={self.status} cycle={self.cycle_number}>"


class ASMRWorkflowRun(Base):
    __tablename__ = "asmr_workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    food_item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("food_items.id"), nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<ASMRWorkflowRun id={self.id} status={self.status} trigger={self.trigger_type}>"


class ASMRContentJob(Base):
    __tablename__ = "asmr_content_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workflow_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("asmr_workflow_runs.id"), nullable=False, index=True,
    )
    food_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("food_items.id"), nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    food_name: Mapped[str] = mapped_column(String(128), nullable=False)
    video_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hashtags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    video_storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    video_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    video_mime_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    video_duration_seconds: Mapped[Optional[float]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<ASMRContentJob id={self.id} food={self.food_name!r} status={self.status}>"


class ASMRPublishedContent(Base):
    __tablename__ = "asmr_published_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    content_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("asmr_content_jobs.id"), nullable=False, index=True,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_post_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<ASMRPublishedContent id={self.id} platform={self.platform}>"


class ChannelConfig(Base):
    __tablename__ = "channel_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    client_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    client_secret: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sheet_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sheet_tab: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    seo_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Instagram integration per channel
    instagram_account_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    instagram_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    instagram_username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<ChannelConfig id={self.id} key={self.key!r} name={self.display_name!r}>"
