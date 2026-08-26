# Posting Pipeline (Watermark Cleaner & Auto-Scheduler)

An automated YouTube and Instagram video posting pipeline with automated watermark removal, Google Sheets metadata syncing, Gemini AI enrichment, and scheduled publishing.

## Architecture

- **Backend**: FastAPI (Python 3.10+), SQLAlchemy + Alembic, APScheduler, Playwright, Google APIs, Gemini AI.
- **Frontend**: React + Vite + Tailwind CSS, deployed on Vercel or locally.

---

## Quick Start

### 1. Backend Setup

```bash
# Create virtual environment & install dependencies
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt

# Configure environment
cp backend/.env.example backend/.env
# (Fill in your credentials in backend/.env)

# Run migrations & start backend server
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

---

## Deployment

### Frontend (Vercel)
- Connect this repository to Vercel.
- Set Root Directory to `frontend`.
- Set Environment Variable: `VITE_API_URL=https://your-backend-api-url.com`.

### Backend
- Deploy on Railway, Render, Fly.io, or VPS.
- Set environment variables as documented in `backend/.env.example`.
