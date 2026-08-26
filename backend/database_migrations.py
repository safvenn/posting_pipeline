"""
Lightweight database migration helper for SQLite/MySQL to add new columns safely on startup.
"""
import logging
from sqlalchemy import inspect, text
from backend.database import engine

logger = logging.getLogger(__name__)

def run_migrations():
    """Ensure newly added columns exist in database tables."""
    try:
        inspector = inspect(engine)
        
        # 1. Check posts table columns
        if inspector.has_table("posts"):
            post_cols = {c["name"] for c in inspector.get_columns("posts")}
            with engine.begin() as conn:
                if "instagram_media_id" not in post_cols:
                    logger.info("Adding instagram_media_id column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN instagram_media_id VARCHAR(128)"))
                if "instagram_post_url" not in post_cols:
                    logger.info("Adding instagram_post_url column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN instagram_post_url VARCHAR(512)"))
                if "instagram_status" not in post_cols:
                    logger.info("Adding instagram_status column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN instagram_status VARCHAR(32) DEFAULT 'none'"))
                if "instagram_error" not in post_cols:
                    logger.info("Adding instagram_error column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN instagram_error TEXT"))
                if "sheet_row_id" not in post_cols:
                    logger.info("Adding sheet_row_id column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN sheet_row_id VARCHAR(64)"))

        # 2. Check channel_configs table columns
        if inspector.has_table("channel_configs"):
            ch_cols = {c["name"] for c in inspector.get_columns("channel_configs")}
            with engine.begin() as conn:
                if "instagram_account_id" not in ch_cols:
                    logger.info("Adding instagram_account_id column to channel_configs table")
                    conn.execute(text("ALTER TABLE channel_configs ADD COLUMN instagram_account_id VARCHAR(128)"))
                if "instagram_access_token" not in ch_cols:
                    logger.info("Adding instagram_access_token column to channel_configs table")
                    conn.execute(text("ALTER TABLE channel_configs ADD COLUMN instagram_access_token TEXT"))
                if "instagram_enabled" not in ch_cols:
                    logger.info("Adding instagram_enabled column to channel_configs table")
                    conn.execute(text("ALTER TABLE channel_configs ADD COLUMN instagram_enabled BOOLEAN DEFAULT 0"))
                if "instagram_username" not in ch_cols:
                    logger.info("Adding instagram_username column to channel_configs table")
                    conn.execute(text("ALTER TABLE channel_configs ADD COLUMN instagram_username VARCHAR(128)"))

        logger.info("Database schema migration check completed.")
    except Exception as exc:
        logger.warning("Database migration check encountered error: %s", exc)
