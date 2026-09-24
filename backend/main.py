"""FastAPI application factory with APScheduler lifespan."""
from __future__ import annotations

import logging
import logging.config
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import Base, engine
from backend.routers import channels, posts, schedule
from backend.routers.settings import router as settings_router
from backend.routers.asmr import router as asmr_router, food_router as asmr_food_router
from backend.routers.extension import router as extension_router
from backend.routers.auth import router as auth_router
from backend.jobs.job_queue import run_serial_queue
from backend.jobs.asmr_workflow_job import run_asmr_workflow_job
from backend.jobs.instagram_job import run_instagram_publish_job
from backend.jobs.auto_generate_job import run_auto_generate, trigger_now, get_last_run_result
from backend.middleware.security import add_security_headers
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.middleware.request_context import RequestIDMiddleware, RequestTimingMiddleware
from backend.routers.jobs import router as jobs_router
from backend.routers.metrics import router as metrics_router
from backend.routers.admin import router as admin_router
from backend.logging_config import configure_logging, get_logger

# --------------------------------------------------------------------------- #
# Logging                                                                       #
# --------------------------------------------------------------------------- #

import os as _os
_json_logs = _os.environ.get("LOG_FORMAT", "json").lower() != "text"
configure_logging(json_output=_json_logs, level=_os.environ.get("LOG_LEVEL", "INFO"))
logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# APScheduler                                                                   #
# --------------------------------------------------------------------------- #

_scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


def _configure_scheduler() -> None:
    # Serial pipeline queue — processes ONE post at a time per tick
    _scheduler.add_job(
        run_serial_queue,
        trigger=IntervalTrigger(seconds=30),
        id="serial_queue",
        name="Serial Pipeline Queue",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=60,
    )
    # Instagram Scheduled Publishing — check every 60s for posts due for Instagram
    # Runs independently so it never blocks the watermark/upload pipeline
    _scheduler.add_job(
        run_instagram_publish_job,
        trigger=IntervalTrigger(seconds=60),
        id="instagram_publish_job",
        name="Instagram Scheduled Publisher",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=120,
    )
    # ASMR Content Workflow — daily at 9 AM IST
    _scheduler.add_job(
        run_asmr_workflow_job,
        trigger=CronTrigger(hour=9, minute=0, timezone="Asia/Kolkata"),
        id="asmr_workflow_job",
        name="ASMR Content Workflow",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=300,
    )
    # Auto-Generate Job (fal.ai) — only registered if FAL_API_KEY is configured
    if getattr(settings, "fal_api_key", "").strip():
        _scheduler.add_job(
            run_auto_generate,
            trigger=CronTrigger(hour=9, minute=5, timezone="Asia/Kolkata"),
            id="auto_generate_job",
            name="Auto-Generate Videos (fal.ai)",
            max_instances=1,
            replace_existing=True,
            misfire_grace_time=600,
        )


# --------------------------------------------------------------------------- #
# Lifespan                                                                      #
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ------------------------------------------------------------------ #
    # Schema management — Alembic ONLY in production                      #
    # ------------------------------------------------------------------ #
    # IMPORTANT: We do NOT call Base.metadata.create_all() here.
    # Production schema is managed exclusively via Alembic migrations.
    # Running `alembic upgrade head` must happen as part of the deploy
    # command (or a pre-deploy migration step).
    #
    # In development/testing environments, run:
    #   alembic upgrade head
    # before starting the server.
    #
    # The database_migrations.py fallback still runs for columns that
    # were added before Alembic was introduced, ensuring backward compat.
    try:
        from backend.database_migrations import run_migrations
        run_migrations()
    except Exception as exc:
        logger.warning("Error running database migrations: %s", exc)

    # ------------------------------------------------------------------ #
    # Startup recovery — conservative, no thread spawning                 #
    # ------------------------------------------------------------------ #
    try:
        from backend.database import SessionLocal
        from backend.models import Post
        from datetime import datetime, timezone as _tz
        now = datetime.now(_tz.utc)

        with SessionLocal() as db:
            # 1. Reset stuck 'cleaning' posts
            stuck_cleaning = db.query(Post).filter(Post.status.in_(["cleaning"])).all()
            for p in stuck_cleaning:
                logger.warning("Startup recovery: resetting stuck post %s from %s -> queued", p.id, p.status)
                p.status = "queued"
                p.error_message = None
            if stuck_cleaning:
                db.commit()
                logger.info("Startup recovery: reset %d cleaning post(s) to queued", len(stuck_cleaning))

            # 2. Reset Drive-pending posts whose upload wasn't confirmed
            stuck_drive = db.query(Post).filter(
                Post.status == "queued",
                Post.drive_upload_status == "pending",
            ).all()
            for p in stuck_drive:
                logger.warning("Startup recovery: resetting Drive-pending post %s to none", p.id)
                p.drive_upload_status = "none"
            if stuck_drive:
                db.commit()
                logger.info("Startup recovery: reset %d Drive-pending post(s)", len(stuck_drive))

            # 3. Reset scheduled posts stuck without youtube_video_id (crash mid-upload)
            # Only reset if they've been stuck > 15 minutes (upload threads never survived restart)
            from datetime import timedelta
            stale_cutoff = now - timedelta(minutes=15)
            stuck_upload = db.query(Post).filter(
                Post.status == "scheduled",
                Post.youtube_video_id.is_(None),
                Post.updated_at < stale_cutoff,
            ).all()
            for p in stuck_upload:
                logger.warning(
                    "Startup recovery: post %s stuck scheduled without video_id since %s, re-queuing enrichment",
                    p.id, p.updated_at,
                )
                p.status = "cleaned"  # re-enter from enrichment step
                p.scheduled_at = None
            if stuck_upload:
                db.commit()
                logger.info("Startup recovery: re-queued %d stuck-upload post(s) from cleaned", len(stuck_upload))

            # 4. Clear next_retry_at for retryable posts whose backoff has expired
            expired_retry = db.query(Post).filter(
                Post.next_retry_at.isnot(None),
                Post.next_retry_at <= now,
                Post.status.in_(["queued", "failed"]),
                Post.retry_count < Post.max_retries,
            ).all()
            for p in expired_retry:
                logger.info("Startup recovery: post %s retry backoff expired, clearing next_retry_at", p.id)
                if p.status == "failed":
                    p.status = "queued"
                p.next_retry_at = None
            if expired_retry:
                db.commit()
                logger.info("Startup recovery: cleared retry backoff on %d post(s)", len(expired_retry))

            # NOTE: Drive uploads for posts missing drive_file_id are intentionally
            # NOT triggered here. Spawning background threads per-post at startup
            # could create dozens of threads and overwhelm the server.
            # The serial queue will pick them up on the next tick.
            missing_drive_count = db.query(Post).filter(
                Post.drive_file_id.is_(None),
                Post.drive_upload_status.in_(["none", "pending", "failed"]),
            ).count()
            if missing_drive_count:
                logger.info(
                    "Startup: %d posts missing Drive archive — will be processed by serial queue",
                    missing_drive_count,
                )

    except Exception as exc:
        logger.warning("Startup post recovery error: %s", exc)

    # --- Phase 5: Stale Job recovery (before scheduler starts) ---
    # Reset RUNNING jobs that were abandoned by a previous crash.
    # Must run BEFORE the scheduler starts so it doesn't race with new jobs.
    try:
        from backend.services.circuit_breaker import recover_stale_running_jobs
        from backend.database import SessionLocal
        with SessionLocal() as recovery_db:
            stale_count = recover_stale_running_jobs(recovery_db)
            if stale_count:
                logger.warning(
                    "Startup: reset %d stale RUNNING job(s) to CREATED (crash recovery)",
                    stale_count,
                    extra={"stale_jobs_reset": stale_count},
                )
            else:
                logger.info("Startup: no stale running jobs found")
    except Exception as exc:
        logger.warning("Stale job recovery error (non-fatal): %s", exc)


    logger.info("Starting background scheduler")
    _configure_scheduler()
    _scheduler.start()
    logger.info("Scheduler started. Jobs: %s", [j.id for j in _scheduler.get_jobs()])

    yield

    # Shutdown
    logger.info("Shutting down scheduler")
    _scheduler.shutdown(wait=False)


# --------------------------------------------------------------------------- #
# App                                                                           #
# --------------------------------------------------------------------------- #

def create_app() -> FastAPI:
    app = FastAPI(
        title="YouTube Auto Pipeline",
        description="Self-hosted n8n replacement: video ingest → watermark removal → schedule → upload → comment",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ---- CORS: explicit trusted-origin allowlist — NO wildcard regex with credentials ----
    raw_origins = settings.allowed_origins
    allowed = [o.strip() for o in raw_origins.split(",") if o.strip()]
    if settings.backend_public_url:
        allowed.append(settings.backend_public_url.rstrip("/"))
    # De-duplicate
    allowed = list(dict.fromkeys(o for o in allowed if o))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed,
        allow_origin_regex=r"^(https://([a-zA-Z0-9-]+\.)*(flow\.google|flow\.google\.com|labs\.google)|chrome-extension://.*)$",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=["Content-Disposition", "X-Request-ID", "X-Response-Time"],
    )

    # Security headers — must be added before CORS middleware in the stack
    add_security_headers(app)

    # Rate limiting — per-IP sliding window
    app.add_middleware(RateLimitMiddleware)

    # Request ID correlation + structured access logging
    # Order matters: RequestTimingMiddleware runs first (outermost),
    # RequestIDMiddleware runs second so timing wraps the ID assignment.
    app.add_middleware(RequestTimingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    _trusted_origins: set[str] = set(allowed)

    # Global exception handler — return CORS headers only for trusted origins
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc: Exception):
        logger.exception("Unhandled server exception: %s", exc)
        import re
        from fastapi.responses import JSONResponse
        origin = request.headers.get("origin", "")
        is_trusted = (
            origin in _trusted_origins
            or origin.startswith("chrome-extension://")
            or bool(re.match(r"^https://([a-zA-Z0-9-]+\.)*(flow\.google|flow\.google\.com|labs\.google)$", origin))
        )
        cors_origin = origin if is_trusted else ""
        headers: dict[str, str] = {}
        if cors_origin:
            headers = {
                "Access-Control-Allow-Origin": cors_origin,
                "Access-Control-Allow-Credentials": "true",
                "Vary": "Origin",
            }
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers=headers,
        )


    # ---- Bearer-token auth dependency ----
    # Accepts EITHER the static API_KEY or a valid JWT access token
    _bearer = HTTPBearer(auto_error=False)

    def require_api_key(
        credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    ) -> None:
        """Reject requests that don't carry the configured API key OR a valid JWT."""
        token = credentials.credentials if credentials else None
        if not token:
            expected = settings.api_key
            if not expected:
                return  # auth disabled (dev mode)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # First: try static API key
        if settings.api_key and token == settings.api_key:
            return

        # Second: try JWT access token
        try:
            from jose import jwt as _jwt, JWTError
            secret = settings.jwt_secret
            if secret:
                payload = _jwt.decode(token, secret, algorithms=[settings.jwt_algorithm])
                if payload.get("type") == "access" and payload.get("sub"):
                    return
        except Exception:
            pass

        # If API_KEY is not set and JWT also failed, reject
        expected = settings.api_key
        if not expected:
            return  # auth fully disabled
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key / token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Public auth endpoints (login/refresh/logout — no API key required)
    app.include_router(auth_router)

    # Public OAuth callback router (no auth required)
    app.include_router(channels.public_router)

    # Public extension ingest — no auth (local/self-hosted only)
    app.include_router(extension_router)

    # Public video endpoints (playback / Instagram crawler download — no auth required)
    app.include_router(posts.public_router)

    # Routers (all protected by api-key dependency)
    app.include_router(posts.router,    dependencies=[Depends(require_api_key)])
    app.include_router(channels.router, dependencies=[Depends(require_api_key)])
    app.include_router(schedule.router, dependencies=[Depends(require_api_key)])
    app.include_router(asmr_router,      dependencies=[Depends(require_api_key)])
    app.include_router(asmr_food_router,  dependencies=[Depends(require_api_key)])
    app.include_router(settings_router,   dependencies=[Depends(require_api_key)])
    app.include_router(jobs_router,       dependencies=[Depends(require_api_key)])
    app.include_router(metrics_router,    dependencies=[Depends(require_api_key)])
    app.include_router(admin_router,      dependencies=[Depends(require_api_key)])

    # Public health endpoints — no auth required
    # Liveness: is the process alive?
    @app.get("/api/health/live", tags=["health"])
    def health_live():
        """Liveness probe — returns 200 if the process is running."""
        return {"status": "ok"}

    # Readiness: is the process ready to serve traffic?
    @app.get("/api/health/ready", tags=["health"])
    def health_ready():
        """Readiness probe — checks database connectivity."""
        db_ok = False
        db_error = None
        try:
            from backend.database import SessionLocal
            from sqlalchemy import text
            with SessionLocal() as _db:
                _db.execute(text("SELECT 1"))
            db_ok = True
        except Exception as exc:
            db_error = str(exc)

        scheduler_ok = _scheduler.running
        ready = db_ok  # scheduler is optional for readiness

        return {
            "status": "ready" if ready else "degraded",
            "database": "ok" if db_ok else f"error: {db_error}",
            "scheduler": "ok" if scheduler_ok else "stopped",
        }

    # Legacy health endpoint — preserved for backward compatibility
    @app.get("/api/health", tags=["health"])
    def health():
        jobs = [
            {"id": j.id, "name": j.name, "next_run": str(j.next_run_time)}
            for j in _scheduler.get_jobs()
        ]
        return {"status": "ok", "scheduler_jobs": jobs}

    # ---- Auto-Generate endpoints — no api-key on GET status, key on POST trigger ----
    @app.get("/api/auto/status")
    def auto_status():
        """Get auto-generate job status, last run, and next scheduled run."""
        from backend.services.fal_service import check_fal_configured
        next_run = None
        job = _scheduler.get_job("auto_generate_job")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
        return {
            "fal_configured": check_fal_configured(),
            "fal_model": settings.fal_default_model,
            "schedule": "Daily at 9:05 AM IST",
            "next_run": next_run,
            "last_run": get_last_run_result(),
        }

    @app.post("/api/auto/trigger", dependencies=[Depends(require_api_key)])
    def auto_trigger(channel: str = "all", limit: int = 1):
        """Manually trigger auto-generate right now (for testing). Requires API key."""
        ch = None if channel == "all" else channel
        result = trigger_now(channel=ch, limit=limit)
        return result

    return app


app = create_app()
