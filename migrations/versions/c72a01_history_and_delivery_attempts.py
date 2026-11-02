"""Protect posted history and retain independently recorded delivery attempts.

Revision ID: c72a01
Revises: a25c70d62f52
"""

from alembic import op

revision = "c72a01"
down_revision = "a25c70d62f52"
branch_labels = None
depends_on = None

EVENTS = (
    "audit_events",
    "stock_transactions",
    "stock_transaction_lines",
    "shipment_events",
    "hold_reviews",
    "notice_acknowledgements",
    "recovery_records",
)
DOCUMENTS = (
    "purchase_orders",
    "goods_receipts",
    "production_runs",
    "sales_orders",
    "shipments",
    "stock_transfers",
)
CHILDREN = (
    ("purchase_order_lines", "purchase_orders", "purchase_order_id"),
    ("goods_receipt_lines", "goods_receipts", "receipt_id"),
    ("production_inputs", "production_runs", "production_run_id"),
    ("production_outputs", "production_runs", "production_run_id"),
    ("sales_order_lines", "sales_orders", "sales_order_id"),
    ("shipment_lines", "shipments", "shipment_id"),
    ("stock_transfer_lines", "stock_transfers", "transfer_id"),
)


def upgrade():
    op.drop_constraint(
        "uq_notice_deliveries_organization_id_idempotency_key", "notice_deliveries", type_="unique"
    )
    op.execute("""
        CREATE FUNCTION recalltrace_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'Posted history is immutable; use a compensating workflow'
            USING ERRCODE = '23514';
        END $$
    """)
    op.execute("""
        CREATE FUNCTION recalltrace_document_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'Only draft business documents may change'
              USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION recalltrace_child_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_state text; row_data jsonb;
        BEGIN
          IF TG_OP = 'DELETE' THEN row_data := to_jsonb(OLD);
          ELSE row_data := to_jsonb(NEW); END IF;
          EXECUTE format('SELECT status FROM %I WHERE id = $1 AND organization_id = $2 FOR UPDATE', TG_ARGV[0])
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
    for table in EVENTS:
        op.execute(
            f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION recalltrace_history_guard()"
        )
    for table in DOCUMENTS:
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
    for table in DOCUMENTS:
        op.execute(f"DROP TRIGGER draft_document ON {table}")
    for table in EVENTS:
        op.execute(f"DROP TRIGGER immutable_history ON {table}")
    op.execute("DROP FUNCTION recalltrace_child_guard()")
    op.execute("DROP FUNCTION recalltrace_document_guard()")
    op.execute("DROP FUNCTION recalltrace_history_guard()")
    # Multiple attempts deliberately share a provider key; restoring the old
    # uniqueness constraint requires operator reconciliation first.
    op.create_unique_constraint(
        "uq_notice_deliveries_organization_id_idempotency_key",
        "notice_deliveries",
        ["organization_id", "idempotency_key"],
    )
