"""
Storage abstraction layer.

StorageService is a Protocol so the implementation can be swapped later
(e.g. S3-compatible provider) without touching business logic.

Current implementation: GoogleDriveStorage — uploads to a configured Drive folder
using the existing service-account credentials in settings.google_sheets_service_account_json.

Usage:
    from backend.services.storage import get_storage
    storage = get_storage()
    file_ref = storage.upload(local_path, dest_name="video.mp4")
    storage.delete(file_ref)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol

from backend.config import settings

logger = logging.getLogger(__name__)

# Drive API scopes needed for file upload
_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]


class StorageService(Protocol):
    """Abstract storage interface — upload, delete, get reference."""

    def upload(
        self,
        local_path: Path,
        dest_name: str,
        folder_id: str | None = None,
    ) -> str:
        """Upload file; return an opaque file reference (Drive file ID, S3 key, etc.)."""
        ...

    def delete(self, file_ref: str) -> None:
        """Delete the file identified by file_ref. Best-effort — no exception on 404."""
        ...

    def get_download_url(self, file_ref: str) -> str:
        """Return a shareable download URL for the file reference."""
        ...


class GoogleDriveStorage:
    """
    StorageService backed by Google Drive.

    Credentials come from the same service-account JSON used by gspread
    (settings.google_sheets_service_account_json).  The service account must
    have at least 'Editor' access on the target folder.
    """

    def __init__(self) -> None:
        self._service = None  # lazy-init

    def _get_service(self):
        if self._service is not None:
            return self._service

        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        sa_val = settings.google_sheets_service_account_json.strip()
        if sa_val.startswith("{"):
            info = json.loads(sa_val)
            creds = Credentials.from_service_account_info(info, scopes=_DRIVE_SCOPES)
        else:
            creds = Credentials.from_service_account_file(sa_val, scopes=_DRIVE_SCOPES)

        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def upload(
        self,
        local_path: Path,
        dest_name: str,
        folder_id: str | None = None,
    ) -> str:
        """
        Upload local_path to Google Drive.
        Returns the Drive file ID on success.
        Raises on any Drive API error (let caller handle retry).
        """
        from googleapiclient.http import MediaFileUpload

        service = self._get_service()

        file_metadata: dict = {"name": dest_name}
        target_folder = folder_id or settings.google_drive_indian_kitchen_folder_id
        if target_folder:
            file_metadata["parents"] = [target_folder]

        media = MediaFileUpload(
            str(local_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10 MB chunks
        )

        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id,name,size",
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.debug("Drive upload %s: %d%% complete", dest_name, pct)

        file_id: str = response.get("id", "")
        if not file_id:
            raise RuntimeError(f"Drive upload returned no file ID for {dest_name}")

        logger.info(
            "Drive upload complete: file=%s id=%s folder=%s",
            dest_name, file_id, target_folder or "(root)",
        )
        return file_id

    def delete(self, file_ref: str) -> None:
        """Delete a Drive file by ID. Silently ignores 404 (already deleted)."""
        try:
            service = self._get_service()
            service.files().delete(fileId=file_ref).execute()
            logger.info("Drive delete: file_id=%s", file_ref)
        except Exception as exc:
            # Don't propagate — deletion is best-effort cleanup
            logger.warning("Drive delete failed for %s: %s", file_ref, exc)

    def get_download_url(self, file_ref: str) -> str:
        """Return a direct Drive download link (requires shared access for external use)."""
        return f"https://drive.google.com/uc?id={file_ref}&export=download"


# Module-level singleton — created once per process
_storage_instance: GoogleDriveStorage | None = None


def get_storage() -> GoogleDriveStorage:
    """Return the module-level GoogleDriveStorage singleton."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = GoogleDriveStorage()
    return _storage_instance


def upload_post_to_drive(post_id: int) -> bool:
    """Upload original video of post to Google Drive and update DB.
    
    Can be run as a FastAPI BackgroundTask or called directly during ingest.
    """
    from datetime import datetime, timezone
    from backend.database import SessionLocal
    from backend.models import Post
    from backend.services.workflow_logger import (
        wlog, DRIVE_UPLOAD_STARTED, DRIVE_UPLOAD_COMPLETED, DRIVE_UPLOAD_FAILED
    )
    from backend.services.retry import is_permanent_error, schedule_retry

    with SessionLocal() as db:
        post = db.get(Post, post_id)
        if not post:
            logger.warning("upload_post_to_drive: Post %s not found", post_id)
            return False

        if post.drive_upload_status == "completed":
            return True

        folder_id = settings.google_drive_indian_kitchen_folder_id
        if not folder_id:
            logger.warning(
                "post_id=%s GOOGLE_DRIVE_INDIAN_KITCHEN_FOLDER_ID not set — skipping Drive upload",
                post_id,
            )
            post.drive_upload_status = "completed"
            db.commit()
            return True

        video_path = Path(post.video_path)
        if not video_path.exists():
            logger.error("post_id=%s Drive upload skipped: video file missing %s", post_id, video_path)
            post.drive_upload_status = "failed"
            post.last_error = f"Video file missing at {video_path}"
            db.commit()
            return False

        post.drive_upload_status = "pending"
        post.updated_at = datetime.now(timezone.utc)
        db.commit()

        try:
            dest_name = f"post_{post.id}_{video_path.name}"
            wlog(db, post_id=post.id, event_type=DRIVE_UPLOAD_STARTED, status="info",
                 message=f"Uploading {dest_name} to Drive folder {folder_id}")

            storage = get_storage()
            file_id = storage.upload(video_path, dest_name=dest_name, folder_id=folder_id)

            post.drive_file_id = file_id
            post.drive_upload_status = "completed"
            post.updated_at = datetime.now(timezone.utc)
            db.commit()

            wlog(db, post_id=post.id, event_type=DRIVE_UPLOAD_COMPLETED, status="success",
                 drive_file_id=file_id, message=f"Drive upload complete: {dest_name}")
            logger.info("post_id=%s Drive upload done drive_file_id=%s", post.id, file_id)
            return True

        except Exception as exc:
            err = str(exc)
            logger.exception("post_id=%s Drive upload failed: %s", post.id, err)
            wlog(db, post_id=post.id, event_type=DRIVE_UPLOAD_FAILED, status="failure",
                 message=err[:500], attempt=post.retry_count + 1)

            if is_permanent_error(exc):
                logger.error("post_id=%s Drive upload permanent error: %s", post.id, err)
                post.drive_upload_status = "failed"
                post.last_error = err[:2000]
                post.updated_at = datetime.now(timezone.utc)
                db.commit()
                return False

            schedule_retry(post, db, err)
            return False
