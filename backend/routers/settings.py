"""Settings router — GET / PATCH /api/settings.

Manages global pipeline toggles stored in the `app_settings` table.

Supported toggles:
  clean_watermark_enabled  (bool, default True)
    When False, newly queued posts skip watermark removal (gwr SSH step) and
    go directly from queued → enrichment/schedule, bypassing cleaning entirely.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import AppSettings
from backend.schemas import AppSettingsRead, AppSettingsUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

_DEFAULT_SETTINGS = {
    "clean_watermark_enabled": "true",
}


def _get_setting(db: Session, key: str) -> str:
    """Return the raw string value for a settings key (upsert default if missing)."""
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    if row is None:
        default = _DEFAULT_SETTINGS.get(key, "true")
        row = AppSettings(key=key, value=default)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row.value


def _set_setting(db: Session, key: str, value: str) -> None:
    """Upsert a settings row."""
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    if row is None:
        row = AppSettings(key=key, value=value)
        db.add(row)
    else:
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
    db.commit()


def get_clean_watermark_enabled(db: Session) -> bool:
    """Convenience function used by the job queue to check the toggle."""
    return _get_setting(db, "clean_watermark_enabled").lower() == "true"


# --------------------------------------------------------------------------- #
# Endpoints                                                                     #
# --------------------------------------------------------------------------- #

@router.get("", response_model=AppSettingsRead)
def get_settings(db: Session = Depends(get_db)):
    """Return current app-wide pipeline settings."""
    enabled = _get_setting(db, "clean_watermark_enabled").lower() == "true"
    return AppSettingsRead(clean_watermark_enabled=enabled)


@router.patch("", response_model=AppSettingsRead)
def update_settings(
    body: AppSettingsUpdate,
    db: Session = Depends(get_db),
):
    """Update app-wide pipeline settings.

    Changing `clean_watermark_enabled` to False causes the job queue to skip
    the watermark cleaning step for posts that have not started cleaning yet.
    Already-running cleaning jobs are not interrupted.
    """
    _set_setting(db, "clean_watermark_enabled", "true" if body.clean_watermark_enabled else "false")
    logger.info(
        "AppSettings updated: clean_watermark_enabled=%s",
        body.clean_watermark_enabled,
    )
    return AppSettingsRead(clean_watermark_enabled=body.clean_watermark_enabled)
