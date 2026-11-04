"""Rebuild the draft-line guard without a percent sign.

The c72a01 body used format('... %I ...'). Offline rendering (flask db upgrade --sql)
escapes that to %%I, so a database built from offline SQL received a guard that
EXECUTEs the literal text "%I" and rejects every document-line insert, update and
delete. quote_ident concatenation has identical semantics and renders the same way
online and offline. CREATE OR REPLACE keeps the function's owner, grants and the
existing draft_lines triggers.

Revision ID: c72a04
Revises: c72a03
"""

from alembic import op

revision = "c72a04"
down_revision = "c72a03"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION recalltrace_child_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_state text; row_data jsonb;
        BEGIN
          IF TG_OP = 'DELETE' THEN row_data := to_jsonb(OLD);
          ELSE row_data := to_jsonb(NEW); END IF;
          EXECUTE 'SELECT status FROM ' || quote_ident(TG_ARGV[0])
            || ' WHERE id = $1 AND organization_id = $2 FOR UPDATE'
            INTO parent_state USING (row_data ->> TG_ARGV[1])::uuid, (row_data ->> 'organization_id')::uuid;
          IF parent_state IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'Posted document lines are immutable'
              USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'UPDATE' AND (to_jsonb(OLD) ->> TG_ARGV[1]) IS DISTINCT FROM (row_data ->> TG_ARGV[1]) THEN
            RAISE EXCEPTION 'Document lines cannot be moved between parents'
              USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
    """)


def downgrade():
    # The previous body is functionally identical when applied online; keep this one.
    pass
