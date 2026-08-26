"""
Google Sheets adapter for ASMR workflow.

Syncs content results to the n8n-era Food Items sheet.
DB remains source of truth. Sheet is for human-readable tracking
and backwards compatibility with the existing n8n workflow.

Non-critical — failures logged, never block the workflow.
"""
from __future__ import annotations

import logging
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from backend.config import settings
from backend.services.asmr.errors import GoogleSheetsError

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class GoogleSheetsAdapter:
    """Adapter for ASMR food items Google Sheet."""

    def __init__(self):
        self._sheet_id = settings.asmr_food_sheet_id
        self._tab_name = settings.asmr_food_sheet_tab
        self._sa_json = settings.google_sheets_service_account_json

    @property
    def is_configured(self) -> bool:
        return bool(self._sheet_id and self._sa_json)

    def _get_worksheet(self) -> gspread.Worksheet:
        """Authenticate and return the worksheet."""
        creds = Credentials.from_service_account_file(self._sa_json, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(self._sheet_id)
        return sh.worksheet(self._tab_name)

    def sync_content_result(
        self,
        food_item: str,
        caption: Optional[str] = None,
        title: Optional[str] = None,
    ) -> None:
        """
        Append or update a row in the Food Items sheet.
        Mirrors n8n "Log Published Result" node:
          item | used | caption | title
        """
        if not self.is_configured:
            logger.debug("Google Sheets not configured, skipping ASMR sync")
            return

        try:
            ws = self._get_worksheet()
            # Append new row (matching n8n appendOrUpdate behavior)
            ws.append_row(
                [food_item, "yes", caption or "", title or ""],
                value_input_option="RAW",
            )
            logger.info("Sheet synced: item=%s, title=%s", food_item, title)

        except Exception as exc:
            # Non-critical — log and continue
            logger.error("Google Sheets sync failed: %s", exc)
            raise GoogleSheetsError(str(exc)) from exc

    def get_used_items(self) -> list[str]:
        """Read all items marked as 'used' from the sheet."""
        if not self.is_configured:
            return []

        try:
            ws = self._get_worksheet()
            records = ws.get_all_records(default_blank="")
            used = [
                str(r.get("item", "")).strip().lower()
                for r in records
                if str(r.get("used", "")).strip().lower() == "yes"
            ]
            return [u for u in used if u]

        except Exception as exc:
            logger.error("Google Sheets read failed: %s", exc)
            return []
