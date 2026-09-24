# =============================================================================
# STAGE 1: Frontend Build (Node.js 20 Alpine)
# =============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Install dependencies with caching
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

# Build production bundle
COPY frontend/ ./
RUN npm run build


# =============================================================================
# STAGE 2: Backend & Production Runtime (Python 3.11-slim)
# =============================================================================
FROM python:3.11-slim AS runtime

# Set environment defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    TIMEZONE=Asia/Kolkata \
    UPLOAD_DIR=/app/data/uploads \
    PROCESSED_DIR=/app/data/processed \
    LOG_DIR=/app/data/logs

# Install minimal OS dependencies: ffmpeg (video processing), curl (healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create non-root application user for container security
RUN groupadd -g 1001 appgroup && \
    useradd -u 1001 -g appgroup -m -s /bin/bash appuser

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend application and database migration configurations
COPY backend/ ./backend/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Copy built frontend assets from Stage 1 into frontend/dist for static serving
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create required directories and set proper ownership
RUN mkdir -p /app/data/uploads /app/data/processed /app/data/logs && \
    chown -R appuser:appgroup /app

# Switch to unprivileged user
USER appuser

# Expose HTTP port
EXPOSE 8000

# Container healthcheck probe (uses FastAPI liveness probe)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health/live || exit 1

# Launch production entrypoint
ENTRYPOINT ["./entrypoint.sh"]
