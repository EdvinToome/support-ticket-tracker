#!/usr/bin/env bash
set -euo pipefail
uv run --no-sync python manage.py migrate --noinput
uv run --no-sync python manage.py createcachetable
exec uv run --no-sync gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" --workers 2 --threads 4 --timeout 30 \
  --access-logfile - --error-logfile -
