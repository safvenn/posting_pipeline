"""Typed error hierarchy for the ASMR content workflow."""
from __future__ import annotations


class ASMRWorkflowError(Exception):
    """Base error for all ASMR workflow failures."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class DuplicateFoodError(ASMRWorkflowError):
    """Raised when a food item is already used in the current cycle."""

    def __init__(self, food_name: str):
        super().__init__(f"Food item already used: {food_name}", retryable=False)
        self.food_name = food_name


class NoFoodAvailableError(ASMRWorkflowError):
    """Raised when all food items have been used and cycle reset fails."""

    def __init__(self):
        super().__init__("No food items available (all used, cycle reset failed)", retryable=False)


class GeminiAPIError(ASMRWorkflowError):
    """Raised on Gemini API call failure."""

    def __init__(self, message: str, *, status_code: int | None = None):
        retryable = status_code in (429, 500, 502, 503, 504) if status_code else False
        super().__init__(f"Gemini API error: {message}", retryable=retryable)
        self.status_code = status_code


class ContentValidationError(ASMRWorkflowError):
    """Raised when AI-generated content fails validation."""

    def __init__(self, field: str, reason: str):
        super().__init__(f"Content validation failed: {field} — {reason}", retryable=True)
        self.field = field
        self.reason = reason


class VideoGenerationError(ASMRWorkflowError):
    """Raised on video generation failure."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(f"Video generation error: {message}", retryable=retryable)


class UploadError(ASMRWorkflowError):
    """Raised on video upload failure."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(f"Upload error: {message}", retryable=retryable)


class PublishingError(ASMRWorkflowError):
    """Raised on social media publishing failure."""

    def __init__(self, platform: str, message: str, *, retryable: bool = True):
        super().__init__(f"Publishing error ({platform}): {message}", retryable=retryable)
        self.platform = platform


class TelegramError(ASMRWorkflowError):
    """Raised on Telegram notification failure."""

    def __init__(self, message: str):
        super().__init__(f"Telegram error: {message}", retryable=True)


class GoogleSheetsError(ASMRWorkflowError):
    """Raised on Google Sheets sync failure."""

    def __init__(self, message: str):
        super().__init__(f"Google Sheets error: {message}", retryable=True)
