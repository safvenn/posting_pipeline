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
from backend.routers.asmr import router as asmr_router, food_router as asmr_food_router
from backend.routers.extension import router as extension_router
from backend.jobs.job_queue import run_serial_queue
from backend.jobs.asmr_workflow_job import run_asmr_workflow_job

# --------------------------------------------------------------------------- #
# Logging                                                                       #
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# APScheduler                                                                   #
# --------------------------------------------------------------------------- #

_scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


def _configure_scheduler() -> None:
    # Serial pipeline queue — processes ONE post at a time
    # Priority: queued → cleaned → uploaded (clean → enrich/upload → comment)
    _scheduler.add_job(
        run_serial_queue,
        trigger=IntervalTrigger(seconds=30),
        id="serial_queue",
        name="Serial Pipeline Queue",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=60,
    )
    # ASMR Content Workflow — daily at 9 AM IST (separate workflow, not part of the queue)
    _scheduler.add_job(
        run_asmr_workflow_job,
        trigger=CronTrigger(hour=9, minute=0, timezone="Asia/Kolkata"),
        id="asmr_workflow_job",
        name="ASMR Content Workflow",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=300,
    )


# --------------------------------------------------------------------------- #
# Lifespan                                                                      #
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Creating database tables (if not exist)")
    Base.metadata.create_all(bind=engine)
    try:
        from backend.database_migrations import run_migrations
        run_migrations()
    except Exception as exc:
        logger.warning("Error running database migrations: %s", exc)

    # Recover any posts left stuck in 'cleaning' from prior restarts
    try:
        from backend.database import SessionLocal
        from backend.models import Post
        with SessionLocal() as db:
            stuck = db.query(Post).filter(Post.status.in_(["cleaning"])).all()
            for p in stuck:
                logger.warning("Startup recovery: resetting stuck post %s from %s -> queued", p.id, p.status)
                p.status = "queued"
                p.error_message = None
            if stuck:
                db.commit()
                logger.info("Startup recovery: reset %d stuck post(s) to queued", len(stuck))
    except Exception as exc:
        logger.warning("Startup post recovery error: %s", exc)

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

    # ---- CORS: explicit allowlist only ----
    raw_origins = settings.allowed_origins
    allowed = [o.strip() for o in raw_origins.split(",") if o.strip()]
    # Also allow the render/production backend public URL's frontend sibling (optional)
    if settings.backend_public_url:
        allowed.append(settings.backend_public_url.rstrip("/"))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed,          # explicit list — never a regex wildcard
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- Bearer-token auth dependency ----
    _bearer = HTTPBearer(auto_error=False)

    def require_api_key(
        credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    ) -> None:
        """Reject requests that don't carry the configured API key."""
        expected = settings.api_key
        if not expected:
            # No key configured → auth disabled (dev mode, local-only)
            return
        if not credentials or credentials.credentials != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Public OAuth callback router (no auth required)
    app.include_router(channels.public_router)

    # Public extension ingest — no auth (local/self-hosted only)
    app.include_router(extension_router)

    # Routers (all protected by api-key dependency)
    app.include_router(posts.router,    dependencies=[Depends(require_api_key)])
    app.include_router(channels.router, dependencies=[Depends(require_api_key)])
    app.include_router(schedule.router, dependencies=[Depends(require_api_key)])
    app.include_router(asmr_router,     dependencies=[Depends(require_api_key)])
    app.include_router(asmr_food_router, dependencies=[Depends(require_api_key)])

    # Public health endpoint — no auth required
    @app.get("/api/health")
    def health():
        jobs = [
            {"id": j.id, "name": j.name, "next_run": str(j.next_run_time)}
            for j in _scheduler.get_jobs()
        ]
        return {"status": "ok", "scheduler_jobs": jobs}

    return app


app = create_app()
