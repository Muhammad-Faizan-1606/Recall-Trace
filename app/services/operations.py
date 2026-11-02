"""Transactional purchasing, production, distribution and stock services.

The company guard is deliberately conservative: every writer takes it before any
lot lock. The same order is shared with recall approval and hold placement.
"""

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from functools import wraps

from flask import abort
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import ItemVariant, UnitsOfMeasure, now
from app.models.master import (
    Carrier,
    Lot,
    Partner,
    PartnerAddress,
    PartnerRoleAssignment,
    Site,
    StorageLocation,
    Warehouse,
)
from app.models.operations import (
    GoodsReceipt,
    GoodsReceiptLine,
    ProductionInput,
    ProductionOutput,
    ProductionRun,
    PurchaseOrder,
    PurchaseOrderLine,
    ReceiptDocument,
    SalesOrder,
    SalesOrderLine,
    Shipment,
    ShipmentEvent,
    ShipmentLine,
    StockBalance,
    StockTransaction,
    StockTransactionLine,
    StockTransfer,
    StockTransferLine,
)
from app.policies import require
from app.services.audit import record as audit_record
from app.services.business import DomainError, actor, company_lock, quantity, scoped

DOCUMENTS = {
    "purchase-orders": (PurchaseOrder, "inventory.receive"),
    "receipts": (GoodsReceipt, "inventory.receive"),
    "production": (ProductionRun, "production.post"),
    "sales-orders": (SalesOrder, "inventory.dispatch"),
    "shipments": (Shipment, "inventory.dispatch"),
    "transfers": (StockTransfer, "inventory.transfer"),
}
LINES = {
    "purchase-orders": (PurchaseOrderLine, "purchase_order_id", ("variant_id", "quantity")),
    "receipts": (
        GoodsReceiptLine,
        "receipt_id",
        ("purchase_order_line_id", "lot_id", "location_id", "quantity"),
    ),
    "production-inputs": (
        ProductionInput,
        "production_run_id",
        ("lot_id", "source_location_id", "quantity"),
    ),
    "production-outputs": (
        ProductionOutput,
        "production_run_id",
        ("lot_id", "destination_location_id", "quantity"),
    ),
    "sales-orders": (SalesOrderLine, "sales_order_id", ("variant_id", "quantity")),
    "shipments": (
        ShipmentLine,
        "shipment_id",
        ("sales_order_line_id", "lot_id", "source_location_id", "quantity"),
    ),
    "transfers": (
        StockTransferLine,
        "transfer_id",
        ("lot_id", "source_location_id", "destination_location_id", "quantity"),
    ),
}


def transaction(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
            audit_record(
                args[0],
                "operations." + function.__name__,
                getattr(result, "__tablename__", "operations"),
                getattr(result, "id", None),
                {"operation": function.__name__, "status": getattr(result, "status", None)},
            )
            db.session.commit()
            return result
        except (IntegrityError, StaleDataError) as exc:
            db.session.rollback()
            raise DomainError(
                "A duplicate, referenced or stale record prevented this change. Reload and try again."
            ) from exc
        except Exception:
            db.session.rollback()
            raise

    return wrapped


def identifier(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise DomainError("Choose a valid related record.") from exc


def text_value(value, limit=80):
    value = str(value or "").strip()
    if not value or len(value) > limit:
        raise DomainError(f"Enter text between 1 and {limit} characters.")
    return value


def active(model, company_id, value):
    row = scoped(model, company_id, identifier(value), lock=True)
    if getattr(row, "archived_at", None) or getattr(row, "status", "active") == "inactive":
        raise DomainError("Choose an active related record.")
    return row


def partner(company_id, value, role):
    row = active(Partner, company_id, value)
    if not db.session.scalar(
        select(PartnerRoleAssignment.id).where(
            PartnerRoleAssignment.organization_id == company_id,
            PartnerRoleAssignment.partner_id == row.id,
            PartnerRoleAssignment.role_code == role,
        )
    ):
        raise DomainError(f"The partner must have the {role} role.")
    return row


def unit_quantity(company_id, variant_id, value):
    variant = active(ItemVariant, company_id, variant_id)
    unit = active(UnitsOfMeasure, company_id, variant.base_unit_id)
    return quantity(value, places=unit.decimal_places)


def document(company_id, kind, record_id, lock=False):
    if kind not in DOCUMENTS:
        abort(404)
    require(company_id, "catalog.read")
    return scoped(DOCUMENTS[kind][0], company_id, identifier(record_id), lock=lock)


def editable(record, version):
    if record.status != "draft":
        raise DomainError(
            "Posted history cannot be edited or deleted. Use a supported reversal workflow."
        )
    if version is not None and record.version != int(version):
        raise DomainError("This draft changed. Reload before editing.")


def _document_values(company_id, kind, values, member):
    fields = {"reference": text_value(values.get("reference"))}
    if kind == "purchase-orders":
        supplier = partner(company_id, values.get("supplier_id"), "supplier")
        site = active(Site, company_id, values.get("delivery_site_id"))
        try:
            ordered_on = date.fromisoformat(str(values.get("ordered_on") or date.today()))
        except ValueError as exc:
            raise DomainError("Choose a valid order date.") from exc
        fields.update(supplier_id=supplier.id, delivery_site_id=site.id, ordered_on=ordered_on)
    elif kind == "receipts":
        supplier = partner(company_id, values.get("supplier_id"), "supplier")
        warehouse = active(Warehouse, company_id, values.get("warehouse_id"))
        fields.update(supplier_id=supplier.id, warehouse_id=warehouse.id, received_by_id=member.id)
    elif kind == "production":
        site = active(Site, company_id, values.get("site_id"))
        fields["site_id"] = site.id
    elif kind == "sales-orders":
        customer = partner(company_id, values.get("customer_id"), "customer")
        address = (
            active(PartnerAddress, company_id, values["address_id"])
            if values.get("address_id")
            else None
        )
        if address and address.partner_id != customer.id:
            raise DomainError("Choose an address belonging to this customer.")
        destination = str(values.get("destination") or "").strip()
        if not address and not destination:
            raise DomainError("Enter a destination or select a customer address.")
        if len(destination) > 4000:
            raise DomainError("Destination is too long.")
        fields.update(
            customer_id=customer.id,
            address_id=address.id if address else None,
            destination_snapshot={
                "address": address.address_text if address else destination,
                "customer": customer.name,
            },
        )
    elif kind == "shipments":
        order = scoped(SalesOrder, company_id, identifier(values.get("sales_order_id")))
        if order.status != "posted":
            raise DomainError("Confirm the sales order before creating a shipment.")
        warehouse = active(Warehouse, company_id, values.get("warehouse_id"))
        carrier = (
            active(Carrier, company_id, values["carrier_id"]) if values.get("carrier_id") else None
        )
        tracking = str(values.get("tracking_reference") or "").strip()
        if len(tracking) > 120:
            raise DomainError("Tracking reference is too long.")
        fields.update(
            sales_order_id=order.id,
            warehouse_id=warehouse.id,
            carrier_id=carrier.id if carrier else None,
            tracking_reference=tracking or None,
        )
    elif kind == "transfers":
        source = active(Warehouse, company_id, values.get("source_warehouse_id"))
        destination = active(Warehouse, company_id, values.get("destination_warehouse_id"))
        if source.id == destination.id:
            raise DomainError("Choose different source and destination warehouses.")
        fields.update(source_warehouse_id=source.id, destination_warehouse_id=destination.id)
    return fields


@transaction
def create_document(company_id, kind, values):
    if kind not in DOCUMENTS:
        abort(404)
    member = actor(company_id, DOCUMENTS[kind][1])
    company_lock(company_id)
    member = actor(company_id, DOCUMENTS[kind][1])
    record = DOCUMENTS[kind][0](
        organization_id=company_id, **_document_values(company_id, kind, values, member)
    )
    db.session.add(record)
    db.session.flush()
    return record


@transaction
def update_draft(company_id, kind, record_id, values, version):
    member = actor(company_id, DOCUMENTS[kind][1])
    company_lock(company_id)
    member = actor(company_id, DOCUMENTS[kind][1])
    record = document(company_id, kind, record_id, lock=True)
    editable(record, version)
    # Parent identity is frozen once lines exist; replacing children is explicit.
    line_kinds = ["production-inputs", "production-outputs"] if kind == "production" else [kind]
    if any(lines_for(company_id, k, record.id) for k in line_kinds):
        # Only reference changes are safe while preserving existing line semantics.
        record.reference = text_value(values.get("reference"))
    else:
        for key, value in _document_values(company_id, kind, values, member).items():
            setattr(record, key, value)
    return record


@transaction
def delete_draft(company_id, kind, record_id, version):
    actor(company_id, DOCUMENTS[kind][1])
    company_lock(company_id)
    actor(company_id, DOCUMENTS[kind][1])
    record = document(company_id, kind, record_id, lock=True)
    editable(record, version)
    for line_kind in (
        ["production-inputs", "production-outputs"] if kind == "production" else [kind]
    ):
        for row in lines_for(company_id, line_kind, record.id):
            db.session.delete(row)
    if kind == "receipts":
        for row in db.session.scalars(
            select(ReceiptDocument).where(ReceiptDocument.receipt_id == record.id)
        ):
            db.session.delete(row)
    db.session.flush()
    db.session.delete(record)


def lines_for(company_id, kind, record_id):
    model, parent_field, _ = LINES[kind]
    return list(
        db.session.scalars(
            select(model)
            .where(model.organization_id == company_id, getattr(model, parent_field) == record_id)
            .order_by(model.created_at, model.id)
            .execution_options(populate_existing=True)
        )
    )


def _line_values(company_id, kind, parent, values):
    fields = {}
    if kind in ("purchase-orders", "sales-orders"):
        variant = active(ItemVariant, company_id, values.get("variant_id"))
        fields.update(
            variant_id=variant.id,
            quantity=unit_quantity(company_id, variant.id, values.get("quantity")),
        )
        return fields
    lot = active(Lot, company_id, values.get("lot_id"))
    fields.update(
        lot_id=lot.id, quantity=unit_quantity(company_id, lot.variant_id, values.get("quantity"))
    )
    for field in ("location_id", "source_location_id", "destination_location_id"):
        if field in LINES[kind][2]:
            location = active(StorageLocation, company_id, values.get(field))
            fields[field] = location.id
            warehouse = active(Warehouse, company_id, location.warehouse_id)
            expected = None
            if kind in ("receipts", "shipments"):
                expected = parent.warehouse_id
            elif kind == "transfers":
                expected = (
                    parent.source_warehouse_id
                    if field == "source_location_id"
                    else parent.destination_warehouse_id
                )
            elif kind.startswith("production"):
                if warehouse.site_id != parent.site_id:
                    raise DomainError("Production locations must belong to the selected site.")
            if expected and location.warehouse_id != expected:
                raise DomainError("Choose a location in the document warehouse.")
    if kind == "receipts":
        order_line = scoped(
            PurchaseOrderLine, company_id, identifier(values.get("purchase_order_line_id"))
        )
        order = scoped(PurchaseOrder, company_id, order_line.purchase_order_id)
        warehouse = scoped(Warehouse, company_id, parent.warehouse_id)
        if (
            order.status != "posted"
            or order.supplier_id != parent.supplier_id
            or order.delivery_site_id != warehouse.site_id
            or order_line.variant_id != lot.variant_id
        ):
            raise DomainError("Receipt must match a confirmed supplier order, site and SKU.")
        if lot.supplier_id and lot.supplier_id != parent.supplier_id:
            raise DomainError("Lot supplier does not match the receipt supplier.")
        fields["purchase_order_line_id"] = order_line.id
    elif kind == "shipments":
        order_line = scoped(
            SalesOrderLine, company_id, identifier(values.get("sales_order_line_id"))
        )
        if (
            order_line.sales_order_id != parent.sales_order_id
            or order_line.variant_id != lot.variant_id
        ):
            raise DomainError("Shipment line must match its customer order and SKU.")
        fields["sales_order_line_id"] = order_line.id
    return fields


@transaction
def add_line(company_id, kind, record_id, values, version=None, line_id=None):
    if kind not in LINES:
        abort(404)
    parent_kind = "production" if kind.startswith("production-") else kind
    actor(company_id, DOCUMENTS[parent_kind][1])
    company_lock(company_id)
    actor(company_id, DOCUMENTS[parent_kind][1])
    parent = document(company_id, parent_kind, record_id, lock=True)
    editable(parent, version)
    model, parent_field, _ = LINES[kind]
    fields = _line_values(company_id, kind, parent, values)
    if line_id:
        row = scoped(model, company_id, identifier(line_id), lock=True)
        if getattr(row, parent_field) != parent.id:
            abort(404)
        for field, value in fields.items():
            setattr(row, field, value)
    else:
        row = model(organization_id=company_id, **{parent_field: parent.id}, **fields)
        db.session.add(row)
    parent.updated_at = now()  # Bumps version: concurrent form submissions cannot silently merge.
    db.session.flush()
    return row


@transaction
def delete_line(company_id, kind, record_id, line_id, version):
    parent_kind = "production" if kind.startswith("production-") else kind
    actor(company_id, DOCUMENTS[parent_kind][1])
    company_lock(company_id)
    actor(company_id, DOCUMENTS[parent_kind][1])
    parent = document(company_id, parent_kind, record_id, lock=True)
    editable(parent, version)
    model, parent_field, _ = LINES[kind]
    row = scoped(model, company_id, identifier(line_id), lock=True)
    if getattr(row, parent_field) != parent.id:
        abort(404)
    db.session.delete(row)
    parent.updated_at = now()


def _payload(kind, entries, source):
    payload = {
        "kind": kind,
        "source": str(source or ""),
        "entries": sorted(
            (str(lot), str(location), str(Decimal(delta).normalize()))
            for lot, location, delta in entries
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def post_stock(
    company_id, kind, entries, idempotency_key, posted_by_id, source=None, reverses_id=None
):
    """Flush-only journal+projection writer. Caller commits the document atomically.

    Requires a live authorized caller; do not expose this internal primitive as an
    arbitrary stock-edit endpoint. Every entry is a lot/base-unit quantity delta.
    """
    company_lock(company_id)
    key = text_value(idempotency_key, 100)
    digest = _payload(kind, entries, source)
    existing = db.session.scalar(
        select(StockTransaction).where(
            StockTransaction.organization_id == company_id, StockTransaction.idempotency_key == key
        )
    )
    if existing:
        if existing.payload_digest != digest:
            raise DomainError("Idempotency key was already used for a different payload.")
        return existing
    if not entries:
        raise DomainError("Add at least one quantity line before posting.")
    deltas = defaultdict(lambda: Decimal("0"))
    negative_lots = set()
    # Lock lots before balances, in stable UUID order; hold services use these locks.
    lots = {}
    for lot_id in sorted({identifier(e[0]) for e in entries}, key=str):
        lots[lot_id] = scoped(Lot, company_id, lot_id, lock=True)
    from app.models.quality import QualityHold

    for lot_id, location_id, delta in entries:
        lot_id, location_id = identifier(lot_id), identifier(location_id)
        lot = lots[lot_id]
        if lot.archived_at:
            raise DomainError("Archived lots cannot be posted.")
        active(StorageLocation, company_id, location_id)
        delta = Decimal(str(delta))
        if not delta.is_finite() or delta == 0:
            raise DomainError("Every stock change must be finite and nonzero.")
        unit_quantity(company_id, lot.variant_id, abs(delta))
        deltas[(lot_id, location_id)] += delta
        if delta < 0:
            negative_lots.add(lot_id)
    if negative_lots and db.session.scalar(
        select(QualityHold.id)
        .where(
            QualityHold.organization_id == company_id,
            QualityHold.lot_id.in_(negative_lots),
            QualityHold.released_at.is_(None),
        )
        .limit(1)
    ):
        raise DomainError("An active quality hold blocks release of this stock.")
    balances = []
    for (lot_id, location_id), delta in sorted(
        deltas.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))
    ):
        row = db.session.scalar(
            select(StockBalance)
            .where(
                StockBalance.organization_id == company_id,
                StockBalance.lot_id == lot_id,
                StockBalance.location_id == location_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            row = StockBalance(
                organization_id=company_id,
                lot_id=lot_id,
                location_id=location_id,
                quantity=Decimal("0"),
            )
            db.session.add(row)
        next_quantity = row.quantity + delta
        if next_quantity < 0:
            raise DomainError("Available stock is insufficient. No stock changes were posted.")
        row.quantity = quantity(next_quantity, places=6, positive=False)
        balances.append(row)
    posting = StockTransaction(
        organization_id=company_id,
        kind=kind,
        status="posted",
        idempotency_key=key,
        payload_digest=digest,
        posted_by_id=posted_by_id,
        reverses_id=reverses_id,
    )
    db.session.add(posting)
    db.session.flush()
    for (lot_id, location_id), delta in deltas.items():
        if delta:
            db.session.add(
                StockTransactionLine(
                    organization_id=company_id,
                    transaction_id=posting.id,
                    lot_id=lot_id,
                    location_id=location_id,
                    quantity_delta=delta,
                )
            )
    db.session.flush()
    return posting


def _check_order_limits(company_id, kind, lines):
    receipt = kind == "receipts"
    model = GoodsReceiptLine if receipt else ShipmentLine
    parent_model = GoodsReceipt if receipt else Shipment
    parent_fk = model.receipt_id if receipt else model.shipment_id
    order_field = "purchase_order_line_id" if receipt else "sales_order_line_id"
    order_model = PurchaseOrderLine if receipt else SalesOrderLine
    requested = defaultdict(lambda: Decimal("0"))
    for line in lines:
        requested[getattr(line, order_field)] += line.quantity
    for order_id, amount in requested.items():
        order_line = scoped(order_model, company_id, order_id, lock=True)
        fulfilled = db.session.scalar(
            select(func.coalesce(func.sum(model.quantity), 0))
            .join(parent_model, parent_fk == parent_model.id)
            .where(
                model.organization_id == company_id,
                getattr(model, order_field) == order_id,
                parent_model.status == "posted",
                ~parent_model.stock_transaction_id.in_(
                    select(StockTransaction.reverses_id).where(
                        StockTransaction.organization_id == company_id,
                        StockTransaction.reverses_id.is_not(None),
                    )
                ),
            )
        )
        if fulfilled + amount > order_line.quantity:
            raise DomainError("Posting would exceed the ordered quantity.")


def _acyclic_production(company_id, inputs, outputs):
    input_ids, output_ids = {line.lot_id for line in inputs}, {line.lot_id for line in outputs}
    if input_ids & output_ids:
        raise DomainError("A production output cannot also be an input.")
    edges = defaultdict(set)
    rows = db.session.execute(
        select(ProductionInput.lot_id, ProductionOutput.lot_id)
        .join(ProductionRun, ProductionInput.production_run_id == ProductionRun.id)
        .join(ProductionOutput, ProductionOutput.production_run_id == ProductionRun.id)
        .where(
            ProductionRun.organization_id == company_id,
            ProductionRun.status == "posted",
            ProductionInput.organization_id == company_id,
            ProductionOutput.organization_id == company_id,
        )
    )
    for source, target in rows:
        edges[source].add(target)
    frontier, seen = list(output_ids), set(output_ids)
    while frontier:
        current = frontier.pop()
        if current in input_ids:
            raise DomainError("This posting would create a genealogy cycle.")
        for target in edges[current]:
            if target not in seen:
                seen.add(target)
                frontier.append(target)
    # Core output identity represents one producing event, never a refill of an old lot.
    if db.session.scalar(
        select(ProductionOutput.id)
        .join(ProductionRun, ProductionRun.id == ProductionOutput.production_run_id)
        .where(
            ProductionOutput.organization_id == company_id,
            ProductionOutput.lot_id.in_(output_ids),
            ProductionRun.status == "posted",
        )
        .limit(1)
    ):
        raise DomainError("An output lot already has a posted producing event; use a new lot.")
    if db.session.scalar(
        select(StockTransactionLine.id)
        .where(
            StockTransactionLine.organization_id == company_id,
            StockTransactionLine.lot_id.in_(output_ids),
        )
        .limit(1)
    ):
        raise DomainError("Output lots must be new, without existing stock history.")


@transaction
def post_document(company_id, kind, record_id, idempotency_key, version=None):
    member = actor(company_id, DOCUMENTS[kind][1])
    company = company_lock(company_id)
    member = actor(company_id, DOCUMENTS[kind][1])
    record = document(company_id, kind, record_id, lock=True)
    if record.status == "posted":
        if kind in ("purchase-orders", "sales-orders"):
            return record
        posting = scoped(StockTransaction, company_id, record.stock_transaction_id)
        if posting.idempotency_key != idempotency_key:
            raise DomainError("Document is already posted under a different idempotency key.")
        return record
    editable(record, version)
    # Validate references and line semantics again at posting, under the guard.
    line_kinds = ["production-inputs", "production-outputs"] if kind == "production" else [kind]
    groups = [lines_for(company_id, k, record.id) for k in line_kinds]
    if any(not group for group in groups):
        raise DomainError("Add at least one line in every required section before posting.")
    for line_kind, rows in zip(line_kinds, groups, strict=True):
        for line in rows:
            _line_values(
                company_id,
                line_kind,
                record,
                {field: getattr(line, field) for field in LINES[line_kind][2]},
            )
    if kind in ("purchase-orders", "sales-orders"):
        partner(
            company_id,
            record.supplier_id if kind == "purchase-orders" else record.customer_id,
            "supplier" if kind == "purchase-orders" else "customer",
        )
        record.status = "posted"
        return record
    entries = []
    if kind == "receipts":
        _check_order_limits(company_id, kind, groups[0])
        entries = [(line.lot_id, line.location_id, line.quantity) for line in groups[0]]
    elif kind == "shipments":
        _check_order_limits(company_id, kind, groups[0])
        entries = [(line.lot_id, line.source_location_id, -line.quantity) for line in groups[0]]
    elif kind == "production":
        _acyclic_production(company_id, *groups)
        entries = [(line.lot_id, line.source_location_id, -line.quantity) for line in groups[0]] + [
            (line.lot_id, line.destination_location_id, line.quantity) for line in groups[1]
        ]
    elif kind == "transfers":
        entries = [(line.lot_id, line.source_location_id, -line.quantity) for line in groups[0]] + [
            (line.lot_id, line.destination_location_id, line.quantity) for line in groups[0]
        ]
    posting = post_stock(company_id, kind, entries, idempotency_key, member.id, source=record.id)
    record.status, record.stock_transaction_id = "posted", posting.id
    if kind in ("shipments", "production"):
        company.trace_revision += 1
    if kind == "shipments":
        record.dispatched_at = now()
        db.session.add(
            ShipmentEvent(
                organization_id=company_id,
                shipment_id=record.id,
                event_type="dispatched",
                recorded_by_id=member.id,
            )
        )
    elif kind == "production":
        record.posted_by_id, record.finished_at = member.id, now()
    return record


@transaction
def attach_receipt_document(company_id, receipt_id, document_id, version):
    actor(company_id, "inventory.receive")
    company_lock(company_id)
    actor(company_id, "inventory.receive")
    require(company_id, "evidence.read")
    receipt = document(company_id, "receipts", receipt_id, lock=True)
    editable(receipt, version)
    from app.models.evidence import Document

    evidence = scoped(Document, company_id, identifier(document_id), lock=True)
    if evidence.state != "active" or evidence.scan_status != "clean" or evidence.archived_at:
        raise DomainError("Attach accepted private evidence only.")
    row = ReceiptDocument(
        organization_id=company_id, receipt_id=receipt.id, document_id=evidence.id
    )
    db.session.add(row)
    receipt.updated_at = now()
    return row


@transaction
def add_shipment_event(company_id, shipment_id, event_type, note=""):
    member = actor(company_id, "inventory.dispatch")
    company_lock(company_id)
    member = actor(company_id, "inventory.dispatch")
    shipment = document(company_id, "shipments", shipment_id, lock=True)
    if shipment.status != "posted" or event_type not in (
        "in_transit",
        "delivered",
        "exception",
        "correction",
    ):
        raise DomainError("Choose a supported event for a dispatched shipment.")
    if len(note) > 4000:
        raise DomainError("Event note is too long.")
    event = ShipmentEvent(
        organization_id=company_id,
        shipment_id=shipment.id,
        event_type=event_type,
        note=note,
        recorded_by_id=member.id,
    )
    db.session.add(event)
    return event


@transaction
def reverse_stock(company_id, transaction_id, idempotency_key, reason):
    """Compensate a receipt/transfer without erasing its journal or source document.

    Production and shipment corrections need scope/recovery review and are not
    exposed as a blind journal negation.
    """
    member = actor(company_id, "inventory.transfer")
    company_lock(company_id)
    member = actor(company_id, "inventory.transfer")
    original = scoped(StockTransaction, company_id, identifier(transaction_id), lock=True)
    if original.kind not in ("receipts", "transfers"):
        raise DomainError("Only receipt and transfer postings support this compensating reversal.")
    reason = text_value(reason, 1000)
    existing = db.session.scalar(
        select(StockTransaction).where(
            StockTransaction.organization_id == company_id,
            StockTransaction.reverses_id == original.id,
        )
    )
    if existing:
        if existing.idempotency_key != idempotency_key:
            raise DomainError("This posting has already been reversed.")
        original_lines = list(
            db.session.scalars(
                select(StockTransactionLine).where(
                    StockTransactionLine.organization_id == company_id,
                    StockTransactionLine.transaction_id == original.id,
                )
            )
        )
        expected = _payload(
            "reversal",
            [(line.lot_id, line.location_id, -line.quantity_delta) for line in original_lines],
            f"{original.id}:{reason}",
        )
        if existing.payload_digest != expected:
            raise DomainError("Idempotency key was already used for a different reversal payload.")
        return existing
    lines = list(
        db.session.scalars(
            select(StockTransactionLine).where(
                StockTransactionLine.organization_id == company_id,
                StockTransactionLine.transaction_id == original.id,
            )
        )
    )
    reversal = post_stock(
        company_id,
        "reversal",
        [(line.lot_id, line.location_id, -line.quantity_delta) for line in lines],
        idempotency_key,
        member.id,
        source=f"{original.id}:{reason}",
        reverses_id=original.id,
    )
    return reversal


def reconciliation(company_id):
    require(company_id, "catalog.read")
    actual = {
        (r.lot_id, r.location_id): r.quantity
        for r in db.session.scalars(
            select(StockBalance).where(StockBalance.organization_id == company_id)
        )
    }
    journal = dict(
        ((lot, location), amount)
        for lot, location, amount in db.session.execute(
            select(
                StockTransactionLine.lot_id,
                StockTransactionLine.location_id,
                func.sum(StockTransactionLine.quantity_delta),
            )
            .where(StockTransactionLine.organization_id == company_id)
            .group_by(StockTransactionLine.lot_id, StockTransactionLine.location_id)
        )
    )
    return [
        {
            "lot_id": lot,
            "location_id": location,
            "balance": actual.get((lot, location), Decimal("0")),
            "journal": journal.get((lot, location), Decimal("0")),
        }
        for lot, location in sorted(
            actual.keys() | journal.keys(), key=lambda pair: (str(pair[0]), str(pair[1]))
        )
        if actual.get((lot, location), Decimal("0")) != journal.get((lot, location), Decimal("0"))
    ]


@transaction
def detach_receipt_document(company_id, receipt_id, attachment_id, version):
    actor(company_id, "inventory.receive")
    company_lock(company_id)
    actor(company_id, "inventory.receive")
    receipt = document(company_id, "receipts", receipt_id, lock=True)
    editable(receipt, version)
    row = scoped(ReceiptDocument, company_id, identifier(attachment_id), lock=True)
    if row.receipt_id != receipt.id:
        abort(404)
    db.session.delete(row)
    receipt.updated_at = now()
