"""Core operational documents, their owned lines and the immutable stock journal."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models import Owned, now


def tenant_fk(field, target):
    return ForeignKeyConstraint(
        ["organization_id", field], [f"{target}.organization_id", f"{target}.id"]
    )


def owned(*constraints):
    return (UniqueConstraint("organization_id", "id"), *constraints)


def positive():
    return CheckConstraint("quantity > 0", name="quantity_positive")


def document_constraints(*constraints):
    return owned(
        UniqueConstraint("organization_id", "reference"),
        CheckConstraint("status IN ('draft','posted','cancelled')", name="document_status"),
        *constraints,
    )


class StockTransaction(Owned, db.Model):
    __tablename__ = "stock_transactions"
    kind: Mapped[str] = mapped_column(db.String(30))
    status: Mapped[str] = mapped_column(db.String(20), default="posted")
    idempotency_key: Mapped[str] = mapped_column(db.String(100))
    payload_digest: Mapped[str] = mapped_column(db.String(64))
    posted_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), default=now)
    posted_by_id: Mapped[uuid.UUID | None]
    reverses_id: Mapped[uuid.UUID | None]
    __table_args__ = owned(
        UniqueConstraint("organization_id", "idempotency_key"),
        UniqueConstraint("organization_id", "reverses_id"),
        tenant_fk("posted_by_id", "memberships"),
        tenant_fk("reverses_id", "stock_transactions"),
        CheckConstraint("status = 'posted'", name="posted_only"),
    )


class StockTransactionLine(Owned, db.Model):
    __tablename__ = "stock_transaction_lines"
    quantity_delta: Mapped[Decimal] = mapped_column(db.Numeric(20, 6))
    transaction_id: Mapped[uuid.UUID]
    lot_id: Mapped[uuid.UUID]
    location_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("transaction_id", "stock_transactions"),
        tenant_fk("lot_id", "lots"),
        tenant_fk("location_id", "storage_locations"),
        CheckConstraint("quantity_delta <> 0", name="nonzero_delta"),
    )


class StockBalance(Owned, db.Model):
    __tablename__ = "stock_balances"
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(20, 6), default=Decimal("0"))
    lot_id: Mapped[uuid.UUID]
    location_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("lot_id", "lots"),
        tenant_fk("location_id", "storage_locations"),
        UniqueConstraint("organization_id", "lot_id", "location_id"),
        CheckConstraint("quantity >= 0", name="nonnegative_balance"),
    )


class StockTransfer(Owned, db.Model):
    __tablename__ = "stock_transfers"
    status: Mapped[str] = mapped_column(db.String(20), default="draft", server_default="draft")
    reference: Mapped[str] = mapped_column(db.String(80))
    source_warehouse_id: Mapped[uuid.UUID]
    destination_warehouse_id: Mapped[uuid.UUID]
    stock_transaction_id: Mapped[uuid.UUID | None]
    __table_args__ = document_constraints(
        tenant_fk("source_warehouse_id", "warehouses"),
        tenant_fk("destination_warehouse_id", "warehouses"),
        tenant_fk("stock_transaction_id", "stock_transactions"),
        CheckConstraint(
            "source_warehouse_id <> destination_warehouse_id", name="different_warehouses"
        ),
    )


class StockTransferLine(Owned, db.Model):
    __tablename__ = "stock_transfer_lines"
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(20, 6))
    transfer_id: Mapped[uuid.UUID]
    lot_id: Mapped[uuid.UUID]
    source_location_id: Mapped[uuid.UUID]
    destination_location_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        positive(),
        tenant_fk("transfer_id", "stock_transfers"),
        tenant_fk("lot_id", "lots"),
        tenant_fk("source_location_id", "storage_locations"),
        tenant_fk("destination_location_id", "storage_locations"),
        UniqueConstraint("transfer_id", "lot_id", "source_location_id", "destination_location_id"),
    )


class PurchaseOrder(Owned, db.Model):
    __tablename__ = "purchase_orders"
    reference: Mapped[str] = mapped_column(db.String(80))
    status: Mapped[str] = mapped_column(db.String(20), default="draft", server_default="draft")
    ordered_on: Mapped[date] = mapped_column(db.Date, default=date.today)
    supplier_id: Mapped[uuid.UUID]
    delivery_site_id: Mapped[uuid.UUID]
    __table_args__ = document_constraints(
        tenant_fk("supplier_id", "partners"), tenant_fk("delivery_site_id", "sites")
    )


class PurchaseOrderLine(Owned, db.Model):
    __tablename__ = "purchase_order_lines"
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(20, 6))
    purchase_order_id: Mapped[uuid.UUID]
    variant_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        positive(),
        tenant_fk("purchase_order_id", "purchase_orders"),
        tenant_fk("variant_id", "item_variants"),
    )


class GoodsReceipt(Owned, db.Model):
    __tablename__ = "goods_receipts"
    reference: Mapped[str] = mapped_column(db.String(80))
    status: Mapped[str] = mapped_column(db.String(20), default="draft", server_default="draft")
    received_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    supplier_id: Mapped[uuid.UUID]
    warehouse_id: Mapped[uuid.UUID]
    received_by_id: Mapped[uuid.UUID]
    stock_transaction_id: Mapped[uuid.UUID | None]
    __table_args__ = document_constraints(
        tenant_fk("supplier_id", "partners"),
        tenant_fk("warehouse_id", "warehouses"),
        tenant_fk("received_by_id", "memberships"),
        tenant_fk("stock_transaction_id", "stock_transactions"),
    )


class GoodsReceiptLine(Owned, db.Model):
    __tablename__ = "goods_receipt_lines"
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(20, 6))
    receipt_id: Mapped[uuid.UUID]
    purchase_order_line_id: Mapped[uuid.UUID]
    lot_id: Mapped[uuid.UUID]
    location_id: Mapped[uuid.UUID]
    # Optional Expanded linkage has no FK in the Core release.
    supplier_delivery_line_id: Mapped[uuid.UUID | None]
    __table_args__ = owned(
        positive(),
        tenant_fk("receipt_id", "goods_receipts"),
        tenant_fk("purchase_order_line_id", "purchase_order_lines"),
        tenant_fk("lot_id", "lots"),
        tenant_fk("location_id", "storage_locations"),
    )


class ReceiptDocument(Owned, db.Model):
    __tablename__ = "receipt_documents"
    receipt_id: Mapped[uuid.UUID]
    document_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("receipt_id", "goods_receipts"),
        tenant_fk("document_id", "documents"),
        UniqueConstraint("receipt_id", "document_id"),
    )


class ProductionRun(Owned, db.Model):
    __tablename__ = "production_runs"
    reference: Mapped[str] = mapped_column(db.String(80))
    status: Mapped[str] = mapped_column(db.String(20), default="draft", server_default="draft")
    started_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    site_id: Mapped[uuid.UUID]
    bom_id: Mapped[uuid.UUID | None]
    posted_by_id: Mapped[uuid.UUID | None]
    stock_transaction_id: Mapped[uuid.UUID | None]
    __table_args__ = document_constraints(
        tenant_fk("site_id", "sites"),
        tenant_fk("posted_by_id", "memberships"),
        tenant_fk("stock_transaction_id", "stock_transactions"),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="run_dates"),
    )


class ProductionInput(Owned, db.Model):
    __tablename__ = "production_inputs"
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(20, 6))
    production_run_id: Mapped[uuid.UUID]
    lot_id: Mapped[uuid.UUID]
    source_location_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        positive(),
        tenant_fk("production_run_id", "production_runs"),
        tenant_fk("lot_id", "lots"),
        tenant_fk("source_location_id", "storage_locations"),
        UniqueConstraint("production_run_id", "lot_id", "source_location_id"),
    )


class ProductionOutput(Owned, db.Model):
    __tablename__ = "production_outputs"
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(20, 6))
    production_run_id: Mapped[uuid.UUID]
    lot_id: Mapped[uuid.UUID]
    destination_location_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        positive(),
        tenant_fk("production_run_id", "production_runs"),
        tenant_fk("lot_id", "lots"),
        tenant_fk("destination_location_id", "storage_locations"),
        UniqueConstraint("production_run_id", "lot_id", "destination_location_id"),
    )


class SalesOrder(Owned, db.Model):
    __tablename__ = "sales_orders"
    reference: Mapped[str] = mapped_column(db.String(80))
    status: Mapped[str] = mapped_column(db.String(20), default="draft", server_default="draft")
    destination_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    customer_id: Mapped[uuid.UUID]
    address_id: Mapped[uuid.UUID | None]
    __table_args__ = document_constraints(
        tenant_fk("customer_id", "partners"), tenant_fk("address_id", "partner_addresses")
    )


class SalesOrderLine(Owned, db.Model):
    __tablename__ = "sales_order_lines"
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(20, 6))
    sales_order_id: Mapped[uuid.UUID]
    variant_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        positive(),
        tenant_fk("sales_order_id", "sales_orders"),
        tenant_fk("variant_id", "item_variants"),
    )


class Shipment(Owned, db.Model):
    __tablename__ = "shipments"
    reference: Mapped[str] = mapped_column(db.String(80))
    status: Mapped[str] = mapped_column(db.String(20), default="draft", server_default="draft")
    dispatched_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    tracking_reference: Mapped[str | None] = mapped_column(db.String(120))
    sales_order_id: Mapped[uuid.UUID]
    warehouse_id: Mapped[uuid.UUID]
    carrier_id: Mapped[uuid.UUID | None]
    stock_transaction_id: Mapped[uuid.UUID | None]
    __table_args__ = document_constraints(
        tenant_fk("sales_order_id", "sales_orders"),
        tenant_fk("warehouse_id", "warehouses"),
        tenant_fk("carrier_id", "carriers"),
        tenant_fk("stock_transaction_id", "stock_transactions"),
    )


class ShipmentLine(Owned, db.Model):
    __tablename__ = "shipment_lines"
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(20, 6))
    shipment_id: Mapped[uuid.UUID]
    sales_order_line_id: Mapped[uuid.UUID]
    lot_id: Mapped[uuid.UUID]
    source_location_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        positive(),
        tenant_fk("shipment_id", "shipments"),
        tenant_fk("sales_order_line_id", "sales_order_lines"),
        tenant_fk("lot_id", "lots"),
        tenant_fk("source_location_id", "storage_locations"),
    )


class ShipmentEvent(Owned, db.Model):
    __tablename__ = "shipment_events"
    event_type: Mapped[str] = mapped_column(db.String(30))
    occurred_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    note: Mapped[str | None] = mapped_column(db.Text)
    shipment_id: Mapped[uuid.UUID]
    recorded_by_id: Mapped[uuid.UUID | None]
    __table_args__ = owned(
        tenant_fk("shipment_id", "shipments"),
        tenant_fk("recorded_by_id", "memberships"),
        CheckConstraint(
            "event_type IN ('dispatched','in_transit','delivered','exception','correction')",
            name="event_type",
        ),
    )
