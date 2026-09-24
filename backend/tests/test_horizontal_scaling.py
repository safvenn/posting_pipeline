"""
Unit and integration tests for Phase 9: Horizontal Scaling & Distributed Worker Coordination.

Verifies:
  1. Distributed locking (post-level, channel-level, mutual exclusion, contention).
  2. Worker coordinator task leasing (atomic claiming, zero double-leases).
  3. Worker heartbeating (lease extension, ownership verification).
  4. Graceful worker shutdown (job release back to queue).
  5. Zombie reaper (stale lease recovery, max attempt dead-lettering).
  6. Cluster worker directory (active worker aggregation).
  7. HTTP endpoints for distributed workers.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Generator
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.database import Base, get_db
from backend.models import Job, Post
from backend.repositories.job_repository import JobStatus, JobType, JobRepository
from backend.services.distributed_lock import advisory_lock, channel_lock
from backend.services.worker_coordinator import WorkerCoordinator
from backend.routers.jobs import router as jobs_router


from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Test DB Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_client(db_session) -> TestClient:
    app = FastAPI()
    app.include_router(jobs_router)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Distributed Locking Tests
# ---------------------------------------------------------------------------

class TestDistributedLocking:
    def test_post_lock_mutual_exclusion(self, db_session: Session):
        """Two concurrent threads cannot acquire the lock for the same post + op."""
        results = []

        def worker_task(worker_id: str):
            with advisory_lock(db_session, post_id=101, operation="youtube_upload") as acquired:
                results.append((worker_id, acquired))
                if acquired:
                    time.sleep(0.05)

        t1 = threading.Thread(target=worker_task, args=("worker-1",))
        t2 = threading.Thread(target=worker_task, args=("worker-2",))

        t1.start()
        time.sleep(0.01)  # ensure t1 acquires first
        t2.start()

        t1.join()
        t2.join()

        # One worker should succeed, the other should be rejected (acquired=False)
        statuses = [acquired for _, acquired in results]
        assert True in statuses
        assert False in statuses

    def test_independent_post_locks_do_not_conflict(self, db_session: Session):
        """Different posts can be processed simultaneously without contention."""
        with advisory_lock(db_session, post_id=201, operation="upload") as acq1:
            with advisory_lock(db_session, post_id=202, operation="upload") as acq2:
                assert acq1 is True
                assert acq2 is True

    def test_different_operations_on_same_post_do_not_conflict(self, db_session: Session):
        """Different operations on the same post (e.g. upload vs comment) can run independently."""
        with advisory_lock(db_session, post_id=301, operation="upload") as acq1:
            with advisory_lock(db_session, post_id=301, operation="comment") as acq2:
                assert acq1 is True
                assert acq2 is True

    def test_channel_lock_mutual_exclusion(self, db_session: Session):
        """Channel lock prevents two workers from uploading to the same channel simultaneously."""
        results = []

        def worker_task(worker_id: str):
            with channel_lock(db_session, channel_key="the_indian_kitchen", operation="upload") as acquired:
                results.append((worker_id, acquired))
                if acquired:
                    time.sleep(0.05)

        t1 = threading.Thread(target=worker_task, args=("worker-A",))
        t2 = threading.Thread(target=worker_task, args=("worker-B",))

        t1.start()
        time.sleep(0.01)
        t2.start()

        t1.join()
        t2.join()

        statuses = [acquired for _, acquired in results]
        assert True in statuses
        assert False in statuses


# ---------------------------------------------------------------------------
# 2. Worker Coordinator & Task Leasing Tests
# ---------------------------------------------------------------------------

class TestWorkerCoordinatorLeasing:
    def test_claim_next_job_success(self, db_session: Session):
        repo = JobRepository(db_session)
        j1 = repo.create(job_type=JobType.CLEAN, post_id=1)
        j2 = repo.create(job_type=JobType.YOUTUBE_UPLOAD, post_id=2)

        coordinator = WorkerCoordinator(db_session)
        claimed1 = coordinator.claim_next_job(worker_id="worker-node-1")
        assert claimed1 is not None
        assert claimed1.id == j1.id
        assert claimed1.status == JobStatus.RUNNING
        assert claimed1.worker_id == "worker-node-1"
        assert claimed1.started_at is not None

        # Next worker claims the second job
        claimed2 = coordinator.claim_next_job(worker_id="worker-node-2")
        assert claimed2 is not None
        assert claimed2.id == j2.id
        assert claimed2.status == JobStatus.RUNNING
        assert claimed2.worker_id == "worker-node-2"

        # Third attempt when queue is empty returns None
        claimed3 = coordinator.claim_next_job(worker_id="worker-node-3")
        assert claimed3 is None

    def test_claim_filtered_by_supported_types(self, db_session: Session):
        repo = JobRepository(db_session)
        repo.create(job_type=JobType.ASMR_WORKFLOW)
        j2 = repo.create(job_type=JobType.CLEAN, post_id=10)

        coordinator = WorkerCoordinator(db_session)
        # Worker only accepts CLEAN jobs
        claimed = coordinator.claim_next_job(
            worker_id="watermark-cleaner-1",
            supported_types=[JobType.CLEAN],
        )
        assert claimed is not None
        assert claimed.id == j2.id
        assert claimed.job_type == JobType.CLEAN

    def test_heartbeat_extends_lease(self, db_session: Session):
        repo = JobRepository(db_session)
        job = repo.create(job_type=JobType.YOUTUBE_UPLOAD, post_id=5)
        coordinator = WorkerCoordinator(db_session)
        claimed = coordinator.claim_next_job(worker_id="uploader-1")

        old_updated_at = claimed.updated_at
        time.sleep(0.01)

        ok = coordinator.heartbeat(job_id=claimed.id, worker_id="uploader-1")
        assert ok is True

        db_session.refresh(claimed)
        assert claimed.updated_at > old_updated_at

    def test_heartbeat_fails_for_wrong_worker(self, db_session: Session):
        repo = JobRepository(db_session)
        job = repo.create(job_type=JobType.YOUTUBE_UPLOAD, post_id=5)
        coordinator = WorkerCoordinator(db_session)
        claimed = coordinator.claim_next_job(worker_id="uploader-1")

        ok = coordinator.heartbeat(job_id=claimed.id, worker_id="imposter-worker")
        assert ok is False

    def test_graceful_release_job(self, db_session: Session):
        repo = JobRepository(db_session)
        job = repo.create(job_type=JobType.CLEAN, post_id=8)
        coordinator = WorkerCoordinator(db_session)
        claimed = coordinator.claim_next_job(worker_id="worker-terminating")

        # Worker receives SIGTERM and releases job
        released = coordinator.release_job(
            job_id=claimed.id,
            worker_id="worker-terminating",
            reason="SIGTERM received",
        )
        assert released is True

        db_session.refresh(claimed)
        assert claimed.status == JobStatus.CREATED
        assert claimed.worker_id is None
        assert claimed.started_at is None
        assert "SIGTERM" in claimed.error_message

        # Job can now be reclaimed by another worker
        reclaimed = coordinator.claim_next_job(worker_id="new-worker")
        assert reclaimed is not None
        assert reclaimed.id == claimed.id
        assert reclaimed.worker_id == "new-worker"


# ---------------------------------------------------------------------------
# 3. Zombie Reaper Tests
# ---------------------------------------------------------------------------

class TestZombieReaping:
    def test_reap_stale_job_under_max_attempts(self, db_session: Session):
        """A stale job with attempt 1 is reclaimed back to CREATED with attempt 2."""
        repo = JobRepository(db_session)
        job = repo.create(job_type=JobType.CLEAN, post_id=99, attempt=1)
        coordinator = WorkerCoordinator(db_session)
        claimed = coordinator.claim_next_job(worker_id="crashed-worker-1")

        # Artificially set updated_at to 15 minutes ago
        past = datetime.now(timezone.utc) - timedelta(minutes=15)
        claimed.updated_at = past
        claimed.started_at = past
        db_session.commit()

        result = coordinator.reap_stale_leases(stale_threshold_seconds=600, max_attempts=3)
        assert result["reaped_total"] == 1
        assert result["reclaimed_count"] == 1
        assert claimed.id in result["reclaimed_ids"]

        db_session.refresh(claimed)
        assert claimed.status == JobStatus.CREATED
        assert claimed.attempt == 2
        assert claimed.worker_id is None

    def test_reap_stale_job_exhausted_attempts_moves_to_dlq(self, db_session: Session):
        """A stale job that already reached max_attempts is moved to DEAD_LETTER."""
        repo = JobRepository(db_session)
        job = repo.create(job_type=JobType.CLEAN, post_id=99, attempt=3)
        coordinator = WorkerCoordinator(db_session)
        claimed = coordinator.claim_next_job(worker_id="crashed-worker-2")

        past = datetime.now(timezone.utc) - timedelta(minutes=15)
        claimed.updated_at = past
        claimed.started_at = past
        db_session.commit()

        result = coordinator.reap_stale_leases(stale_threshold_seconds=600, max_attempts=3)
        assert result["reaped_total"] == 1
        assert result["dead_letter_count"] == 1
        assert claimed.id in result["dead_letter_ids"]

        db_session.refresh(claimed)
        assert claimed.status == JobStatus.DEAD_LETTER
        assert "Zombie reaper" in claimed.error_message

    def test_fresh_job_is_not_reaped(self, db_session: Session):
        """A running job with a fresh heartbeat is NOT reaped."""
        repo = JobRepository(db_session)
        job = repo.create(job_type=JobType.CLEAN, post_id=12)
        coordinator = WorkerCoordinator(db_session)
        claimed = coordinator.claim_next_job(worker_id="healthy-worker")

        result = coordinator.reap_stale_leases(stale_threshold_seconds=600)
        assert result["reaped_total"] == 0

        db_session.refresh(claimed)
        assert claimed.status == JobStatus.RUNNING


# ---------------------------------------------------------------------------
# 4. HTTP API Endpoints for Workers
# ---------------------------------------------------------------------------

class TestHTTPWorkerEndpoints:
    def test_http_claim_and_heartbeat_flow(self, test_client: TestClient, db_session: Session):
        repo = JobRepository(db_session)
        j = repo.create(job_type=JobType.YOUTUBE_UPLOAD, post_id=77)

        # 1. Claim job via API
        claim_resp = test_client.post(
            "/api/jobs/claim",
            json={"worker_id": "pod-worker-alpha"},
        )
        assert claim_resp.status_code == 200
        claimed_data = claim_resp.json()
        assert claimed_data["id"] == j.id
        assert claimed_data["worker_id"] == "pod-worker-alpha"
        assert claimed_data["status"] == "running"

        # 2. Heartbeat via API
        hb_resp = test_client.post(
            f"/api/jobs/{j.id}/heartbeat",
            json={"worker_id": "pod-worker-alpha"},
        )
        assert hb_resp.status_code == 200
        assert hb_resp.json()["refreshed"] is True

        # 3. Imposter heartbeat rejected with 409
        imposter_resp = test_client.post(
            f"/api/jobs/{j.id}/heartbeat",
            json={"worker_id": "imposter"},
        )
        assert imposter_resp.status_code == 409

        # 4. Release job via API
        rel_resp = test_client.post(
            f"/api/jobs/{j.id}/release",
            json={"worker_id": "pod-worker-alpha", "reason": "pod_eviction"},
        )
        assert rel_resp.status_code == 200
        assert rel_resp.json()["released"] is True

    def test_http_active_workers_and_reap(self, test_client: TestClient, db_session: Session):
        repo = JobRepository(db_session)
        j = repo.create(job_type=JobType.COMMENT, post_id=88)
        coordinator = WorkerCoordinator(db_session)
        claimed = coordinator.claim_next_job(worker_id="node-worker-9")

        # Check active workers
        resp = test_client.get("/api/jobs/active-workers")
        assert resp.status_code == 200
        workers = resp.json()
        assert any(w["worker_id"] == "node-worker-9" and w["active_jobs"] == 1 for w in workers)

        # Trigger reap-stale
        reap_resp = test_client.post("/api/jobs/reap-stale?stale_seconds=10")
        assert reap_resp.status_code == 200
        assert "reaped_total" in reap_resp.json()
