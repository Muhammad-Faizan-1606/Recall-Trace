"""Databases built from offline SQL (flask db upgrade --sql) must match online ones."""

import os
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from app.extensions import db

ROOT = Path(__file__).resolve().parents[1]


def _offline_sql():
    result = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "wsgi:app", "db", "upgrade", "base:head", "--sql"],
        cwd=ROOT,
        env={**os.environ, "APP_ENV": "testing"},
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return result.stdout


def test_final_offline_child_guard_has_no_escaped_format_placeholder():
    # Offline rendering escapes % to %%; the final guard body must not depend on %.
    bodies = re.findall(
        r"FUNCTION recalltrace_child_guard\(\).*?END \$\$", _offline_sql(), flags=re.S
    )
    assert bodies, "child guard definition missing from offline SQL"
    assert "%" not in bodies[-1]


def test_installed_child_guard_matches_percent_free_definition(app):
    with app.app_context():
        source = db.session.scalar(
            text("SELECT prosrc FROM pg_proc WHERE proname = 'recalltrace_child_guard'")
        )
    assert "quote_ident(TG_ARGV[0])" in source
    assert "%" not in source
