#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then
  export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/recalltrace-uv-cache}"
  uv venv --allow-existing --python python3.13 .venv
  uv pip sync --require-hashes --python .venv/bin/python requirements-dev.txt
else
  # Requires the Python 3.13 venv/ensurepip component on Debian/Ubuntu.
  python3.13 -m venv .venv
  .venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
fi
.venv/bin/python scripts/init_local.py
.venv/bin/python scripts/init_security.py
docker compose up -d --wait
.venv/bin/flask --app wsgi:app db upgrade
