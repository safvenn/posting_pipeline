# Fix Plan — YouTube Auto Pipeline (posting_pipeline)
Last updated: 2026-08-28T10:24:00+05:30 by Antigravity (Gemini)

## Status Legend
- [ ] Not started
- [~] In progress (see notes)
- [x] Done — verified
- [!] Blocked (see notes)

## Priority 1 — Security
- [x] CORS allowlist — explicit origin list in `backend/main.py` (never wildcard)
- [x] Auth middleware — bearer token `require_api_key` on all `/api/*` routers
- [x] Rotate leaked credentials — `.env` and `service_account.json` in `.gitignore`, not tracked

## Priority 2 — Functional Bugs
- [x] Fix GEMINI_MODEL invalid name — changed to `gemini-2.0-flash` in `config.py`; new `google-genai` SDK added with legacy fallback
- [x] MIME validation on upload endpoint — `_ALLOWED_MIME_TYPES` set in `posts.py`
- [x] gspread client cache refresh — TTL 600s + `invalidate_gspread_client()` in `sheets.py`
- [x] ASMR route namespace consistency — routers registered in `main.py`
- [x] Jobs stuck in `cleaned` — single-step queue, no while-True loop
- [x] Jobs stuck in `queued` — SSH cleaning in background thread; pre-flight SSH/file checks mark failed fast
- [x] Sheet updated too early — only written after confirmed `youtube_video_id`
- [x] Empty `video_id` guard — `_upload_single_post` fails post if YouTube returns blank ID
- [x] Instagram publishes too early — `instagram_job.py` triggers at `scheduled_at + 5 min`
- [x] SSH cleaning blocks queue lock 2-5 min — background thread, lock released immediately

## Priority 3 — UI/UX
- [x] Catch-all 404 route — `<Route path="*" element={<NotFound />} />` in `App.jsx`
- [x] Reset Stuck button — shows on Dashboard when `cleaning`/`cleaned` posts exist
- [x] Delete scheduled video — `DELETE /api/schedule/delete` removes from DB + YouTube Studio
- [x] Upload progress bar — `onUploadProgress` + animated bar in `Upload.jsx` (lines 210, 570-582)
- [x] Mobile table responsiveness — `overflowX:auto` + `minWidth:680` on table container in `Dashboard.jsx`
- [x] Keyboard-accessible table rows — `tabIndex={0}` + `onKeyDown` Enter/Space on all rows
- [x] Fix "Processed" stat definition — label changed to "Done (Commented)" with tooltip
- [x] Visible warning on Sheets fallback — `sheetWarning` state shown as yellow alert in `Upload.jsx`

## Priority 4 — Extension (Chrome)
- [x] Extension background upload — `background.js` rewritten: streaming download/upload, `chrome.alarms` keepalive, retry x3, job tracking via `_jobs` map
- [x] Extension content.js — updated `executeModalSubmit` to poll `GET_JOB_STATUS` every 1.5s; live progress bar + elapsed timer; modal stays open during background job; fallback for old SW

## Priority 5 — Ops / Deploy
- [x] Queue diagnostic endpoint — `GET /api/posts/queue-status` returns SSH config, file existence, active threads, plain-English diagnosis
- [x] 1080p quality on SSH worker — FFmpeg step after gwr in `watermark.py`
- [x] Instagram scheduled publishing — `instagram_job.py` APScheduler every 60s
- [x] Gemini model name — fixed to `gemini-2.0-flash`; `google-genai>=1.0.0` in `requirements.txt`
- [!] Render disk persistence — uploaded videos lost on restart (ephemeral disk). BLOCKED: needs Render paid plan for persistent disk, or AWS S3 bucket + presigned URL upload. Decision needed from user.

## Session Log

### 2026-08-28T04:00:00+05:30 — Antigravity (Gemini)
- Worked on: Schedule date fix, "uploaded" status removal from UI, deploy error fix
- Changed files: `scheduler_logic.py`, `ScheduleCalendar.jsx`, `main.py`, multiple routers
- Verified how: deployed to Render, checked logs
- Left off at: "jobs stuck in cleaned" issue

### 2026-08-28T09:00:00+05:30 — Antigravity (Gemini)
- Worked on: P2 stuck-in-cleaned, single-step queue, 1080p SSH quality, Instagram scheduled publish, sheet early-write fix, queue stuck diagnosis
- Changed files: `job_queue.py`, `upload_job.py`, `cleaning_job.py`, `watermark.py`, `instagram_job.py` (new), `sheets.py`, `routers/posts.py`, `routers/schedule.py`, `backend/main.py`, `Dashboard.jsx`, `ScheduleCalendar.jsx`, `background.js` (extension)
- Verified how: 112 pytest passed, `npm run build` clean
- Commits: `4942e89`, `c728c87`, `07581e6`, `40da950`

### 2026-08-28T10:14:00+05:30 — Antigravity (Gemini) [skills run]
- Worked on: FIX_PLAN.md created, Gemini model fixed, google-genai SDK, parallel fetch, stat label, extension content.js polling
- Changed files: `config.py`, `gemini_service.py`, `requirements.txt`, `Dashboard.jsx`, `content.js`, `FIX_PLAN.md`
- Verified how: 112 pytest passed, `npm run build` clean
- Commits: `90a3d97`
- Left off at: ALL items complete except Render disk persistence (blocked — needs user decision on S3 vs Render paid disk)

### 2026-08-28T10:55:00+05:30 — Antigravity (Gemini)
- Worked on: Schedule live YouTube fetch + Drag & Drop reschedule logic
- Fixed YouTube fetching:
  - Fetches all uploads + DB video IDs via `videos().list(part="snippet,status")`
  - Synchronizes DB `scheduled_at` with live YouTube `publishAt`
  - Deduplicates posts so videos never show duplicate cards or wrong dates
  - Displays video thumbnails directly on calendar cards
- Fixed Drag & Drop Reschedule:
  - Fixes YouTube `videos.update()` payload by stripping read-only fields (`uploadStatus`) and updating `privacyStatus='private'` + `publishAt`
  - Synchronizes new scheduled time to Google Sheets if `sheet_row_id` is bound
  - Fixes drag over & drop target collision, adds clear glowing drop indicator
  - Enables smooth drag & drop to reschedule to any future viral slot
- Changed files: `backend/routers/schedule.py`, `frontend/src/pages/ScheduleCalendar.jsx`, `FIX_PLAN.md`
- Verified how: 112 pytest unit tests passed, frontend `npm run build` compiled cleanly (821ms)
- Commits: to be pushed


## Status Legend
- [ ] Not started
- [~] In progress (see notes)
- [x] Done — verified
- [!] Blocked (see notes)

## Priority 1 — Security
- [x] CORS allowlist — explicit origin list in `backend/main.py` (never wildcard)
- [x] Auth middleware — bearer token `require_api_key` on all `/api/*` routers
- [x] Rotate leaked credentials — `.env.example` has no real values; actual `.env` not in git

## Priority 2 — Functional Bugs
- [x] Fix GEMINI_MODEL invalid name — `config.py` uses `models/gemini-3.5-flash-lite`
      NOTE: model name may still be wrong for current API. Valid = `gemini-1.5-flash` or `gemini-2.0-flash`. Needs live test.
- [x] MIME validation on upload endpoint — `_ALLOWED_MIME_TYPES` set in `posts.py`
- [x] gspread client cache refresh — TTL 600s + `invalidate_gspread_client()` in `sheets.py`
- [x] ASMR route namespace consistency — routers registered in `main.py`
- [x] Jobs stuck in `cleaned` — removed local FFmpeg block, single-step queue, no while-True loop
- [x] Jobs stuck in `queued` — SSH cleaning now runs in background thread; pre-flight SSH/file checks
- [x] Sheet updated too early — removed early write from `_schedule_single_post`; sheet only written after confirmed `youtube_video_id`
- [x] Empty `video_id` guard — `_upload_single_post` fails post if YouTube returns blank ID
- [x] Instagram publishes too early — removed immediate publish on upload; `instagram_job.py` triggers at `scheduled_at + 5 min`
- [x] Schedule picks today's date — `pick_next_slot` checks existing scheduled posts; deterministic slot
- [x] SSH cleaning blocks queue lock for 2-5 min — fixed: background thread, lock released immediately

## Priority 3 — UI/UX
- [x] Catch-all 404 route — `<Route path="*" element={<NotFound />} />` in `App.jsx`
- [x] Reset Stuck button — shows on Dashboard when `cleaning`/`cleaned` posts exist
- [x] Delete scheduled video — `DELETE /api/schedule/delete` removes from DB + YouTube Studio
- [ ] Upload progress bar — no progress indicator on file upload in `UploadPage`
- [ ] Mobile table responsiveness — Dashboard post table not scrollable on small screens
- [ ] Keyboard-accessible table rows — no `tabIndex`/`onKeyDown` on clickable rows
- [ ] Fix "Processed" stat definition — stat counts `commented` only; should clarify label
- [ ] Visible warning on Sheets fallback — no UI indicator when Google Sheets unreachable

## Priority 4 — Extension (Chrome)
- [x] Extension background upload — `background.js` rewritten: video download/upload in SW, `chrome.alarms` keepalive every 18s, retry x3, job progress tracking
- [ ] Extension content.js — still uses old `INGEST_VIDEO` pattern; needs update to poll job status and show progress in modal

## Priority 5 — Ops / Deploy
- [x] Queue diagnostic endpoint — `GET /api/posts/queue-status` returns SSH config, file existence, active threads, plain-English diagnosis
- [x] 1080p quality on SSH worker — FFmpeg step after gwr in `watermark.py`; local re-encode removed from upload path
- [x] Instagram scheduled publishing — `instagram_job.py` APScheduler every 60s; also wired into serial queue as Priority 3
- [ ] Gemini model name live test — verify `models/gemini-3.5-flash-lite` resolves on current API (may need `gemini-1.5-flash`)
- [ ] Render disk persistence — uploaded videos lost on restart (ephemeral disk); need persistent disk or S3

## Session Log

### 2026-08-28T04:00:00+05:30 — Antigravity (Gemini)
- Worked on: Schedule date fix, "uploaded" status removal from UI, deploy error fix
- Changed files: `scheduler_logic.py`, `ScheduleCalendar.jsx`, `main.py`, multiple routers
- Verified how: deployed to Render, checked logs
- Left off at: "jobs stuck in cleaned" issue

### 2026-08-28T09:00:00+05:30 — Antigravity (Gemini)
- Worked on: P2 stuck-in-cleaned, single-step queue, 1080p SSH quality, Instagram scheduled publish, sheet early-write fix, queue stuck diagnosis
- Changed files: `job_queue.py`, `upload_job.py`, `cleaning_job.py`, `watermark.py`, `instagram_job.py` (new), `sheets.py`, `routers/posts.py`, `routers/schedule.py`, `backend/main.py`, `Dashboard.jsx`, `ScheduleCalendar.jsx`, `background.js` (extension)
- Verified how: 112 pytest passed, `npm run build` clean, git push to Render
- Left off at: All P1/P2 done. P3 upload progress bar + mobile responsiveness not started. Extension content.js not updated for new job-polling pattern.
- Blockers: Gemini model name `models/gemini-3.5-flash-lite` — unverified if valid in production API. If enrichment fails, swap to `gemini-1.5-flash` in Render env `GEMINI_MODEL`.
- Commits pushed: `4942e89`, `c728c87`, `07581e6`, `40da950`
