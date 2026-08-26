"""
Telegram notification service for ASMR workflow.

Sends success/failure notifications via Telegram Bot API.
Non-critical — failures are logged but never block the workflow.
"""
from __future__ import annotations

import logging

import httpx

from backend.config import settings
from backend.services.asmr.errors import TelegramError

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramNotificationService:
    """Send ASMR workflow notifications via Telegram."""

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ):
        self._bot_token = bot_token or settings.telegram_bot_token
        self._chat_id = chat_id or settings.telegram_chat_id

    @property
    def is_configured(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    def notify_success(self, dish: str, title: str, video_url: str | None = None) -> None:
        """Send success notification. Mirrors n8n Telegram node output."""
        if not self.is_configured:
            logger.debug("Telegram not configured, skipping success notification")
            return

        video_line = f"\nVideo: {video_url}" if video_url else ""
        text = (
            f"✅ New ASMR Short published!\n"
            f"Dish: {dish}\n"
            f"Title: {title}"
            f"{video_line}"
        )
        self._send_message(text)

    def notify_failure(self, run_id: int, error: str) -> None:
        """Send failure notification."""
        if not self.is_configured:
            logger.debug("Telegram not configured, skipping failure notification")
            return

        # Truncate error to avoid Telegram message limit
        error_truncated = error[:500] if len(error) > 500 else error
        text = (
            f"❌ ASMR Workflow Failed\n"
            f"Run ID: {run_id}\n"
            f"Error: {error_truncated}"
        )
        self._send_message(text)

    def notify_dry_run(self, dish: str, title: str) -> None:
        """Send dry-run notification."""
        if not self.is_configured:
            return

        text = (
            f"🧪 ASMR Dry Run Complete\n"
            f"Dish: {dish}\n"
            f"Title: {title}\n"
            f"(No publish — dry run mode)"
        )
        self._send_message(text)

    def _send_message(self, text: str) -> None:
        """Send a message via Telegram Bot API."""
        url = f"{TELEGRAM_API_BASE}/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
            logger.info("Telegram notification sent (chat_id=%s)", self._chat_id)
        except httpx.HTTPStatusError as exc:
            logger.error("Telegram API error: %s %s", exc.response.status_code, exc.response.text[:200])
            raise TelegramError(f"HTTP {exc.response.status_code}: {exc.response.text[:200]}") from exc
        except httpx.RequestError as exc:
            logger.error("Telegram request error: %s", exc)
            raise TelegramError(str(exc)) from exc
