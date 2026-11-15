#!/bin/bash
# ./snap.sh save NAME | ./snap.sh load NAME
# Snapshot the demo database and run state, to retry later chapters without replaying the
# earlier ones while editing the script. Sessions stay in Redis.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEMO_DB="${DEMO_DB:-recalltrace_video}"
. "$HERE/demo.env.sh"
OWNER="$(cd "$HERE/../.." && .venv/bin/python -c 'import os; from urllib.parse import urlsplit; print(urlsplit(os.environ["DATABASE_URL"]).username)')"
export PGHOST="${PGADMIN_HOST:-/tmp}" PGUSER="${PGADMIN_USER:-postgres}"
mkdir -p "$HERE/snapshots"
if [ "$1" = save ]; then
  pg_dump -Fc "$DEMO_DB" > "$HERE/snapshots/$2.dump"
  mkdir -p "$HERE/snapshots/$2" && cp "$HERE"/out/*.json "$HERE/snapshots/$2/"
else
  psql -qc "DROP DATABASE IF EXISTS $DEMO_DB WITH (FORCE)"
  psql -qc "CREATE DATABASE $DEMO_DB OWNER \"$OWNER\""
  pg_restore -d "$DEMO_DB" --no-owner --role="$OWNER" "$HERE/snapshots/$2.dump"
  mkdir -p "$HERE/out" && cp "$HERE/snapshots/$2"/*.json "$HERE/out/"
fi
echo "snapshot $1 $2 done"
