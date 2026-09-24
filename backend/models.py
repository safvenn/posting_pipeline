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
    # Pre-created container ID (created while video file is hot on disk, published later at scheduled_at)
    instagram_container_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Google Sheets Row Matching
    sheet_row_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Enriched content (written during enrichment phase)
    enriched_title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    enriched_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enriched_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_comment_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Google Drive archive
    drive_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    clean_drive_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    drive_upload_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none", index=True
    )  # none | pending | completed | failed

    # Retry state — persisted so restarts can resume
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

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


# ---------------------------------------------------------------------------
# Workflow audit trail
# ---------------------------------------------------------------------------

class WorkflowEvent(Base):
    """Immutable append-only audit log for every pipeline step on a Post."""
    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Values: success | failure | info | retry
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="info")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON-serialised extra context (drive_file_id, youtube_video_id, sheet_row_id, etc.)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    def __repr__(self) -> str:
        return f"<WorkflowEvent id={self.id} post={self.post_id} type={self.event_type} status={self.status}>"


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


# --------------------------------------------------------------------------- #
# App-wide Settings (key-value toggles)                                        #
# --------------------------------------------------------------------------- #

class AppSettings(Base):
    """Global pipeline settings stored as key-value pairs.

    Known keys:
      clean_watermark_enabled  — 'true' | 'false'
        When 'false', newly queued posts skip watermark cleaning (gwr SSH step)
        and go directly to the enrichment/schedule step instead.
    """
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<AppSettings key={self.key!r} value={self.value!r}>"


# --------------------------------------------------------------------------- #
# Idempotency Keys — duplicate-publish prevention                             #
# --------------------------------------------------------------------------- #

class PostIdempotencyRecord(Base):
    """
    Database-backed idempotency record for external side effects.

    Prevents duplicate YouTube uploads, Instagram publishes, Drive archives,
    and Sheet updates after worker crashes or network timeouts.

    Key format examples:
      youtube:post:182:publish
      instagram:post:182:publish
      instagram:post:182:container_create
      sheet:post:182:update
      drive:post:182:archive_original
    """
    __tablename__ = "post_idempotency_records"
    __table_args__ = (
        UniqueConstraint("key", name="uq_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    # pending | succeeded | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    # Provider-returned identifier (e.g. YouTube video_id, Instagram media_id)
    external_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # JSON-serialized result payload for re-use without re-executing
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Error detail if status == failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # When this record expires and can be cleaned up
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # When the operation was last executed
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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
        return f"<PostIdempotencyRecord key={self.key!r} status={self.status!r} external_id={self.external_id!r}>"


# --------------------------------------------------------------------------- #
# Job — durable execution record per pipeline step                            #
# --------------------------------------------------------------------------- #

class Job(Base):
    """
    Durable execution record for each pipeline step attempted on a Post.

    Separates EXECUTION state (what is running right now, attempt number,
    worker identity, duration) from BUSINESS state (post.status, which
    represents the content lifecycle).

    Design rationale:
      - Post.status = current content lifecycle state (queued → commented)
      - Job = a specific attempt to advance a Post through a step
      - Multiple Jobs can exist for a single Post (retries create new Jobs)
      - Enables: retry auditing, per-step latency tracking, worker identification,
        DLQ visibility without polluting the Post model

    Job lifecycle: created → running → succeeded | failed | cancelled
    """
    __tablename__ = "jobs"
    __table_args__ = (
        # Fast lookup: all jobs for a post
        __import__("sqlalchemy").Index("ix_jobs_post_id_created_at", "post_id", "created_at"),
        # Fast lookup: jobs by status (queue depth monitoring)
        __import__("sqlalchemy").Index("ix_jobs_status_scheduled_at", "status", "scheduled_at"),
        # Fast lookup: running jobs (stale lock detection)
        __import__("sqlalchemy").Index("ix_jobs_status_started_at", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Which post this job is for (nullable for system-level jobs like ASMR workflow)
    post_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Job type: clean | enrich | youtube_upload | comment | instagram_publish |
    #           drive_archive | sheet_sync | asmr_workflow | auto_generate
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Execution state: created | scheduled | running | succeeded | failed | cancelled | dead_letter
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)

    # Attempt number for this job_type + post_id combination (1-based)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Worker identity — process ID or hostname of the worker that picked this up
    worker_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # When this job was queued for execution
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # When the worker picked it up
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # When it finished (succeeded or failed)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Duration in milliseconds (computed on finish)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Error detail on failure
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Full error traceback (truncated)
    error_traceback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # JSON payload for task input (e.g., {"video_path": "...", "channel": "..."})
    input_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON payload for task output (e.g., {"video_id": "...", "view_url": "..."})
    output_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # External reference (e.g., YouTube video_id, Instagram media_id, Celery task_id)
    external_ref: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<Job id={self.id} type={self.job_type!r} "
            f"post_id={self.post_id} status={self.status!r} attempt={self.attempt}>"
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled", "dead_letter")

    @property
    def elapsed_seconds(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


# --------------------------------------------------------------------------- #
# RefreshToken — server-side revocable refresh token store                    #
# --------------------------------------------------------------------------- #

class RefreshToken(Base):
    """
    Server-side record for each issued refresh token.

    Enables true logout (invalidate on server) and token rotation
    without requiring Redis. Replaces the previous stateless approach
    where stolen refresh tokens could not be revoked.

    Security properties:
      - token_hash: SHA-256 of the raw token (raw token is never stored)
      - rotation: each use generates a new token and revokes the old one
      - revocation: explicit revoke_all_for_user() on logout/compromise
      - TTL cleanup: expired tokens are pruned periodically
    """
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # SHA-256 hex digest of the raw refresh token — never store raw token
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    # The subject (username) this token grants access to
    username: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # Device/session identifier — for multi-device management
    device_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # Human-readable client hint (e.g., "Chrome on Windows", "iOS App")
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # IP address at issuance
    issued_to_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Lifecycle
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Reason for revocation (logout | rotation | admin | security)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # When was the token last used (for idle timeout detection)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # How many times has this token been used (should be 1 with rotation)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<RefreshToken id={self.id} username={self.username!r} "
            f"revoked={self.is_revoked} expires={self.expires_at}>"
        )

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_expired


# --------------------------------------------------------------------------- #
# AuditLog — append-only admin action trail                                   #
# --------------------------------------------------------------------------- #

class AuditLog(Base):
    """
    Append-only audit trail for security-relevant and admin actions.

    NEVER UPDATE or DELETE rows from this table.
    It is the authoritative, tamper-evident record of:
      - Authentication events (login, logout, failed attempts, token revocation)
      - Post state mutations by admin (manual retries, cancellations, deletions)
      - Configuration changes (channel credentials updated, settings toggled)
      - API key usage anomalies

    Each row is self-contained — no foreign keys (preserves log integrity
    even when referenced rows are deleted).
    """
    __tablename__ = "audit_logs"
    __table_args__ = (
        # Fast timeline queries: all events for a resource
        __import__("sqlalchemy").Index("ix_audit_logs_actor_created_at", "actor", "created_at"),
        __import__("sqlalchemy").Index("ix_audit_logs_event_type_created_at", "event_type", "created_at"),
        __import__("sqlalchemy").Index("ix_audit_logs_resource_created_at", "resource_type", "resource_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Who performed the action (username or "system" for automated actions)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # IP address of the actor (for security reviews)
    actor_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Event classification
    # auth: LOGIN_SUCCESS | LOGIN_FAILURE | LOGOUT | TOKEN_REVOKED | TOKEN_ROTATED
    # post: POST_STATUS_CHANGED | POST_RETRIED | POST_CANCELLED | POST_DELETED
    # config: CHANNEL_UPDATED | SETTING_TOGGLED | CREDS_ROTATED
    # system: WORKER_STARTED | WORKER_STOPPED | MIGRATION_RUN
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Outcome: success | failure | denied
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="success")

    # The resource being acted upon (denormalized for log integrity)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # post | channel | setting
    resource_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)   # str of primary key

    # Human-readable description
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON with structured event details (before/after states, etc.)
    details_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} actor={self.actor!r} "
            f"event={self.event_type!r} outcome={self.outcome!r}>"
        )

