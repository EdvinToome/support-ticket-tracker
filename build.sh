#!/usr/bin/env bash
set -euo pipefail
python -m pip install uv==0.8.17
uv sync --frozen --no-dev
uv run --no-sync python manage.py collectstatic --noinput
