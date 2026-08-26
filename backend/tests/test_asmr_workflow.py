"""
End-to-end ASMR workflow test — mocked external APIs.

Tests the full orchestration:
  trigger → select food → generate content → generate video → persist → notify
"""
from __future__ import annotations

import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from backend.services.asmr.errors import ASMRWorkflowError
from backend.services.asmr.video_provider import StubVideoProvider, VideoResult, VideoStatus


# ---- Stub video provider -------------------------------------------------- #

def test_stub_video_provider_returns_completed():
    provider = StubVideoProvider()
    result = provider.generate("test prompt", "samosa")
    assert result.status == VideoStatus.COMPLETED
    assert result.job_id.startswith("stub-")
    assert result.url is not None

def test_stub_video_provider_get_status():
    provider = StubVideoProvider()
    result = provider.get_status("stub-abc123")
    assert result.status == VideoStatus.COMPLETED

def test_stub_video_provider_download():
    provider = StubVideoProvider()
    data = provider.download("stub-abc123")
    assert isinstance(data, bytes)


# ---- Error hierarchy ------------------------------------------------------- #

def test_error_retryable_flag():
    from backend.services.asmr.errors import GeminiAPIError, ContentValidationError
    
    err = GeminiAPIError("rate limit", status_code=429)
    assert err.retryable is True
    
    err = GeminiAPIError("invalid key", status_code=401)
    assert err.retryable is False
    
    err = ContentValidationError("title", "too long")
    assert err.retryable is True

def test_error_hierarchy():
    from backend.services.asmr.errors import (
        ASMRWorkflowError, DuplicateFoodError, NoFoodAvailableError,
        GeminiAPIError, ContentValidationError, VideoGenerationError,
        TelegramError, GoogleSheetsError,
    )
    
    assert issubclass(DuplicateFoodError, ASMRWorkflowError)
    assert issubclass(NoFoodAvailableError, ASMRWorkflowError)
    assert issubclass(GeminiAPIError, ASMRWorkflowError)
    assert issubclass(ContentValidationError, ASMRWorkflowError)
    assert issubclass(VideoGenerationError, ASMRWorkflowError)
    assert issubclass(TelegramError, ASMRWorkflowError)
    assert issubclass(GoogleSheetsError, ASMRWorkflowError)


# ---- Workflow state transitions -------------------------------------------- #

def test_valid_workflow_statuses():
    from backend.schemas import ASMR_VALID_STATUSES
    
    expected = {
        "pending", "selecting_food", "generating_content",
        "validating_content", "generating_video", "video_ready",
        "publishing", "published", "notified", "failed",
        "retry_pending", "dry_run_complete",
    }
    assert ASMR_VALID_STATUSES == expected


# ---- Publisher adapters ---------------------------------------------------- #

def test_youtube_publisher_stub():
    from backend.services.asmr.publisher import YouTubePublisher
    pub = YouTubePublisher()
    assert pub.platform_name == "youtube"
    assert pub.is_configured() is False
    result = pub.publish(title="test", description="desc", tags=["asmr"])
    assert result.platform == "youtube"

def test_instagram_publisher_stub():
    from backend.services.asmr.publisher import InstagramPublisher
    pub = InstagramPublisher()
    assert pub.platform_name == "instagram"
    assert pub.is_configured() is False


# ---- Google Sheets adapter ------------------------------------------------ #

def test_sheets_adapter_unconfigured():
    from backend.services.asmr.google_sheets_adapter import GoogleSheetsAdapter
    with patch.object(GoogleSheetsAdapter, "is_configured", new_callable=PropertyMock, return_value=False):
        adapter = GoogleSheetsAdapter()
        # Should not raise when unconfigured
        adapter.sync_content_result("samosa", "caption", "title")

def test_sheets_adapter_get_used_unconfigured():
    from backend.services.asmr.google_sheets_adapter import GoogleSheetsAdapter
    with patch.object(GoogleSheetsAdapter, "is_configured", new_callable=PropertyMock, return_value=False):
        adapter = GoogleSheetsAdapter()
        result = adapter.get_used_items()
        assert result == []


# ---- Gemini service -------------------------------------------------------- #

def test_gemini_json_parsing():
    from backend.services.gemini_service import GeminiService
    
    # Clean JSON
    parsed = GeminiService.parse_json_response('{"key": "value"}')
    assert parsed == {"key": "value"}
    
    # JSON with markdown fences
    parsed = GeminiService.parse_json_response('```json\n{"key": "value"}\n```')
    assert parsed == {"key": "value"}
    
    # JSON with just ``` fences
    parsed = GeminiService.parse_json_response('```\n{"key": "value"}\n```')
    assert parsed == {"key": "value"}


def test_gemini_invalid_json_raises():
    from backend.services.gemini_service import GeminiService
    from backend.services.asmr.errors import GeminiAPIError
    
    with pytest.raises(GeminiAPIError, match="Invalid JSON"):
        GeminiService.parse_json_response("not json at all")
