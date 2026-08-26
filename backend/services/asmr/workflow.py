"""
ASMR Content Workflow orchestration service.

Explicit state transitions, idempotency, DRY_RUN mode.

Flow:
  PENDING → SELECTING_FOOD → GENERATING_CONTENT → VALIDATING_CONTENT
  → GENERATING_VIDEO → VIDEO_READY → PUBLISHING → PUBLISHED → NOTIFIED

Failure: ANY → FAILED
Retry:   FAILED → RETRY_PENDING → PENDING
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import SessionLocal
from backend.models import ASMRContentJob, ASMRPublishedContent, ASMRWorkflowRun, FoodItem
from backend.services.asmr.content_generation import ContentGenerationService
from backend.services.asmr.errors import ASMRWorkflowError
from backend.services.asmr.food_selection import seed_food_items, select_next_food
from backend.services.asmr.google_sheets_adapter import GoogleSheetsAdapter
from backend.services.asmr.publisher import Publisher, YouTubePublisher, InstagramPublisher
from backend.services.asmr.seo_service import SEOService
from backend.services.asmr.telegram_notifier import TelegramNotificationService
from backend.services.asmr.video_provider import StubVideoProvider, VideoGenerationProvider

logger = logging.getLogger(__name__)


class ASMRContentWorkflow:
    """
    Orchestrates the full ASMR content pipeline.
    Each method updates the workflow run status explicitly.
    """

    def __init__(
        self,
        video_provider: VideoGenerationProvider | None = None,
        publishers: list[Publisher] | None = None,
    ):
        self._video_provider = video_provider or StubVideoProvider()
        self._publishers = publishers or [YouTubePublisher(), InstagramPublisher()]
        self._telegram = TelegramNotificationService()
        self._sheets = GoogleSheetsAdapter()

    def run(
        self,
        trigger_type: str = "manual",
        dry_run: bool | None = None,
        idempotency_key: str | None = None,
    ) -> ASMRWorkflowRun:
        """
        Execute the full ASMR content workflow.

        Args:
            trigger_type: 'scheduled' or 'manual'
            dry_run: Override config dry_run setting
            idempotency_key: Prevent duplicate runs
        """
        if dry_run is None:
            dry_run = settings.asmr_dry_run

        db = SessionLocal()
        workflow_run: ASMRWorkflowRun | None = None

        try:
            # Create workflow run
            workflow_run = self._create_run(db, trigger_type, dry_run, idempotency_key)
            if workflow_run is None:
                # Duplicate idempotency key — return existing run
                existing = (
                    db.query(ASMRWorkflowRun)
                    .filter(ASMRWorkflowRun.idempotency_key == idempotency_key)
                    .first()
                )
                logger.info("Duplicate idempotency key, returning existing run %s", existing.id if existing else None)
                return existing

            # Ensure food items are seeded
            seed_food_items(db)

            # Stage 1: Select food
            self._update_status(db, workflow_run, "selecting_food")
            food = select_next_food(db)
            workflow_run.food_item_id = food.id
            db.commit()

            # Stage 2: Generate content
            self._update_status(db, workflow_run, "generating_content")
            content_service = ContentGenerationService()
            content = content_service.generate(food.name)

            # Stage 3: Validate content (already done in content_service, but mark state)
            self._update_status(db, workflow_run, "validating_content")

            # Stage 4: Generate video
            self._update_status(db, workflow_run, "generating_video")
            video_result = self._video_provider.generate(content.video_prompt, food.name)

            # Create content job record
            content_job = ASMRContentJob(
                workflow_run_id=workflow_run.id,
                food_item_id=food.id,
                status="completed",
                food_name=food.name,
                video_prompt=content.video_prompt,
                title=content.title,
                caption=content.caption,
                description=content.description,
                tags=json.dumps(content.tags),
                hashtags=json.dumps(content.hashtags),
                video_url=video_result.url,
                video_storage_key=video_result.storage_key,
                video_size_bytes=video_result.size_bytes,
                video_mime_type=video_result.mime_type,
                video_duration_seconds=video_result.duration_seconds,
            )
            db.add(content_job)
            db.commit()
            db.refresh(content_job)

            self._update_status(db, workflow_run, "video_ready")

            # Stage 5: Publish (skip in dry_run)
            if not dry_run:
                self._update_status(db, workflow_run, "publishing")
                for publisher in self._publishers:
                    if not publisher.is_configured():
                        logger.debug("Publisher %s not configured, skipping", publisher.platform_name)
                        continue
                    try:
                        result = publisher.publish(
                            title=content.title,
                            description=content.description,
                            tags=content.tags,
                            video_url=video_result.url,
                        )
                        pub_record = ASMRPublishedContent(
                            content_job_id=content_job.id,
                            platform=result.platform,
                            platform_post_id=result.post_id,
                            published_at=datetime.now(timezone.utc),
                            url=result.url,
                        )
                        db.add(pub_record)
                        db.commit()
                    except Exception as exc:
                        logger.error("Publisher %s failed: %s", publisher.platform_name, exc)

                final_status = "published"
            else:
                final_status = "dry_run_complete"

            self._update_status(db, workflow_run, final_status)

            # Stage 6: Sync to Google Sheets (non-critical)
            try:
                self._sheets.sync_content_result(
                    food_item=food.name,
                    caption=content.caption,
                    title=content.title,
                )
            except Exception as exc:
                logger.warning("Sheets sync failed (non-critical): %s", exc)

            # Stage 7: Send notification
            try:
                if dry_run:
                    self._telegram.notify_dry_run(food.name, content.title)
                else:
                    self._telegram.notify_success(food.name, content.title, video_result.url)
                if not dry_run:
                    self._update_status(db, workflow_run, "notified")
            except Exception as exc:
                logger.warning("Telegram notification failed (non-critical): %s", exc)

            workflow_run.completed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(workflow_run)

            logger.info(
                "ASMR workflow complete: run_id=%d food=%s title=%s status=%s",
                workflow_run.id, food.name, content.title, workflow_run.status,
            )
            return workflow_run

        except ASMRWorkflowError as exc:
            logger.error("ASMR workflow error: %s (retryable=%s)", exc, exc.retryable)
            if workflow_run:
                self._update_status(db, workflow_run, "failed", str(exc))
                try:
                    self._telegram.notify_failure(workflow_run.id, str(exc))
                except Exception:
                    pass
            raise

        except Exception as exc:
            logger.exception("Unexpected ASMR workflow error")
            if workflow_run:
                self._update_status(db, workflow_run, "failed", str(exc))
                try:
                    self._telegram.notify_failure(workflow_run.id, str(exc))
                except Exception:
                    pass
            raise

        finally:
            db.close()

    def _create_run(
        self,
        db: Session,
        trigger_type: str,
        dry_run: bool,
        idempotency_key: str | None,
    ) -> ASMRWorkflowRun | None:
        """Create a new workflow run. Returns None if idempotency key already exists."""
        run = ASMRWorkflowRun(
            trigger_type=trigger_type,
            status="pending",
            dry_run=dry_run,
            idempotency_key=idempotency_key or f"asmr-{uuid.uuid4().hex}",
        )
        db.add(run)
        try:
            db.commit()
            db.refresh(run)
            logger.info("Workflow run created: id=%d trigger=%s dry_run=%s", run.id, trigger_type, dry_run)
            return run
        except IntegrityError:
            db.rollback()
            return None

    @staticmethod
    def _update_status(
        db: Session,
        run: ASMRWorkflowRun,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update workflow run status with timestamp."""
        run.status = status
        run.error_message = error_message
        run.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Workflow run %d: status → %s", run.id, status)


def retry_workflow_run(run_id: int) -> ASMRWorkflowRun:
    """
    Retry a failed workflow run.
    Creates a new run with the same trigger type.
    """
    db = SessionLocal()
    try:
        run = db.get(ASMRWorkflowRun, run_id)
        if not run:
            raise ValueError(f"Workflow run not found: {run_id}")
        if run.status != "failed":
            raise ValueError(f"Can only retry failed runs (current: {run.status})")

        workflow = ASMRContentWorkflow()
        return workflow.run(
            trigger_type=run.trigger_type,
            dry_run=run.dry_run,
        )
    finally:
        db.close()
