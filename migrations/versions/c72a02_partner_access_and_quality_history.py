"""Partner invitation scope and immutable quality/trace snapshots.

Revision ID: c72a02
Revises: c72a01
"""

import sqlalchemy as sa
from alembic import op

revision = "c72a02"
down_revision = "c72a01"
branch_labels = None
depends_on = None

EVENTS = ("case_comments", "trace_runs", "trace_results")
PARENTS = ("inspection_templates", "inspections")
CHILDREN = (
    ("inspection_checks", "inspection_templates", "template_id"),
    ("inspection_results", "inspections", "inspection_id"),
)


def upgrade():
    op.add_column("invitations", sa.Column("partner_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_invitations_organization_id_partner_id_partners",
        "invitations",
        "partners",
        ["organization_id", "partner_id"],
        ["organization_id", "id"],
    )
    for table in EVENTS:
        op.execute(
            f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION recalltrace_history_guard()"
        )
    for table in PARENTS:
        op.execute(
            f"CREATE TRIGGER draft_document BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION recalltrace_document_guard()"
        )
    for table, parent, field in CHILDREN:
        op.execute(
            f"CREATE TRIGGER draft_lines BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION recalltrace_child_guard('{parent}', '{field}')"
        )


def downgrade():
    for table, _, _ in CHILDREN:
        op.execute(f"DROP TRIGGER draft_lines ON {table}")
    for table in PARENTS:
        op.execute(f"DROP TRIGGER draft_document ON {table}")
    for table in EVENTS:
        op.execute(f"DROP TRIGGER immutable_history ON {table}")
    op.drop_constraint(
        "fk_invitations_organization_id_partner_id_partners", "invitations", type_="foreignkey"
    )
    op.drop_column("invitations", "partner_id")
