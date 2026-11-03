"""Allow encrypted global account requests without weakening tenant job scope.

Revision ID: c72a03
Revises: c72a02
"""

import sqlalchemy as sa
from alembic import op

revision = "c72a03"
down_revision = "c72a02"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("job_outbox", "organization_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        op.f("ck_job_outbox_job_scope"),
        "job_outbox",
        "(kind = 'account.challenge' AND organization_id IS NULL AND created_by_id IS NULL) "
        "OR (kind <> 'account.challenge' AND organization_id IS NOT NULL)",
    )
    op.create_index(
        "uq_job_outbox_system_deduplication_key",
        "job_outbox",
        ["deduplication_key"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "ix_job_outbox_account_request_order",
        "job_outbox",
        [sa.text("(payload ->> 'request_key')"), "created_at", "id"],
        postgresql_where=sa.text("kind = 'account.challenge' AND organization_id IS NULL"),
    )


def downgrade():
    # Never erase security/delivery evidence to make a downgrade pass.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM job_outbox WHERE organization_id IS NULL) THEN
            RAISE EXCEPTION 'Account request history must be preserved before downgrade';
          END IF;
        END $$;
    """)
    op.drop_index("ix_job_outbox_account_request_order", table_name="job_outbox")
    op.drop_index("uq_job_outbox_system_deduplication_key", table_name="job_outbox")
    op.drop_constraint(op.f("ck_job_outbox_job_scope"), "job_outbox", type_="check")
    op.alter_column("job_outbox", "organization_id", existing_type=sa.Uuid(), nullable=False)
