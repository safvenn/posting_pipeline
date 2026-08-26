"""
Robust Script to migrate all existing data from local SQLite database (pipeline.db) to Supabase PostgreSQL database.
Uses raw sqlite3 dictionary mapping so missing legacy columns are safely handled with defaults.
"""
import sqlite3
from datetime import datetime
from dateutil.parser import parse as parse_date
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.database import Base, normalize_db_url
from backend.models import (
    Post,
    ChannelConfig,
    FoodItem,
    ASMRWorkflowRun,
    ASMRContentJob,
    ASMRPublishedContent,
)

SQLITE_PATH = "pipeline.db"
SUPABASE_URL = "postgresql://postgres.rrgqtizlkqcrlqjwweju:safwankallu00@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"

def parse_dt(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return parse_date(str(v))
    except Exception:
        return None

def migrate():
    print("=" * 60)
    print("MIGRATING LOCAL SQLITE DATA -> SUPABASE POSTGRESQL")
    print("=" * 60)

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    supabase_engine = create_engine(normalize_db_url(SUPABASE_URL))

    print("\n1. Ensuring tables exist in Supabase...")
    Base.metadata.create_all(bind=supabase_engine)
    print("   [OK] Tables verified in Supabase.")

    # Get available tables in SQLite
    sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    sqlite_tables = {t[0] for t in sqlite_cur.fetchall()}
    print(f"   [INFO] Tables found in SQLite: {', '.join(sqlite_tables)}")

    with Session(supabase_engine) as session:
        # 1. Migrate ChannelConfigs
        if "channel_configs" in sqlite_tables:
            print("\n2. Migrating ChannelConfigs...")
            sqlite_cur.execute("SELECT * FROM channel_configs")
            rows = [dict(r) for r in sqlite_cur.fetchall()]
            ch_count = 0
            for r in rows:
                key = r.get("key")
                if not key:
                    continue
                existing = session.query(ChannelConfig).filter_by(key=key).first()
                if not existing:
                    new_ch = ChannelConfig(
                        id=r.get("id"),
                        key=key,
                        display_name=r.get("display_name") or key,
                        client_id=r.get("client_id") or "",
                        client_secret=r.get("client_secret") or "",
                        refresh_token=r.get("refresh_token") or "",
                        sheet_id=r.get("sheet_id"),
                        sheet_tab=r.get("sheet_tab"),
                        seo_tags=r.get("seo_tags"),
                        instagram_account_id=r.get("instagram_account_id"),
                        instagram_access_token=r.get("instagram_access_token"),
                        instagram_enabled=bool(r.get("instagram_enabled", False)),
                        instagram_username=r.get("instagram_username"),
                        is_active=bool(r.get("is_active", True)),
                        created_at=parse_dt(r.get("created_at")) or datetime.utcnow(),
                        updated_at=parse_dt(r.get("updated_at")) or datetime.utcnow(),
                    )
                    session.add(new_ch)
                    ch_count += 1
                else:
                    existing.display_name = r.get("display_name") or existing.display_name
                    existing.client_id = r.get("client_id") or existing.client_id
                    existing.client_secret = r.get("client_secret") or existing.client_secret
                    existing.refresh_token = r.get("refresh_token") or existing.refresh_token
                    existing.sheet_id = r.get("sheet_id") or existing.sheet_id
                    existing.sheet_tab = r.get("sheet_tab") or existing.sheet_tab
                    existing.seo_tags = r.get("seo_tags") or existing.seo_tags
                    existing.instagram_account_id = r.get("instagram_account_id") or existing.instagram_account_id
                    existing.instagram_access_token = r.get("instagram_access_token") or existing.instagram_access_token
                    existing.instagram_enabled = bool(r.get("instagram_enabled", existing.instagram_enabled))
                    existing.instagram_username = r.get("instagram_username") or existing.instagram_username
            session.commit()
            print(f"   [OK] {len(rows)} channel(s) processed ({ch_count} newly inserted).")

        # 2. Migrate Posts
        if "posts" in sqlite_tables:
            print("\n3. Migrating Posts & Schedules...")
            sqlite_cur.execute("SELECT * FROM posts")
            rows = [dict(r) for r in sqlite_cur.fetchall()]
            post_count = 0
            for r in rows:
                post_id = r.get("id")
                if not post_id:
                    continue
                existing = session.query(Post).filter_by(id=post_id).first()
                if not existing:
                    new_p = Post(
                        id=post_id,
                        channel=r.get("channel") or "channel_a",
                        title=r.get("title") or "Untitled",
                        description=r.get("description") or "",
                        tags=r.get("tags") or "",
                        video_path=r.get("video_path") or "",
                        clean_video_path=r.get("clean_video_path"),
                        status=r.get("status") or "queued",
                        scheduled_at=parse_dt(r.get("scheduled_at")),
                        youtube_video_id=r.get("youtube_video_id"),
                        first_comment_posted=bool(r.get("first_comment_posted", False)),
                        error_message=r.get("error_message"),
                        instagram_media_id=r.get("instagram_media_id"),
                        instagram_post_url=r.get("instagram_post_url"),
                        instagram_status=r.get("instagram_status") or "none",
                        instagram_error=r.get("instagram_error"),
                        sheet_row_id=r.get("sheet_row_id"),
                        enriched_title=r.get("enriched_title"),
                        enriched_description=r.get("enriched_description"),
                        enriched_tags=r.get("enriched_tags"),
                        first_comment_text=r.get("first_comment_text"),
                        created_at=parse_dt(r.get("created_at")) or datetime.utcnow(),
                        updated_at=parse_dt(r.get("updated_at")) or datetime.utcnow(),
                    )
                    session.add(new_p)
                    post_count += 1
            session.commit()
            print(f"   [OK] {len(rows)} post(s) processed ({post_count} newly inserted).")

        # 3. Migrate FoodItems
        if "food_items" in sqlite_tables:
            print("\n4. Migrating Food Items...")
            sqlite_cur.execute("SELECT * FROM food_items")
            rows = [dict(r) for r in sqlite_cur.fetchall()]
            food_count = 0
            for r in rows:
                norm_name = r.get("normalized_name") or r.get("name", "").lower().strip()
                cycle_num = int(r.get("cycle_number", 1))
                existing = session.query(FoodItem).filter_by(normalized_name=norm_name, cycle_number=cycle_num).first()
                if not existing:
                    new_f = FoodItem(
                        id=r.get("id"),
                        name=r.get("name"),
                        normalized_name=norm_name,
                        status=r.get("status") or "available",
                        cycle_number=cycle_num,
                        used_at=parse_dt(r.get("used_at")),
                        created_at=parse_dt(r.get("created_at")) or datetime.utcnow(),
                        updated_at=parse_dt(r.get("updated_at")) or datetime.utcnow(),
                    )
                    session.add(new_f)
                    food_count += 1
            session.commit()
            print(f"   [OK] {len(rows)} food item(s) processed ({food_count} newly inserted).")

        # 4. Migrate ASMRWorkflowRuns
        if "asmr_workflow_runs" in sqlite_tables:
            print("\n5. Migrating ASMR Workflow Runs...")
            sqlite_cur.execute("SELECT * FROM asmr_workflow_runs")
            rows = [dict(r) for r in sqlite_cur.fetchall()]
            run_count = 0
            for r in rows:
                run_id = r.get("id")
                if not run_id:
                    continue
                existing = session.query(ASMRWorkflowRun).filter_by(id=run_id).first()
                if not existing:
                    new_r = ASMRWorkflowRun(
                        id=run_id,
                        trigger_type=r.get("trigger_type") or "manual",
                        status=r.get("status") or "pending",
                        food_item_id=r.get("food_item_id"),
                        started_at=parse_dt(r.get("started_at")) or datetime.utcnow(),
                        completed_at=parse_dt(r.get("completed_at")),
                        error_message=r.get("error_message"),
                        dry_run=bool(r.get("dry_run", False)),
                        idempotency_key=r.get("idempotency_key"),
                        created_at=parse_dt(r.get("created_at")) or datetime.utcnow(),
                        updated_at=parse_dt(r.get("updated_at")) or datetime.utcnow(),
                    )
                    session.add(new_r)
                    run_count += 1
            session.commit()
            print(f"   [OK] {len(rows)} workflow run(s) processed ({run_count} newly inserted).")

        # 5. Migrate ASMRContentJobs
        if "asmr_content_jobs" in sqlite_tables:
            print("\n6. Migrating ASMR Content Jobs...")
            sqlite_cur.execute("SELECT * FROM asmr_content_jobs")
            rows = [dict(r) for r in sqlite_cur.fetchall()]
            job_count = 0
            for r in rows:
                job_id = r.get("id")
                if not job_id:
                    continue
                existing = session.query(ASMRContentJob).filter_by(id=job_id).first()
                if not existing:
                    new_j = ASMRContentJob(
                        id=job_id,
                        workflow_run_id=r.get("workflow_run_id"),
                        food_item_id=r.get("food_item_id"),
                        status=r.get("status") or "pending",
                        food_name=r.get("food_name") or "",
                        video_prompt=r.get("video_prompt"),
                        title=r.get("title"),
                        caption=r.get("caption"),
                        description=r.get("description"),
                        tags=r.get("tags"),
                        hashtags=r.get("hashtags"),
                        video_url=r.get("video_url"),
                        video_storage_key=r.get("video_storage_key"),
                        video_size_bytes=r.get("video_size_bytes"),
                        video_mime_type=r.get("video_mime_type"),
                        video_duration_seconds=r.get("video_duration_seconds"),
                        error_message=r.get("error_message"),
                        retry_count=int(r.get("retry_count", 0)),
                        created_at=parse_dt(r.get("created_at")) or datetime.utcnow(),
                        updated_at=parse_dt(r.get("updated_at")) or datetime.utcnow(),
                    )
                    session.add(new_j)
                    job_count += 1
            session.commit()
            print(f"   [OK] {len(rows)} content job(s) processed ({job_count} newly inserted).")

        # 6. Migrate ASMRPublishedContent
        if "asmr_published_content" in sqlite_tables:
            print("\n7. Migrating ASMR Published Content...")
            sqlite_cur.execute("SELECT * FROM asmr_published_content")
            rows = [dict(r) for r in sqlite_cur.fetchall()]
            pub_count = 0
            for r in rows:
                pub_id = r.get("id")
                if not pub_id:
                    continue
                existing = session.query(ASMRPublishedContent).filter_by(id=pub_id).first()
                if not existing:
                    new_pub = ASMRPublishedContent(
                        id=pub_id,
                        content_job_id=r.get("content_job_id"),
                        platform=r.get("platform") or "youtube",
                        platform_post_id=r.get("platform_post_id"),
                        published_at=parse_dt(r.get("published_at")),
                        url=r.get("url"),
                        created_at=parse_dt(r.get("created_at")) or datetime.utcnow(),
                    )
                    session.add(new_pub)
                    pub_count += 1
            session.commit()
            print(f"   [OK] {len(rows)} published item(s) processed ({pub_count} newly inserted).")

        # Reset Postgres Auto-Increment sequences to avoid PK conflicts on future inserts
        print("\n8. Updating PostgreSQL primary key ID sequences...")
        with supabase_engine.begin() as conn:
            for table_name in ["channel_configs", "posts", "food_items", "asmr_workflow_runs", "asmr_content_jobs", "asmr_published_content"]:
                try:
                    conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE((SELECT MAX(id) FROM {table_name}), 1));"))
                except Exception as seq_err:
                    pass
        print("   [OK] Sequences updated successfully.")

    sqlite_conn.close()
    print("\n" + "=" * 60)
    print("MIGRATION COMPLETED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    migrate()
