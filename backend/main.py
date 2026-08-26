"""FastAPI application factory with APScheduler lifespan."""
from __future__ import annotations

import logging
import logging.config
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import Base, engine
from backend.routers import channels, posts, schedule
from backend.routers.asmr import router as asmr_router, food_router as asmr_food_router
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
            orphans = db.query(Post).filter(Post.status == "cleaning").all()
            for p in orphans:
                logger.warning("Startup recovery: resetting stuck post %s from cleaning -> queued", p.id)
                p.status = "queued"
                p.error_message = None
            if orphans:
                db.commit()
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

    # CORS — allow Vite dev server, Vercel deployments, and production domains
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(posts.router)
    app.include_router(channels.router)
    app.include_router(schedule.router)
    app.include_router(asmr_router)
    app.include_router(asmr_food_router)

    @app.get("/api/health")
    def health():
        jobs = [
            {"id": j.id, "name": j.name, "next_run": str(j.next_run_time)}
            for j in _scheduler.get_jobs()
        ]
        return {"status": "ok", "scheduler_jobs": jobs}

    return app


app = create_app()
