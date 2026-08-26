"""
Dedicated Gemini provider service — shared across all workflows.

Responsibilities:
  - Model configuration
  - Prompt construction
  - API calls with timeout + retries
  - Structured output parsing
  - Error handling with typed errors
  - Usage logging
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from backend.config import settings
from backend.services.asmr.errors import GeminiAPIError

logger = logging.getLogger(__name__)

# Max retries for transient failures
MAX_RETRIES = 2
RETRY_DELAY_BASE = 2  # seconds, exponential backoff


class GeminiService:
    """Centralized Gemini API client with retry, parsing, and error handling."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
    ):
        self._api_key = api_key or settings.gemini_api_key
        self._model_name = model_name or settings.gemini_model
        if not self._api_key:
            raise GeminiAPIError("GEMINI_API_KEY not configured", status_code=None)
        genai.configure(api_key=self._api_key)

    def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
    ) -> str:
        """
        Call Gemini and return raw text response.
        Retries on transient failures with exponential backoff.
        """
        model = genai.GenerativeModel(
            model_name=self._model_name,
            system_instruction=system_instruction,
        )

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 2):  # 1-indexed, MAX_RETRIES + 1 total attempts
            try:
                start = time.monotonic()
                response = model.generate_content(prompt)
                elapsed = time.monotonic() - start
                logger.info(
                    "Gemini call: model=%s attempt=%d elapsed=%.2fs",
                    self._model_name, attempt, elapsed,
                )
                return response.text

            except google_exceptions.ResourceExhausted as exc:
                last_error = exc
                logger.warning("Gemini rate limit (attempt %d): %s", attempt, exc)
                if attempt <= MAX_RETRIES:
                    delay = RETRY_DELAY_BASE ** attempt
                    time.sleep(delay)
                continue

            except google_exceptions.ServiceUnavailable as exc:
                last_error = exc
                logger.warning("Gemini unavailable (attempt %d): %s", attempt, exc)
                if attempt <= MAX_RETRIES:
                    delay = RETRY_DELAY_BASE ** attempt
                    time.sleep(delay)
                continue

            except google_exceptions.InvalidArgument as exc:
                raise GeminiAPIError(str(exc), status_code=400) from exc

            except Exception as exc:
                raise GeminiAPIError(str(exc)) from exc

        raise GeminiAPIError(f"All {MAX_RETRIES + 1} attempts failed: {last_error}", status_code=429)

    def generate_json(
        self,
        prompt: str,
        system_instruction: str | None = None,
    ) -> dict[str, Any]:
        """
        Call Gemini and parse response as JSON.
        Strips markdown code fences if model adds them.
        """
        raw = self.generate_text(prompt, system_instruction)
        return self.parse_json_response(raw)

    @staticmethod
    def parse_json_response(raw: str) -> dict[str, Any]:
        """
        Parse Gemini text output as JSON.
        Strips markdown fences, handles common formatting issues.
        """
        text = raw.strip()
        # Strip ```json ... ``` or ``` ... ``` fences
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiAPIError(
                f"Invalid JSON from Gemini: {exc}. Raw (first 500 chars): {text[:500]}"
            ) from exc
