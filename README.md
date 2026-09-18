# YouTube Auto-Post Pipeline

A production-ready FastAPI + React pipeline that automates the full YouTube Shorts publishing workflow — from raw video to scheduled YouTube upload, Google Sheet sync, and Instagram Reels cross-posting.

---

## Architecture

```
Raw Video (file upload / Chrome Extension)
        │
        ▼
┌─────────────────────────────┐
│  FastAPI Backend            │
│  (Render + PostgreSQL/SQLite)│
│                             │
│  Serial Job Queue (30s tick)│
│  1. queued → watermark clean│ SSH to GPU Server
│  2. cleaned → Gemini enrich │ Gemini Flash Lite
│  3. scheduled → YT upload   │ YouTube Data API v3
│  4. uploaded → first comment│
│  5. scheduled → Instagram   │ Meta Graph API
└─────────────────────────────┘
        │
        ▼
Google Sheets ← sync scheduled_at + upload_id + enriched title
```

### Key Services

| Service | File | Purpose |
|---------|------|---------|
| Job Queue | backend/jobs/job_queue.py | Serial APScheduler runner |
| Cleaning | backend/jobs/cleaning_job.py | SSH watermark removal |
| Enrichment | backend/services/enrichment.py | Gemini AI SEO content |
| Upload | backend/jobs/upload_job.py | YouTube upload + sheet sync |
| Instagram | backend/services/instagram.py | Meta Graph API Reels |
| Sheets | backend/services/sheets.py | Google Sheets CRUD |

---

## Setup

### Backend

```bash
cd watermark-pipeline
pip install -r requirements.txt
cp .env.example .env
python main.py
```

### Frontend

```bash
cd watermark-pipeline/frontend
npm install
npm run dev
```

### Chrome Extension

Load Unpacked from chrome-extension/ directory in chrome://extensions

---

## Environment Variables

```
DATABASE_URL=sqlite:///./pipeline.db
CHANNEL_A_CLIENT_ID=xxx
CHANNEL_A_CLIENT_SECRET=xxx
CHANNEL_A_REFRESH_TOKEN=xxx
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
SHEET_ID_CHANNEL_A=...
GEMINI_API_KEY=AIzaSy...
GEMINI_MODEL=gemini-2.0-flash-lite
INSTAGRAM_ACCOUNT_ID_CHANNEL_A=17841400...
INSTAGRAM_ACCESS_TOKEN_CHANNEL_A=EAAxx...
INSTAGRAM_ENABLED_CHANNEL_A=true
SSH_HOST=your.gpu.server.com
SSH_USER=ubuntu
SSH_KEY_PATH=/path/to/key.pem
RENDER_EXTERNAL_URL=https://your-app.onrender.com
API_KEY=your-api-key-here
TIMEZONE=Asia/Kolkata
```

---

## API Endpoints

### Posts
- POST /api/posts — Create post (multipart upload)
- GET /api/posts — List all posts
- GET /api/posts/{id} — Get post details
- GET /api/posts/{id}/video — Stream video file (public)
- GET /api/posts/sheet-rows?channel=&unscheduled_only=true — Sheet rows
- GET /api/posts/sheet-row?channel=&row_id= — Specific sheet row
- POST /api/posts/{id}/reset — Reset post to retry

### Schedule
- GET /api/schedule?days=7 — Calendar slots
- POST /api/schedule/{id}/reschedule — Drag-and-drop reschedule
- DELETE /api/schedule/{id} — Delete scheduled video

### Extension
- GET /api/extension/channels — Active channels
- GET /api/extension/sheet-rows?channel=&unscheduled_only=true — Sheet rows
- POST /api/extension/ingest — Ingest video from extension

---

## Key Fixes (Latest Session)

### 1. Instagram Ephemeral Disk Fix
After YouTube upload succeeds (video file still on disk), Instagram container is pre-created and container_id stored in DB. At publish time, container_id is used directly — no video file needed. Falls back to public RENDER_EXTERNAL_URL if container expired.

### 2. YouTube Title SEO
All titles enforced before upload:
- Primary tag from enriched_tags embedded in title
- #shorts suffix added if missing
- Hard cap at 100 chars (YouTube limit)

### 3. Failed Job Schedule Cleanup
On upload failure: post.scheduled_at cleared, Google Sheet row cleared (scheduled + upload id set to empty). No ghost slots in calendar.

### 4. Upload Page — Unscheduled Filter
Sheet row dropdown shows only unscheduled rows by default. Toggle to "Show All Rows" available.

### 5. Extension — Unscheduled Filter
Extension popup matches Upload page behavior with same toggle.

---

## Project Structure

```
watermark-pipeline/
├── backend/
│   ├── main.py
│   ├── models.py
│   ├── jobs/
│   │   ├── job_queue.py
│   │   ├── upload_job.py
│   │   ├── cleaning_job.py
│   │   ├── comment_job.py
│   │   └── instagram_job.py
│   ├── services/
│   │   ├── enrichment.py
│   │   ├── instagram.py
│   │   ├── sheets.py
│   │   └── watermark.py
│   └── routers/
│       ├── posts.py
│       ├── schedule.py
│       ├── extension.py
│       └── channels.py
├── frontend/src/
│   └── pages/
│       ├── Upload.jsx
│       ├── Dashboard.jsx
│       ├── ScheduleCalendar.jsx
│       └── PostDetail.jsx
└── chrome-extension/
    ├── background.js
    ├── popup.js
    └── popup.html
```
