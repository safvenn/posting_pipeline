"""ASMR workflow router — trigger, monitor, manage food items and content."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ASMRContentJob, ASMRWorkflowRun, FoodItem
from backend.schemas import (
    ASMRContentJobList,
    ASMRContentJobRead,
    ASMRWorkflowRunList,
    ASMRWorkflowRunRead,
    ASMRWorkflowTrigger,
    FoodItemCreate,
    FoodItemList,
    FoodItemRead,
)
from backend.services.asmr.food_selection import (
    add_food_item,
    get_food_stats,
    retire_food_item,
    seed_food_items,
)
from backend.services.asmr.workflow import ASMRContentWorkflow, retry_workflow_run

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows/asmr", tags=["asmr-workflow"])


# --------------------------------------------------------------------------- #
# Workflow execution                                                            #
# --------------------------------------------------------------------------- #

def _run_workflow_background(trigger_type: str, dry_run: bool, idempotency_key: str | None) -> None:
    """Background task: run ASMR workflow."""
    try:
        workflow = ASMRContentWorkflow()
        workflow.run(
            trigger_type=trigger_type,
            dry_run=dry_run,
            idempotency_key=idempotency_key,
        )
    except Exception:
        logger.exception("Background ASMR workflow failed")


@router.post("/run", response_model=ASMRWorkflowRunRead, status_code=202)
def trigger_asmr_workflow(
    body: ASMRWorkflowTrigger,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Manually trigger the ASMR content workflow.
    Returns immediately with a run ID. Execution happens in background.
    """
    # Check for duplicate idempotency key
    if body.idempotency_key:
        existing = (
            db.query(ASMRWorkflowRun)
            .filter(ASMRWorkflowRun.idempotency_key == body.idempotency_key)
            .first()
        )
        if existing:
            return existing

    # Create pending run for immediate response
    from datetime import datetime, timezone
    run = ASMRWorkflowRun(
        trigger_type="manual",
        status="pending",
        dry_run=body.dry_run,
        idempotency_key=body.idempotency_key,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Enqueue background execution
    background_tasks.add_task(
        _run_workflow_background,
        trigger_type="manual",
        dry_run=body.dry_run,
        idempotency_key=run.idempotency_key,
    )

    logger.info("ASMR workflow triggered: run_id=%d dry_run=%s", run.id, body.dry_run)
    return run


# --------------------------------------------------------------------------- #
# Workflow runs                                                                 #
# --------------------------------------------------------------------------- #

@router.get("/runs", response_model=ASMRWorkflowRunList)
def list_workflow_runs(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    query = db.query(ASMRWorkflowRun)
    if status:
        query = query.filter(ASMRWorkflowRun.status == status)
    total = query.count()
    items = query.order_by(ASMRWorkflowRun.created_at.desc()).offset(skip).limit(limit).all()
    return ASMRWorkflowRunList(total=total, items=items)


@router.get("/runs/{run_id}", response_model=ASMRWorkflowRunRead)
def get_workflow_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(ASMRWorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return run


@router.post("/runs/{run_id}/retry", response_model=ASMRWorkflowRunRead)
def retry_run(
    run_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Retry a failed workflow run."""
    run = db.get(ASMRWorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status != "failed":
        raise HTTPException(status_code=400, detail=f"Can only retry failed runs (current: {run.status})")

    background_tasks.add_task(retry_workflow_run, run_id)
    return run


# --------------------------------------------------------------------------- #
# Content jobs                                                                  #
# --------------------------------------------------------------------------- #

@router.get("/content", response_model=ASMRContentJobList)
def list_content_jobs(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    query = db.query(ASMRContentJob)
    total = query.count()
    items = query.order_by(ASMRContentJob.created_at.desc()).offset(skip).limit(limit).all()
    return ASMRContentJobList(total=total, items=items)


@router.get("/content/{job_id}", response_model=ASMRContentJobRead)
def get_content_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ASMRContentJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Content job not found")
    return job


# --------------------------------------------------------------------------- #
# Food items                                                                    #
# --------------------------------------------------------------------------- #

food_router = APIRouter(prefix="/api/asmr/foods", tags=["asmr-foods"])


@food_router.get("", response_model=FoodItemList)
def list_food_items(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    # Ensure seeded
    seed_food_items(db)

    query = db.query(FoodItem)
    if status:
        query = query.filter(FoodItem.status == status)
    total = query.count()
    items = query.order_by(FoodItem.cycle_number.desc(), FoodItem.name.asc()).offset(skip).limit(limit).all()
    return FoodItemList(total=total, items=items)


@food_router.post("", response_model=FoodItemRead, status_code=201)
def create_food_item(body: FoodItemCreate, db: Session = Depends(get_db)):
    try:
        item = add_food_item(db, body.name)
        return item
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@food_router.delete("/{food_id}", status_code=204)
def delete_food_item(food_id: int, db: Session = Depends(get_db)):
    try:
        retire_food_item(db, food_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@food_router.get("/stats")
def food_stats(db: Session = Depends(get_db)):
    seed_food_items(db)
    return get_food_stats(db)
