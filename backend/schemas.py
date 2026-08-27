"""Pydantic schemas for request/response validation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator


VALID_STATUSES = {
    "queued", "cleaning", "cleaned", "scheduled",
    "uploaded", "commented", "failed",
}


class PostCreate(BaseModel):
    channel: str
    title: str = ""
    description: Optional[str] = ""
    tags: Optional[str] = ""
    sheet_row_id: Optional[str] = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("channel cannot be empty")
        return v

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title cannot be empty")
        return v


class PostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    title: str
    description: str
    tags: str
    video_path: str
    clean_video_path: Optional[str]
    status: str
    scheduled_at: Optional[datetime]
    youtube_video_id: Optional[str]
    first_comment_posted: bool
    error_message: Optional[str]

    # Instagram Reels fields
    instagram_media_id: Optional[str] = None
    instagram_post_url: Optional[str] = None
    instagram_status: str = "none"
    instagram_error: Optional[str] = None

    # Google Sheet Row Matching
    sheet_row_id: Optional[str] = None

    enriched_title: Optional[str]
    enriched_description: Optional[str]
    enriched_tags: Optional[str]
    first_comment_text: Optional[str]
    channel_display_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at", "scheduled_at", when_used="json-unless-none")
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()



class PostList(BaseModel):
    total: int
    items: List[PostRead]


class ChannelCreate(BaseModel):
    display_name: str
    client_id: Optional[str] = ""
    client_secret: Optional[str] = ""
    key: Optional[str] = None
    refresh_token: Optional[str] = ""
    sheet_id: Optional[str] = None
    sheet_tab: Optional[str] = None
    seo_tags: Optional[str] = None
    instagram_account_id: Optional[str] = None
    instagram_access_token: Optional[str] = None
    instagram_enabled: bool = False
    instagram_username: Optional[str] = None


class ChannelUpdate(BaseModel):
    display_name: Optional[str] = None
    sheet_id: Optional[str] = None
    sheet_tab: Optional[str] = None
    seo_tags: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    instagram_account_id: Optional[str] = None
    instagram_access_token: Optional[str] = None
    instagram_enabled: Optional[bool] = None
    instagram_username: Optional[str] = None


class ChannelStats(BaseModel):
    channel: str
    display_name: str
    subscriber_count: int
    video_count: int
    recent_uploads: List[dict]
    auth_ok: bool
    is_custom: bool = False
    sheet_id: Optional[str] = None
    sheet_tab: Optional[str] = None
    instagram_account_id: Optional[str] = None
    instagram_enabled: bool = False
    instagram_username: Optional[str] = None
    instagram_ok: bool = False


class InstagramTestRequest(BaseModel):
    account_id: str
    access_token: str


class InstagramTestResponse(BaseModel):
    success: bool
    username: Optional[str] = None
    name: Optional[str] = None
    profile_picture_url: Optional[str] = None
    message: str


class ScheduleSlot(BaseModel):
    channel: str
    slot_label: str        # "A", "B", or "OFF_SLOT"
    scheduled_at: datetime
    post_id: Optional[int] = None
    post_title: Optional[str] = None
    status: Optional[str] = None
    is_available: bool = True
    channel_name: Optional[str] = None
    youtube_video_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    is_off_slot: bool = False
    slot_time_formatted: Optional[str] = None
    instagram_post_url: Optional[str] = None
    instagram_status: Optional[str] = None
    instagram_enabled: bool = False

    @field_serializer("scheduled_at", when_used="json-unless-none")
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()


class RescheduleRequest(BaseModel):
    channel: str
    new_scheduled_at: datetime
    post_id: Optional[int] = None
    youtube_video_id: Optional[str] = None


class YouTubeScheduledPost(BaseModel):
    video_id: str
    title: str
    channel_key: str
    channel_name: str
    scheduled_at: Optional[datetime] = None
    privacy_status: str = "private"
    thumbnail_url: Optional[str] = None
    description: Optional[str] = ""
    tags: Optional[List[str]] = []
    source: str = "youtube"
    post_id: Optional[int] = None

    @field_serializer("scheduled_at", when_used="json-unless-none")
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()


class RetryResponse(BaseModel):
    post_id: int
    new_status: str
    message: str


# --------------------------------------------------------------------------- #
# ASMR Content Workflow schemas                                                #
# --------------------------------------------------------------------------- #

ASMR_VALID_STATUSES = {
    "pending", "selecting_food", "generating_content", "validating_content",
    "generating_video", "video_ready", "publishing", "published",
    "notified", "failed", "retry_pending", "dry_run_complete",
}


class ASMRWorkflowTrigger(BaseModel):
    """Request body for manual ASMR workflow trigger."""
    dry_run: bool = False
    idempotency_key: Optional[str] = None


class ASMRWorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trigger_type: str
    status: str
    food_item_id: Optional[int]
    started_at: datetime
    completed_at: Optional[datetime]
    error_message: Optional[str]
    dry_run: bool
    idempotency_key: Optional[str]
    created_at: datetime
    updated_at: datetime


class ASMRWorkflowRunList(BaseModel):
    total: int
    items: List[ASMRWorkflowRunRead]


class ASMRContentJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_run_id: int
    food_item_id: int
    status: str
    food_name: str
    video_prompt: Optional[str]
    title: Optional[str]
    caption: Optional[str]
    description: Optional[str]
    tags: Optional[str]
    hashtags: Optional[str]
    video_url: Optional[str]
    error_message: Optional[str]
    retry_count: int
    created_at: datetime
    updated_at: datetime


class ASMRContentJobList(BaseModel):
    total: int
    items: List[ASMRContentJobRead]


class FoodItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    normalized_name: str
    status: str
    cycle_number: int
    used_at: Optional[datetime]
    created_at: datetime


class FoodItemCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty")
        return v


class FoodItemList(BaseModel):
    total: int
    items: List[FoodItemRead]


class ContentGenerationResult(BaseModel):
    """Structured output expected from Gemini for ASMR content."""
    caption: str
    description: str
    tags: List[str]
    prompt: str  # video_prompt in the n8n output format


class ASMRContentResult(BaseModel):
    """Full content result after validation and enrichment."""
    food_item: str
    title: str
    caption: str
    description: str
    tags: List[str]
    hashtags: List[str]
    video_prompt: str
