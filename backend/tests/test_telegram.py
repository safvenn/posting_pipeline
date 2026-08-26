"""Unit tests for Telegram notification service (mocked HTTP)."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from unittest.mock import MagicMock, patch

from backend.services.asmr.telegram_notifier import TelegramNotificationService
from backend.services.asmr.errors import TelegramError


@pytest.fixture
def telegram():
    return TelegramNotificationService(bot_token="test-token", chat_id="12345")


@pytest.fixture
def unconfigured_telegram():
    return TelegramNotificationService(bot_token="", chat_id="")


# ---- Configuration -------------------------------------------------------- #

def test_is_configured(telegram):
    assert telegram.is_configured is True

def test_not_configured(unconfigured_telegram):
    assert unconfigured_telegram.is_configured is False


# ---- Success notification ------------------------------------------------- #

@patch("backend.services.asmr.telegram_notifier.httpx.Client")
def test_notify_success_sends_correct_message(mock_client_class, telegram):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_class.return_value = mock_client

    telegram.notify_success("samosa", "Miniature Samosa ASMR", "https://video.url")

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    payload = call_args[1]["json"]
    assert "samosa" in payload["text"]
    assert "Miniature Samosa ASMR" in payload["text"]
    assert "https://video.url" in payload["text"]
    assert payload["chat_id"] == "12345"


# ---- Failure notification ------------------------------------------------- #

@patch("backend.services.asmr.telegram_notifier.httpx.Client")
def test_notify_failure_sends_error(mock_client_class, telegram):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_class.return_value = mock_client

    telegram.notify_failure(42, "Gemini API timeout")

    mock_client.post.assert_called_once()
    payload = mock_client.post.call_args[1]["json"]
    assert "42" in payload["text"]
    assert "Gemini API timeout" in payload["text"]
    assert "❌" in payload["text"]


# ---- Unconfigured skips silently ------------------------------------------ #

def test_unconfigured_skips_success(unconfigured_telegram):
    # Should not raise
    unconfigured_telegram.notify_success("samosa", "title")

def test_unconfigured_skips_failure(unconfigured_telegram):
    unconfigured_telegram.notify_failure(1, "error")


# ---- Error truncation ----------------------------------------------------- #

@patch("backend.services.asmr.telegram_notifier.httpx.Client")
def test_long_error_truncated(mock_client_class, telegram):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_class.return_value = mock_client

    long_error = "x" * 1000
    telegram.notify_failure(1, long_error)

    payload = mock_client.post.call_args[1]["json"]
    # Error should be truncated to 500 chars
    assert len(payload["text"]) < 700
