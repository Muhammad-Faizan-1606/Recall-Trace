#!/usr/bin/env bash
set -euo pipefail
# DATABASE_URL belongs in a protected process environment or managed secret binding.
# Use the project interpreter without putting a connection string in process arguments.
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${RECALLTRACE_PYTHON:-}" ]]; then
  interpreter="$RECALLTRACE_PYTHON"
elif [[ -x "$script_dir/../.venv/bin/python" ]]; then
  interpreter="$script_dir/../.venv/bin/python"
else
  interpreter=python3
fi
exec "$interpreter" "$script_dir/restore_verify.py" backup "$@"
