"""
APScheduler job — daily 9 AM IST ASMR content workflow.

Replaces the n8n "Daily 9AM Trigger" + "Manual Trigger".
"""
from __future__ import annotations

import logging

from backend.services.asmr.workflow import ASMRContentWorkflow

logger = logging.getLogger(__name__)


def run_asmr_workflow_job() -> None:
    """
    APScheduler entry point — runs daily at 9 AM IST.
    Equivalent to the n8n Schedule Trigger (0 9 * * *).
    """
    logger.info("ASMR workflow job started (scheduled trigger)")
    try:
        workflow = ASMRContentWorkflow()
        run = workflow.run(trigger_type="scheduled")
        logger.info(
            "ASMR workflow job completed: run_id=%d status=%s",
            run.id, run.status,
        )
    except Exception:
        logger.exception("ASMR workflow job failed")
