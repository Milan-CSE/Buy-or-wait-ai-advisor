#!/bin/sh
set -e

python -m alembic upgrade head

exec python -m uvicorn backend.api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \
  --no-access-log