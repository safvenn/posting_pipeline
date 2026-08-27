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
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from backend.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


import time as _time

_GSPREAD_CLIENT: "gspread.Client | None" = None
_GSPREAD_CREATED_AT: float = 0.0
_GSPREAD_TTL_SECONDS: float = 600.0  # 10 minutes


def invalidate_gspread_client() -> None:
    """Force the next call to _gc() to create a fresh gspread client.
    Call this after updating Google Sheets service account credentials
    without restarting the app.
    """
    global _GSPREAD_CLIENT, _GSPREAD_CREATED_AT
    _GSPREAD_CLIENT = None
    _GSPREAD_CREATED_AT = 0.0
    logger.info("gspread client cache invalidated — next call will re-authenticate")


def _gc() -> gspread.Client:
    """TTL-cached gspread client using service account credentials.
    Re-authenticates automatically every 10 minutes or when invalidated.
    """
    global _GSPREAD_CLIENT, _GSPREAD_CREATED_AT
    now = _time.monotonic()
    if _GSPREAD_CLIENT is None or (now - _GSPREAD_CREATED_AT) > _GSPREAD_TTL_SECONDS:
        sa_val = settings.google_sheets_service_account_json.strip()
        if sa_val.startswith("{"):
            import json
            info = json.loads(sa_val)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(sa_val, scopes=SCOPES)
        _GSPREAD_CLIENT = gspread.authorize(creds)
        _GSPREAD_CREATED_AT = now
        logger.debug("gspread client (re-)authenticated")
    return _GSPREAD_CLIENT


import csv
import io
import re
import httpx


def _extract_sheet_id(val: str) -> str:
    """Extract clean Google Sheet ID from URL or raw ID."""
    if not val:
        return ""
    val = val.strip()
    # Match standard docs.google.com/spreadsheets/d/<ID>
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", val)
    if m and not val.startswith("https://docs.google.com/spreadsheets/d/e/"):
        return m.group(1)
    return val


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

    clean_id = _extract_sheet_id(sheet_id)
    sh = gc.open_by_key(clean_id)
    return sh.worksheet(tab_name) if tab_name else sh.sheet1


def get_all_rows(channel: str) -> list[dict]:
    """Return all rows as list of dicts (header row as keys)."""
    # Check if channel configured with a published CSV URL
    sheet_id = None
    try:
        from backend.database import SessionLocal
        from backend.models import ChannelConfig
        with SessionLocal() as db:
            cfg = db.query(ChannelConfig).filter(ChannelConfig.key == channel, ChannelConfig.is_active == True).first()
            if cfg and cfg.sheet_id:
                sheet_id = cfg.sheet_id
    except Exception:
        pass

    if not sheet_id and settings.google_sheets_id_channel_a:
        sheet_id = settings.google_sheets_id_channel_a

    # Fallback to direct HTTP fetch if a published CSV URL is provided
    if sheet_id and ("pub?output=csv" in sheet_id or "pub?gid=" in sheet_id or "/d/e/2PACX-" in sheet_id):
        try:
            resp = httpx.get(sheet_id, timeout=15.0, follow_redirects=True)
            if resp.status_code == 200:
                reader = csv.DictReader(io.StringIO(resp.text))
                return [dict(r) for r in reader if any(r.values())]
        except Exception as csv_err:
            logger.warning("Error fetching published CSV sheet: %s", csv_err)

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


def _find_column_index(headers: list[str], target_name: str) -> Optional[int]:
    """Find 1-indexed column number for a field name supporting common aliases."""
    normalized_target = re.sub(r"[_\s-]+", "", target_name.lower())
    aliases = {
        "scheduled": ["scheduled", "schedule", "scheduletime", "scheduledtime", "scheduledat", "date", "slot"],
        "uploadid": ["uploadid", "upload_id", "upload id", "youtubeid", "youtube_id", "videoid", "video_id", "ytid"],
        "title": ["title", "enrichedtitle", "videotitle", "name", "videoname"],
        "description": ["description", "desc", "videodescription"],
        "tags": ["tags", "hashtags", "tag"],
    }
    candidates = aliases.get(normalized_target, [normalized_target])

    for i, h in enumerate(headers):
        norm_h = re.sub(r"[_\s-]+", "", str(h).lower())
        if norm_h in candidates:
            return i + 1
    return None


def update_row_fields(
    channel: str,
    row_id: int | str,
    fields: dict[str, str],
) -> bool:
    """
    Update specific column values for a row matched by 'id' in Google Sheet.
    Example: update_row_fields("channel_a", "12", {"scheduled": "2026-08-28T09:00:00+05:30", "upload id": "abc123xyz"})
    """
    try:
        ws = _sheet(channel)
        records = ws.get_all_records(default_blank="")

        target_row_num: Optional[int] = None
        for i, row in enumerate(records):
            if str(row.get("id", "")).strip() == str(row_id).strip():
                target_row_num = i + 2  # +1 for header row, +1 for 1-based indexing
                break

        if target_row_num is None:
            logger.warning("Channel %s: could not find row with id=%s in Google Sheet", channel, row_id)
            return False

        headers = ws.row_values(1)

        for col_name, value in fields.items():
            if value is None:
                continue
            col_idx = _find_column_index(headers, col_name)
            if col_idx is not None:
                ws.update_cell(target_row_num, col_idx, str(value))
                logger.debug("Google Sheet cell updated: channel=%s row=%s col=%s val=%s", channel, target_row_num, col_name, value)
            else:
                logger.warning("Column '%s' not found in sheet headers: %s", col_name, headers)

        logger.info("Google Sheet row #%s updated for channel %s: %s", row_id, channel, fields)
        return True
    except Exception as exc:
        logger.error("Failed to update Google Sheet row #%s for channel %s: %s", row_id, channel, exc)
        return False


def update_row_after_upload(
    channel: str,
    row_id: int | str,
    scheduled_at: str,
    upload_id: str,
    enriched_title: str,
) -> None:
    """
    Write scheduled date, YouTube upload ID, and enriched title back to the Google Sheet.
    """
    fields = {}
    if scheduled_at:
        fields["scheduled"] = scheduled_at
    if upload_id:
        fields["upload id"] = upload_id
    if enriched_title:
        fields["title"] = enriched_title

    update_row_fields(channel, row_id, fields)


def is_row_scheduled(channel: str, row_id: int | str) -> bool:
    """Return True if row has non-empty 'scheduled' or 'upload id'."""
    row = get_row_by_id(channel, row_id)
    if not row:
        return False
    sched = str(row.get("scheduled", "")).strip()
    upload = str(row.get("upload id", "") or row.get("upload_id", "")).strip()
    return bool(sched or upload)


def append_new_row(channel: str, title: str, description: str = "", tags: str = "", prompt: str = "") -> dict:
    """
    Append a new row to the channel's Google Sheet with a clean new ID.
    Returns the newly created row dict.
    """
    ws = _sheet(channel)
    records = ws.get_all_records(default_blank="")

    # Determine highest numeric ID or next sequence
    max_id = 0
    for r in records:
        raw_id = str(r.get("id", "")).strip()
        if raw_id.isdigit():
            max_id = max(max_id, int(raw_id))
    new_id = max_id + 1 if max_id > 0 else len(records) + 1

    headers = [h.lower().strip() for h in ws.row_values(1)]
    if not headers:
        headers = ["id", "title", "description", "prompt", "tags", "scheduled", "upload id"]

    row_vals = []
    for h in headers:
        if h == "id":
            row_vals.append(str(new_id))
        elif h == "title":
            row_vals.append(title)
        elif h == "description":
            row_vals.append(description)
        elif h == "prompt":
            row_vals.append(prompt)
        elif h == "tags":
            row_vals.append(tags)
        elif h in ("scheduled", "upload id", "upload_id"):
            row_vals.append("")
        else:
            row_vals.append("")

    ws.append_row(row_vals)
    logger.info("Appended new row to Google Sheet: channel=%s new_id=%s title=%s", channel, new_id, title)
    return {
        "id": str(new_id),
        "title": title,
        "description": description,
        "tags": tags,
        "prompt": prompt,
        "scheduled": "",
        "upload id": "",
    }

