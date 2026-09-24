"""
Unit tests for email_notifier service and cookie expiry notification.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from backend.services.email_notifier import (
    get_smtp_config,
    is_email_configured,
    notify_cookies_expired,
    send_email,
)


def test_is_email_configured_false_when_empty(monkeypatch):
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("NOTIFICATION_EMAIL_TO", raising=False)
    assert not is_email_configured()


def test_is_email_configured_true(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "sender@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("NOTIFICATION_EMAIL_TO", "recipient@gmail.com")
    assert is_email_configured()


def test_get_smtp_config_defaults(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PORT", raising=False)
    monkeypatch.setenv("SMTP_USER", "test@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "pass123")
    monkeypatch.delenv("NOTIFICATION_EMAIL_TO", raising=False)

    cfg = get_smtp_config()
    assert cfg["host"] == "smtp.gmail.com"
    assert cfg["port"] == 587
    assert cfg["user"] == "test@gmail.com"
    # When recipient not set, defaults to user
    assert cfg["recipient"] == "test@gmail.com"


def test_send_email_skips_when_not_configured(monkeypatch):
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    result = send_email(subject="Test", text_content="Test body")
    assert result is False


@patch("smtplib.SMTP")
def test_send_email_starttls_success(mock_smtp_cls, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "sender@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pass")
    monkeypatch.setenv("NOTIFICATION_EMAIL_TO", "user@gmail.com")

    mock_server = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_server

    ok = send_email(
        subject="Alert Test",
        text_content="Plain text content",
        html_content="<p>HTML content</p>",
    )
    assert ok is True
    mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=20)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("sender@gmail.com", "app-pass")
    mock_server.send_message.assert_called_once()


@patch("smtplib.SMTP_SSL")
def test_send_email_ssl_success(mock_smtp_ssl_cls, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "sender@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pass")
    monkeypatch.setenv("NOTIFICATION_EMAIL_TO", "user@gmail.com")

    mock_server = MagicMock()
    mock_smtp_ssl_cls.return_value.__enter__.return_value = mock_server

    ok = send_email(
        subject="Alert SSL Test",
        text_content="Plain text content",
    )
    assert ok is True
    mock_smtp_ssl_cls.assert_called_once_with("smtp.gmail.com", 465, timeout=20)
    mock_server.login.assert_called_once_with("sender@gmail.com", "app-pass")
    mock_server.send_message.assert_called_once()


@patch("backend.services.email_notifier.send_email")
def test_notify_cookies_expired(mock_send):
    mock_send.return_value = True
    ok = notify_cookies_expired(
        channel="the_indian_kitchen",
        row_id=71,
        details="Session redirected to flow.google.com/about",
    )
    assert ok is True
    mock_send.assert_called_once()
    subject = mock_send.call_args.kwargs["subject"]
    text = mock_send.call_args.kwargs["text_content"]
    html = mock_send.call_args.kwargs["html_content"]

    assert "Google Flow Cookies Expired" in subject
    assert "#71" in subject
    assert "python export_cookies.py" in text
    assert "python export_cookies.py" in html
    assert "the_indian_kitchen" in text
