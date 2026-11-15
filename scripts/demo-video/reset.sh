#!/bin/bash
# Rebuild the demo database from scratch with fictional data only, and write demo.env.sh
# (database URL and fresh random demo passwords; ignored by git).
#
# Needs: a local PostgreSQL where PGADMIN_* (default: socket /tmp, user postgres) can create
# databases, Redis on 127.0.0.1:6379, and the repository's .env with DATABASE_URL.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"
DEMO_DB="${DEMO_DB:-recalltrace_video}"
BASE_URL="${DATABASE_URL:-$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-)}"
# Same server and login as the development database, different database name.
read -r DEMO_URL DB_OWNER < <(.venv/bin/python - "$BASE_URL" "$DEMO_DB" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit
url, name = sys.argv[1], sys.argv[2]
parts = urlsplit(url)
print(urlunsplit(parts._replace(path="/" + name)), parts.username)
PY
)
export PGHOST="${PGADMIN_HOST:-/tmp}" PGUSER="${PGADMIN_USER:-postgres}"
psql -qc "DROP DATABASE IF EXISTS $DEMO_DB WITH (FORCE)"
psql -qc "CREATE DATABASE $DEMO_DB OWNER \"$DB_OWNER\""
unset PGHOST PGUSER
OWNER_PW="demo-$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(18))')"
REVIEWER_PW="demo-$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(18))')"
umask 077
cat > "$HERE/demo.env.sh" <<ENV
export DATABASE_URL='$DEMO_URL'
export SESSION_REDIS_URL=redis://127.0.0.1:6379/3
export ACCOUNT_MAIL_DIR=video-mail
export MAIL_MODE=local
export DEMO_OWNER_PASSWORD='$OWNER_PW'
export DEMO_REVIEWER_PASSWORD='$REVIEWER_PW'
ENV
. "$HERE/demo.env.sh"
redis-cli -n 3 flushdb >/dev/null
rm -rf instance/video-mail
F=".venv/bin/flask --app wsgi:app"
$F db upgrade >/dev/null 2>&1
$F create-company --name "Harbourline Foods (demo)" --slug video-demo >/dev/null
$F create-owner --company video-demo --email owner@video-demo.test --password "$OWNER_PW" >/dev/null
$F init-business --company video-demo >/dev/null
$F seed-investigation-demo --company video-demo --owner-email owner@video-demo.test >/dev/null
$F seed-demo-extras --company video-demo >/dev/null
$F seed-factory-demo --owner-of video-demo >/dev/null
rm -rf "$HERE/out"
echo "Demo database $DEMO_DB ready. Start the server with ./serve.sh, then ./run.sh."
