#!/bin/bash
# Serve the app on the demo database (port 8001) with notices written to a local mailbox.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/../.."
. "$HERE/demo.env.sh"
exec .venv/bin/gunicorn -b 127.0.0.1:8001 -w 2 --timeout 120 wsgi:app
