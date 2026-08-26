#!/usr/bin/env bash
# start-backend.sh — activate venv and launch FastAPI
set -e
cd "$(dirname "$0")"
source venv/bin/activate
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
