"""
Idempotency service — prevents duplicate external side effects.

CRITICAL for preventing duplicate YouTube/Instagram publishing after:
  - process crash mid-upload
  - network timeout after provider accepts request
  - worker restart
  - database timeout
  - lost API response

Usage
-----
    from backend.services.idempotency import IdempotencyService, IdempotencyStatus

    svc = IdempotencyService(db)

    # Before calling YouTube:
    entry = svc.get_or_create("youtube:post:182:publish")

    if entry.status == IdempotencyStatus.SUCCEEDED:
        # Already done — return stored result
        return entry.result_data

    # ... call YouTube API ...

    # On success:
    svc.mark_succeeded(
        "youtube:post:182:publish",
        external_id=video_id,
        result_data={"video_id": video_id},
    )

    # On failure:
    svc.mark_failed("youtube:post:182:publish", error=str(exc))
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# How long to retain idempotency records (7 days)
IDEMPOTENCY_TTL_DAYS = 7


class IdempotencyStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class IdempotencyEntry:
    """In-memory representation of an idempotency record."""

    def __init__(
        self,
        key: str,
        status: IdempotencyStatus,
        external_id: Optional[str] = None,
        result_data: Optional[dict] = None,
        error: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> None:
        self.key = key
        self.status = status
        self.external_id = external_id
        self.result_data = result_data or {}
        self.error = error
        self.created_at = created_at or datetime.now(timezone.utc)

    @property
    def already_succeeded(self) -> bool:
        return self.status == IdempotencyStatus.SUCCEEDED

    @property
    def already_failed(self) -> bool:
        return self.status == IdempotencyStatus.FAILED


def _make_key(operation: str, resource_type: str, resource_id: Any, suffix: str = "") -> str:
    """
    Create a namespaced idempotency key.

    Examples:
        _make_key("publish", "youtube", 182) → "youtube:post:182:publish"
        _make_key("publish", "instagram", 182) → "instagram:post:182:publish"
        _make_key("update", "sheet", "row-42") → "sheet:post:row-42:update"
    """
    parts = [resource_type, "post", str(resource_id), operation]
    if suffix:
        parts.append(suffix)
    return ":".join(parts)


def youtube_publish_key(post_id: int) -> str:
    return _make_key("publish", "youtube", post_id)


def instagram_container_key(post_id: int) -> str:
    return _make_key("container_create", "instagram", post_id)


def instagram_publish_key(post_id: int) -> str:
    return _make_key("publish", "instagram", post_id)


def sheet_update_key(post_id: int) -> str:
    return _make_key("update", "sheet", post_id)


def drive_archive_key(post_id: int, variant: str = "original") -> str:
    return _make_key(f"archive_{variant}", "drive", post_id)


class IdempotencyService:
    """
    Database-backed idempotency tracking.

    Uses the PostIdempotencyRecord model (imported lazily to avoid circular
    imports at module level).
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def _get_model(self):
        from backend.models import PostIdempotencyRecord
        return PostIdempotencyRecord

    def get(self, key: str) -> Optional[IdempotencyEntry]:
        """Return existing idempotency record or None."""
        model = self._get_model()
        record = self._db.query(model).filter(model.key == key).first()
        if record is None:
            return None
        return IdempotencyEntry(
            key=record.key,
            status=IdempotencyStatus(record.status),
            external_id=record.external_id,
            result_data=json.loads(record.result_json) if record.result_json else {},
            error=record.error_message,
            created_at=record.created_at,
        )

    def get_or_create(self, key: str) -> IdempotencyEntry:
        """
        Get existing record or create a new PENDING one.
        This is the main entry point before any external API call.
        """
        existing = self.get(key)
        if existing is not None:
            if existing.already_succeeded:
                logger.info(
                    "idempotency: key=%r already succeeded external_id=%s — skipping",
                    key, existing.external_id,
                )
            elif existing.already_failed:
                logger.warning(
                    "idempotency: key=%r previously failed — will re-attempt",
                    key,
                )
            return existing

        # Create new PENDING record
        model = self._get_model()
        record = model(
            key=key,
            status=IdempotencyStatus.PENDING.value,
            expires_at=datetime.now(timezone.utc) + timedelta(days=IDEMPOTENCY_TTL_DAYS),
        )
        self._db.add(record)
        try:
            self._db.commit()
        except Exception:
            self._db.rollback()
            # Race condition: another worker just created it — fetch theirs
            existing = self.get(key)
            if existing:
                return existing
            raise
        return IdempotencyEntry(key=key, status=IdempotencyStatus.PENDING)

    def mark_succeeded(
        self,
        key: str,
        external_id: Optional[str] = None,
        result_data: Optional[dict] = None,
    ) -> None:
        """Persist a successful outcome for this operation."""
        model = self._get_model()
        record = self._db.query(model).filter(model.key == key).first()
        if record is None:
            logger.warning("idempotency: mark_succeeded called for unknown key=%r", key)
            return
        record.status = IdempotencyStatus.SUCCEEDED.value
        record.external_id = external_id
        record.result_json = json.dumps(result_data or {})
        record.processed_at = datetime.now(timezone.utc)
        try:
            self._db.commit()
            logger.info(
                "idempotency: key=%r succeeded external_id=%s",
                key, external_id,
            )
        except Exception as exc:
            self._db.rollback()
            logger.error("idempotency: failed to persist success for key=%r: %s", key, exc)

    def mark_failed(self, key: str, error: str) -> None:
        """Persist a failed outcome — allows retry on next attempt."""
        model = self._get_model()
        record = self._db.query(model).filter(model.key == key).first()
        if record is None:
            logger.warning("idempotency: mark_failed called for unknown key=%r", key)
            return
        record.status = IdempotencyStatus.FAILED.value
        record.error_message = error[:2000]
        record.processed_at = datetime.now(timezone.utc)
        try:
            self._db.commit()
        except Exception as exc:
            self._db.rollback()
            logger.error("idempotency: failed to persist failure for key=%r: %s", key, exc)

    def reset(self, key: str) -> None:
        """Reset a failed/pending record to allow re-processing."""
        model = self._get_model()
        record = self._db.query(model).filter(model.key == key).first()
        if record is None:
            return
        record.status = IdempotencyStatus.PENDING.value
        record.error_message = None
        record.external_id = None
        record.result_json = None
        record.processed_at = None
        try:
            self._db.commit()
        except Exception:
            self._db.rollback()

    def cleanup_expired(self) -> int:
        """Delete expired idempotency records. Returns count deleted."""
        model = self._get_model()
        now = datetime.now(timezone.utc)
        expired = (
            self._db.query(model)
            .filter(model.expires_at < now)
            .all()
        )
        for record in expired:
            self._db.delete(record)
        try:
            self._db.commit()
            if expired:
                logger.info("idempotency: cleaned up %d expired records", len(expired))
            return len(expired)
        except Exception:
            self._db.rollback()
            return 0
