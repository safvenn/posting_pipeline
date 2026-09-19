"""
Lightweight database migration helper for SQLite/MySQL to add new columns safely on startup.
"""
import logging
from sqlalchemy import inspect, text
from backend.database import engine

logger = logging.getLogger(__name__)

def run_migrations():
    """Ensure newly added columns exist in database tables."""
    # 1. First attempt Alembic upgrade head if available
    try:
        import os
        from alembic.config import Config
        from alembic import command
        alembic_ini = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
        if os.path.exists(alembic_ini):
            alembic_cfg = Config(alembic_ini)
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic upgrade head completed successfully.")
    except Exception as exc:
        logger.info("Alembic upgrade note (continuing to direct column check): %s", exc)

    # 2. Direct column inspection fallback for SQLite / Postgres
    try:
        inspector = inspect(engine)
        tz_type = "DATETIME" if engine.dialect.name == "sqlite" else "TIMESTAMP WITH TIME ZONE"
        
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
                if "instagram_container_id" not in post_cols:
                    logger.info("Adding instagram_container_id column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN instagram_container_id VARCHAR(128)"))
                # Drive & Retry fields
                if "drive_file_id" not in post_cols:
                    logger.info("Adding drive_file_id column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN drive_file_id VARCHAR(256)"))
                if "drive_upload_status" not in post_cols:
                    logger.info("Adding drive_upload_status column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN drive_upload_status VARCHAR(32) DEFAULT 'none'"))
                if "retry_count" not in post_cols:
                    logger.info("Adding retry_count column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN retry_count INTEGER DEFAULT 0"))
                if "max_retries" not in post_cols:
                    logger.info("Adding max_retries column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN max_retries INTEGER DEFAULT 5"))
                if "next_retry_at" not in post_cols:
                    logger.info("Adding next_retry_at column to posts table")
                    conn.execute(text(f"ALTER TABLE posts ADD COLUMN next_retry_at {tz_type}"))
                if "last_error" not in post_cols:
                    logger.info("Adding last_error column to posts table")
                    conn.execute(text("ALTER TABLE posts ADD COLUMN last_error TEXT"))
                if "last_attempt_at" not in post_cols:
                    logger.info("Adding last_attempt_at column to posts table")
                    conn.execute(text(f"ALTER TABLE posts ADD COLUMN last_attempt_at {tz_type}"))

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
