# Production Migration Plan — posting_pipeline

> Phase-by-phase migration from current architecture to production-grade system.
> Each phase is independently deployable. Previous functionality is preserved throughout.

---

## Pre-Migration Checklist

Before starting ANY phase:
- [ ] Take a database backup (Render Dashboard > Database > Backups)
- [ ] Confirm alembic upgrade head runs cleanly on a test DB
- [ ] Confirm all existing tests pass on current main branch
- [ ] Document current Render environment variables

---

## Phase 1 — COMPLETE: Baseline + Critical Fixes (DONE)

**Status: IMPLEMENTED** (this session)

### Changes Made

| File | Change |
|------|--------|
| backend/domain/states.py | NEW — formal post state machine with legal transitions |
| backend/domain/errors.py | NEW — domain error hierarchy |
| backend/services/idempotency.py | NEW — DB-backed idempotency service |
| backend/services/distributed_lock.py | NEW — PostgreSQL advisory locks |
| backend/middleware/security.py | NEW — security headers middleware |
| backend/middleware/rate_limit.py | NEW — per-IP rate limiting |
| backend/schemas_pagination.py | NEW — pagination utilities |
| backend/models.py | MODIFIED — added PostIdempotencyRecord model |
| backend/jobs/upload_job.py | MODIFIED — idempotency integrated into YouTube upload |
| backend/main.py | MODIFIED — removed create_all(), removed thread storm, added middleware |
| alembic/versions/0005_idempotency.py | NEW — migration for idempotency table + indexes |
| backend/tests/test_state_machine.py | NEW — 43 state machine tests |
| backend/tests/test_idempotency.py | NEW — 21 idempotency tests |
| docs/current-architecture.md | NEW — architecture audit document |

### Critical Bugs Fixed
1. Base.metadata.create_all() removed from production lifespan
2. Startup thread storm (Drive upload threads) eliminated
3. YouTube duplicate-upload protection via idempotency service
4. Rate limiting on login, upload, and API endpoints
5. Security headers on all responses
6. Liveness/readiness health endpoints separated

---

## Phase 2 — Data Model (Next Steps)

### Goal
Strengthen database model — separate job tracking from post business state.

### Steps
1. Add Jobs table (separate from Posts) for execution tracking
2. Add composite indexes from migration 0005 (done)
3. Add RefreshToken table for server-side session revocation
4. Add AuditLog table for admin actions
5. Verify Alembic baseline covers all tables

### Migration
`
alembic revision --autogenerate -m "0006_jobs_and_tokens"
alembic upgrade head
`

### Verification
`
python -m pytest backend/tests/
alembic downgrade -1
alembic upgrade head
`

---

## Phase 3 — Application Architecture

### Goal
Repository pattern + application services layer.

### Steps
1. Create backend/repositories/ (PostRepository, JobRepository, EventRepository)
2. Move DB queries from routers into repositories
3. Create backend/application/ (CreatePostService, PublishYouTubeService, etc.)
4. Migrate routers to use service layer

### Key Rule
DO NOT break existing API contracts.
Add repositories as new layer, keep existing router logic working in parallel.

---

## Phase 4 — Worker Architecture (Redis + Celery)

### Goal
Replace APScheduler + threading.Thread with durable Redis-backed Celery workers.

### Prerequisite
Add Redis to Render deployment (managed Redis add-on or Redis Cloud).

### Steps
1. Add celery, redis to requirements.txt
2. Create backend/workers/ (celery app + worker definitions)
3. Port serial queue steps to Celery tasks
4. Deploy worker as separate Render service
5. Test with multiple worker instances

### Render Config Changes
Add to render.yaml:
`yaml
- type: worker
  name: posting-pipeline-worker
  startCommand: celery -A backend.workers.app worker -l info -Q video,ai,publish,sync
`

### Rollback Plan
APScheduler remains in place until Celery workers are verified.
Set a feature flag to route tasks to Celery or old scheduler.

---

## Phase 5 — Reliability

### Goal
Exponential backoff, DLQ, stale job recovery, circuit breakers.

### Changes
1. Enhance retry.py with jitter (currently fixed backoff)
2. Add dead_letter status to Post state machine
3. Create periodic maintenance job for stale lock recovery
4. Add basic circuit breaker for YouTube/Instagram

---

## Phase 6 — Security Hardening

### Goal
Stateful refresh tokens, RBAC, upload security audit.

### Steps
1. Add RefreshToken table (migration)
2. Update auth.py to persist and revoke refresh tokens
3. Add RBAC roles (ADMIN / OPERATOR / VIEWER)
4. Audit upload endpoint file validation (MIME, magic bytes, size)
5. Review SSH command construction for injection vectors
6. Rotate service_account.json out of repository

### Critical: service_account.json
This file MUST be removed from the repository and moved to an environment
variable (JSON as string) or a secret store.

Action:
`ash
git rm --cached service_account.json backend/service_account.json
echo "service_account.json" >> .gitignore
# Then set GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON env var to the JSON content
`

---

## Phase 7 — Observability

### Goal
Structured JSON logging, request correlation IDs, metrics.

### Steps
1. Replace basicConfig() with structlog or python-json-logger
2. Add X-Request-ID middleware
3. Expose /metrics endpoint (prometheus_fastapi_instrumentator)
4. Add LLM usage tracking

---

## Phase 8 — Storage

### Goal
Object storage abstraction — stop depending on local disk as sole storage.

### Steps
1. Create StorageBackend Protocol
2. Implement GoogleDriveStorageBackend (existing)
3. Implement LocalStorageBackend (existing local files)
4. Add streaming upload support
5. Document media lifecycle

---

## Phase 9 — Frontend

### Goal
TypeScript migration, typed API client, job status UI.

### Steps
1. Generate TypeScript types from OpenAPI schema
2. Create typed API client (replaces scattered axios calls)
3. Add workflow timeline view per post
4. Add DLQ management UI
5. Add pagination to posts list

---

## Phase 10 — CI/CD

### Goal
GitHub Actions pipeline with linting, tests, security scanning.

### Steps
1. Create .github/workflows/ci.yml
2. Add ruff linting step
3. Add pytest step with coverage gate (>= 70%)
4. Add dependency vulnerability scan (pip-audit)
5. Add Docker build step

---

## Verification Commands (Run After Each Phase)

`powershell
# Syntax check
python -m py_compile backend/main.py backend/models.py backend/jobs/upload_job.py

# Core tests (no external deps)
python -m pytest backend/tests/test_state_machine.py backend/tests/test_idempotency.py backend/tests/test_retry_system.py backend/tests/test_seo_validation.py -v

# Migration test (requires DB)
alembic upgrade head
alembic downgrade -1
alembic upgrade head

# Import verification
python -c "from backend.main import app; print('OK')"
python -c "from backend.domain.states import PostStatus; print('OK')"
python -c "from backend.services.idempotency import IdempotencyService; print('OK')"
python -c "from backend.middleware.security import add_security_headers; print('OK')"
python -c "from backend.middleware.rate_limit import RateLimitMiddleware; print('OK')"
`

---

## Rollback Instructions

### For Phase 1 (current)
All changes are additive. To rollback:

1. Revert main.py (add back create_all, remove middleware imports)
2. Revert upload_job.py (remove idempotency imports)
3. Run: alembic downgrade -1 (removes idempotency table and indexes)
4. Delete: backend/domain/, backend/middleware/, backend/services/idempotency.py, backend/services/distributed_lock.py

The post_idempotency_records table is safe to drop — it only exists to prevent duplicates, not store core business data.

---

## Known Remaining Limitations (Post Phase 1)

| Limitation | Phase to Fix |
|------------|--------------|
| In-process threading.Lock still used in job_queue.py | Phase 4 |
| No server-side refresh token revocation | Phase 6 |
| No RBAC beyond single admin | Phase 6 |
| service_account.json in repository | Phase 6 (URGENT) |
| No structured JSON logging | Phase 7 |
| No DLQ management UI | Phase 9 |
| No CI/CD pipeline | Phase 10 |
| Rate limiter is in-memory (not Redis-backed) | Phase 4 |
| No LLM cost tracking | Phase 7 |
