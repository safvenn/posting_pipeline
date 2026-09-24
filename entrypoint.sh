#!/bin/sh
set -e

echo "=== YouTube Auto Pipeline Container Starting ==="
echo "Port: ${PORT:-8000}"
echo "Timezone: ${TIMEZONE:-Asia/Kolkata}"

# Run Alembic database migrations automatically before traffic serving
if [ -n "$DATABASE_URL" ]; then
    echo "Running Alembic database migrations..."
    alembic upgrade head || {
        echo "WARNING: Alembic migration encountered an error or already up to date. Continuing..."
    }
fi

# Graceful termination handler
trap 'echo "SIGTERM/SIGINT received. Shutting down gracefully..."; kill -TERM "$child" 2>/dev/null' TERM INT

# Start Uvicorn ASGI server
uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --lifespan on \
    --access-log \
    --log-config /dev/null &

child=$!
wait "$child"
