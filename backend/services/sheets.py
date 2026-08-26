"""
Google Sheets integration — gspread with service account JSON.

Two sheets (one per channel):
  Channel A: indian_food_miniature_asmr_prompts
  Channel B: 30_fruit_growth_video_prompts

Columns (matching n8n workflow schema):
  id | title | description | prompt | tags | scheduled | upload id

get_first_unscheduled_row() — find first row where 'scheduled' is null/empty
update_row_after_upload()   — write scheduled, upload id, enriched title back (match by id)
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from backend.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


@lru_cache(maxsize=1)
def _gc() -> gspread.Client:
    """Cached gspread client using service account credentials."""
    sa_val = settings.google_sheets_service_account_json.strip()
    if sa_val.startswith("{"):
        import json
        info = json.loads(sa_val)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(sa_val, scopes=SCOPES)
    return gspread.authorize(creds)


def _sheet(channel: str) -> gspread.Worksheet:
    """Return the worksheet for the given channel."""
    gc = _gc()
    sheet_id = None
    tab_name = None

    # Check DB ChannelConfig first
    try:
        from backend.database import SessionLocal
        from backend.models import ChannelConfig
        with SessionLocal() as db:
            cfg = db.query(ChannelConfig).filter(ChannelConfig.key == channel, ChannelConfig.is_active == True).first()
            if cfg and cfg.sheet_id:
                sheet_id = cfg.sheet_id
                tab_name = cfg.sheet_tab
    except Exception as exc:
        logger.debug("ChannelConfig DB lookup for sheet skipped: %s", exc)

    if not sheet_id:
        if channel == "channel_a":
            sheet_id = settings.google_sheets_id_channel_a
            tab_name = settings.google_sheets_tab_channel_a
        elif channel == "channel_b":
            sheet_id = settings.google_sheets_id_channel_b
            tab_name = settings.google_sheets_tab_channel_b
        elif settings.google_sheets_id_channel_a:
            sheet_id = settings.google_sheets_id_channel_a
            tab_name = settings.google_sheets_tab_channel_a

    if not sheet_id:
        raise ValueError(
            f"Google Sheet ID not configured for channel '{channel}'. "
            "Please configure the Sheet ID in Channel Settings."
        )

    sh = gc.open_by_key(sheet_id)
    return sh.worksheet(tab_name) if tab_name else sh.sheet1


def get_all_rows(channel: str) -> list[dict]:
    """Return all rows as list of dicts (header row as keys)."""
    ws = _sheet(channel)
    records = ws.get_all_records(default_blank="")
    return records


def get_first_unscheduled_row(channel: str) -> Optional[dict]:
    """
    Return the first row where 'scheduled' is null/empty, preserving row order.
    Returns None if all rows are scheduled.
    """
    records = get_all_rows(channel)
    for row in records:
        scheduled = str(row.get("scheduled", "")).strip()
        if not scheduled:
            logger.info(
                "Channel %s: found unscheduled row id=%s title=%s",
                channel, row.get("id"), row.get("title", "")[:50],
            )
            return row
    logger.info("Channel %s: no unscheduled rows found", channel)
    return None


def get_row_by_id(channel: str, row_id: int | str) -> Optional[dict]:
    """Return specific row by 'id' column value."""
    records = get_all_rows(channel)
    for row in records:
        if str(row.get("id", "")).strip() == str(row_id).strip():
            return row
    return None


def update_row_after_upload(
    channel: str,
    row_id: int | str,
    scheduled_at: str,
    upload_id: str,
    enriched_title: str,
) -> None:
    """
    Write scheduled date, YouTube upload ID, and enriched title back to the sheet.
    Matches row by the 'id' column (same as n8n appendOrUpdate matchingColumns: ['id']).
    """
    ws = _sheet(channel)
    records = ws.get_all_records(default_blank="")

    # Find the row number (1-indexed; +2 because row 1 is header, gspread is 1-indexed)
    target_row_num: int | None = None
    for i, row in enumerate(records):
        if str(row.get("id", "")).strip() == str(row_id).strip():
            target_row_num = i + 2  # +1 for header, +1 for 0→1 index
            break

    if target_row_num is None:
        logger.error("Channel %s: could not find row with id=%s to update", channel, row_id)
        return

    # Find column indices for 'scheduled', 'upload id', 'title'
    headers = ws.row_values(1)
    col_map = {h.lower().strip(): i + 1 for i, h in enumerate(headers)}

    def _write(col_name: str, value: str) -> None:
        col = col_map.get(col_name.lower())
        if col is None:
            logger.warning("Column '%s' not found in sheet for channel %s", col_name, channel)
            return
        ws.update_cell(target_row_num, col, value)
        logger.debug("Sheet update: channel=%s row=%s col=%s value=%s", channel, target_row_num, col_name, value)

    _write("scheduled", scheduled_at)
    _write("upload id", upload_id)
    _write("title", enriched_title)

    logger.info(
        "Sheet updated: channel=%s id=%s scheduled=%s upload_id=%s",
        channel, row_id, scheduled_at, upload_id,
    )
