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
