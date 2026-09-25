"""
Regression tests for:
1. GeminiService initialization without AttributeError under google-genai SDK.
2. ensure_video_file_on_disk restoring missing files from Google Drive.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from backend.services.gemini_service import GeminiService
from backend.services.watermark import ensure_video_file_on_disk


def test_gemini_service_init_does_not_crash():
    """Verify GeminiService can be initialized with an api_key without throwing AttributeError."""
    with patch("backend.services.gemini_service.settings") as mock_settings:
        mock_settings.gemini_api_key = "test_key"
        mock_settings.gemini_model = "models/gemini-2.5-flash"
        svc = GeminiService(api_key="test_key")
        assert svc._api_key == "test_key"


def test_ensure_video_file_on_disk_exists(tmp_path):
    """When file already exists locally, ensure_video_file_on_disk returns it immediately."""
    fake_video = tmp_path / "existing.mp4"
    fake_video.write_bytes(b"test video data")

    result = ensure_video_file_on_disk(str(fake_video), is_clean=False)
    assert result == fake_video


def test_ensure_video_file_on_disk_restores_from_drive(tmp_path):
    """When file is missing locally but drive_file_id is provided, it downloads from storage."""
    missing_video = tmp_path / "missing.mp4"
    assert not missing_video.exists()

    with patch("backend.services.storage.get_storage") as mock_get_storage:
        mock_storage = MagicMock()

        def fake_download(file_id, dest, channel=None):
            dest.write_bytes(b"downloaded from drive")
            return dest

        mock_storage.download.side_effect = fake_download
        mock_get_storage.return_value = mock_storage

        result = ensure_video_file_on_disk(
            str(missing_video),
            is_clean=False,
            drive_file_id="fake_drive_id_123",
            channel="the_indian_kitchen",
        )

        assert result is not None
        assert result.exists()
        assert result.read_bytes() == b"downloaded from drive"
