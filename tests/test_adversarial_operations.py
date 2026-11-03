"""Regression attacks against operational authorization and stale parent state."""

from contextlib import contextmanager

import pytest
from conftest import csrf, login
from flask_login import login_user
from sqlalchemy import delete, select
from test_operations import amount, production, seed_stock
from test_operations import operational as _operational
from werkzeug.exceptions import Forbidden

from app.extensions import db
from app.models import MembershipRole, Permission, RolePermission, User, now
from app.models.master import Partner, Site, Warehouse
from app.models.operations import GoodsReceipt, ShipmentEvent, StockTransaction
from app.services import operations as op
from app.services.business import DomainError

operational = _operational


@contextmanager
def signed(app, data):
    with app.test_request_context():
        login_user(db.session.get(User, data["user"]))
        yield


def revoke_action(data, action):
    permission_id = db.session.scalar(select(Permission.id).where(Permission.code == action))
    roles = select(MembershipRole.role_id).where(MembershipRole.membership_id == data["member"])
    db.session.execute(
        delete(RolePermission).where(
            RolePermission.role_id.in_(roles), RolePermission.permission_id == permission_id
        )
    )
    db.session.commit()


def transfer(data, reference="MOVE"):
    row = op.create_document(
        data["company"],
        "transfers",
        {
            "reference": reference,
            "source_warehouse_id": data["warehouse"],
            "destination_warehouse_id": data["other"],
        },
    )
    op.add_line(
        data["company"],
        "transfers",
        row.id,
        {
            "lot_id": data["lot"],
            "quantity": "20",
            "source_location_id": data["location"],
            "destination_location_id": data["destination"],
        },
    )
    op.post_document(data["company"], "transfers", row.id, "post-" + reference)
    return row


def test_transfer_only_user_cannot_reverse_supplier_receipt(app, operational, client):
    d = operational
    with signed(app, d):
        receipt = seed_stock(d, "100")
        receipt_id, posting_id = receipt.id, receipt.stock_transaction_id
        revoke_action(d, "inventory.receive")
        with pytest.raises(Forbidden):
            op.reverse_stock(
                d["company"], posting_id, "unauthorized-receipt-undo", "Cannot receive"
            )
        assert amount(d) == 100
        assert db.session.get(GoodsReceipt, receipt_id).stock_transaction_id == posting_id
        assert (
            db.session.scalar(
                select(StockTransaction.id).where(StockTransaction.reverses_id == posting_id)
            )
            is None
        )
    login(client)
    path = f"/companies/{d['company']}/operations/journal/{posting_id}"
    assert "Post compensating reversal" not in client.get(path).text
    response = client.post(
        path,
        data={
            "csrf_token": csrf(client.get(path)),
            "idempotency_key": "web-receipt-undo",
            "reason": "Denied",
        },
    )
    assert response.status_code == 403


def test_receiving_permission_does_not_authorize_transfer_reversal(app, operational):
    d = operational
    with signed(app, d):
        seed_stock(d, "100")
        moved = transfer(d)
        revoke_action(d, "inventory.transfer")
        with pytest.raises(Forbidden):
            op.reverse_stock(
                d["company"], moved.stock_transaction_id, "no-transfer-authority", "Denied"
            )
        assert amount(d) == 80
        assert amount(d, location=d["destination"]) == 20
        assert (
            db.session.scalar(
                select(StockTransaction.id).where(
                    StockTransaction.reverses_id == moved.stock_transaction_id
                )
            )
            is None
        )


def test_receipt_reversal_does_not_require_transfer_permission(app, operational):
    d = operational
    with signed(app, d):
        receipt = seed_stock(d, "100")
        revoke_action(d, "inventory.transfer")
        op.reverse_stock(
            d["company"], receipt.stock_transaction_id, "receive-undo", "Wrong receipt"
        )
        assert amount(d) == 0
        assert op.reconciliation(d["company"]) == []


def test_posting_and_reversal_retry_normalize_the_same_key_consistently(app, operational):
    d = operational
    with signed(app, d):
        receipt = draft_receipt(d)
        posted = op.post_document(d["company"], "receipts", receipt.id, "  retry-receipt  ")
        posting_id = posted.stock_transaction_id
        retried = op.post_document(d["company"], "receipts", receipt.id, "  retry-receipt  ")
        assert retried.stock_transaction_id == posting_id
        first = op.reverse_stock(d["company"], posting_id, "  retry-reversal  ", "Wrong delivery")
        again = op.reverse_stock(d["company"], posting_id, "  retry-reversal  ", "Wrong delivery")
        assert first.id == again.id
        assert amount(d) == 0
        assert db.session.query(StockTransaction).count() == 2


@pytest.mark.parametrize("field", ["reference", "destination"])
def test_nul_in_operational_header_is_rejected_before_database_write(app, operational, field):
    d = operational
    with signed(app, d):
        values = {"reference": "NUL-ORDER", "customer_id": d["customer"], "destination": "Campus"}
        values[field] = "Fictional\x00payload"
        before = db.session.query(op.SalesOrder).count()
        with pytest.raises(DomainError, match="NUL"):
            op.create_document(d["company"], "sales-orders", values)
        assert db.session.query(op.SalesOrder).count() == before


def draft_receipt(data):
    purchase = op.create_document(
        data["company"],
        "purchase-orders",
        {
            "reference": "ORDER",
            "supplier_id": data["supplier"],
            "delivery_site_id": data["site"],
        },
    )
    line = op.add_line(
        data["company"],
        "purchase-orders",
        purchase.id,
        {
            "variant_id": data["input_variant"],
            "quantity": "100",
        },
    )
    op.post_document(data["company"], "purchase-orders", purchase.id, "confirmed-order")
    receipt = op.create_document(
        data["company"],
        "receipts",
        {
            "reference": "DRAFT-RECEIPT",
            "supplier_id": data["supplier"],
            "warehouse_id": data["warehouse"],
        },
    )
    op.add_line(
        data["company"],
        "receipts",
        receipt.id,
        {
            "lot_id": data["lot"],
            "quantity": "100",
            "purchase_order_line_id": line.id,
            "location_id": data["location"],
        },
    )
    return receipt


@pytest.mark.parametrize("state", ["inactive_supplier", "archived_site"])
def test_receipt_posting_revalidates_header_and_facility(app, operational, state):
    d = operational
    with signed(app, d):
        receipt = draft_receipt(d)
        if state == "inactive_supplier":
            db.session.get(Partner, d["supplier"]).status = "inactive"
        else:
            db.session.get(Site, d["site"]).archived_at = now()
        db.session.commit()
        with pytest.raises(DomainError, match="active"):
            op.post_document(d["company"], "receipts", receipt.id, "stale-header-receipt")
        assert amount(d) == 0
        assert receipt.status == "draft"
        assert receipt.stock_transaction_id is None


def test_purchase_confirmation_rechecks_archived_delivery_site(app, operational):
    d = operational
    with signed(app, d):
        order = op.create_document(
            d["company"],
            "purchase-orders",
            {
                "reference": "DRAFT-PO",
                "supplier_id": d["supplier"],
                "delivery_site_id": d["site"],
            },
        )
        op.add_line(
            d["company"],
            "purchase-orders",
            order.id,
            {
                "variant_id": d["input_variant"],
                "quantity": "10",
            },
        )
        db.session.get(Site, d["site"]).archived_at = now()
        db.session.commit()
        with pytest.raises(DomainError, match="active"):
            op.post_document(d["company"], "purchase-orders", order.id, "stale-site")
        assert order.status == "draft"


def test_dispatch_rechecks_customer_after_draft_creation(app, operational):
    d = operational
    with signed(app, d):
        seed_stock(d, "100")
        run = production(d, "RUN", "10", "10")
        op.post_document(d["company"], "production", run.id, "production")
        order = op.create_document(
            d["company"],
            "sales-orders",
            {
                "reference": "SO",
                "customer_id": d["customer"],
                "destination": "Fictional campus",
            },
        )
        line = op.add_line(
            d["company"],
            "sales-orders",
            order.id,
            {
                "variant_id": d["output_variant"],
                "quantity": "10",
            },
        )
        op.post_document(d["company"], "sales-orders", order.id, "confirm-sale")
        shipment = op.create_document(
            d["company"],
            "shipments",
            {
                "reference": "SHIP",
                "sales_order_id": order.id,
                "warehouse_id": d["warehouse"],
            },
        )
        op.add_line(
            d["company"],
            "shipments",
            shipment.id,
            {
                "lot_id": d["output"],
                "quantity": "10",
                "source_location_id": d["location"],
                "sales_order_line_id": line.id,
            },
        )
        db.session.get(Partner, d["customer"]).status = "inactive"
        db.session.commit()
        with pytest.raises(DomainError, match="active"):
            op.post_document(d["company"], "shipments", shipment.id, "inactive-customer")
        assert amount(d, lot=d["output"]) == 10
        assert shipment.status == "draft" and shipment.stock_transaction_id is None


@pytest.mark.parametrize("note,expected_status", [(None, 303), ("malicious\x00note", 409)])
def test_shipment_event_missing_or_nul_note_never_causes_server_error(
    app, operational, client, note, expected_status
):
    d = operational
    with signed(app, d):
        seed_stock(d, "20")
        run = production(d, "EVENT-RUN", "5", "5")
        op.post_document(d["company"], "production", run.id, "event-production")
        order = op.create_document(
            d["company"],
            "sales-orders",
            {
                "reference": "EVENT-SO",
                "customer_id": d["customer"],
                "destination": "Fictional campus",
            },
        )
        line = op.add_line(
            d["company"],
            "sales-orders",
            order.id,
            {
                "variant_id": d["output_variant"],
                "quantity": "5",
            },
        )
        op.post_document(d["company"], "sales-orders", order.id, "event-sale")
        shipment = op.create_document(
            d["company"],
            "shipments",
            {
                "reference": "EVENT-SHIP",
                "sales_order_id": order.id,
                "warehouse_id": d["warehouse"],
            },
        )
        op.add_line(
            d["company"],
            "shipments",
            shipment.id,
            {
                "lot_id": d["output"],
                "quantity": "5",
                "source_location_id": d["location"],
                "sales_order_line_id": line.id,
            },
        )
        op.post_document(d["company"], "shipments", shipment.id, "event-ship")
        shipment_id = shipment.id
    login(client)
    base = f"/companies/{d['company']}/operations/shipments/{shipment_id}"
    data = {"csrf_token": csrf(client.get(base)), "event_type": "in_transit"}
    if note is not None:
        data["note"] = note
    assert client.post(base + "/events", data=data).status_code == expected_status
    event = db.session.scalar(
        select(ShipmentEvent).where(
            ShipmentEvent.shipment_id == shipment_id,
            ShipmentEvent.event_type == "in_transit",
        )
    )
    if note is None:
        assert event is not None and event.note == ""
    else:
        assert event is None


def test_transfer_reversal_cannot_return_stock_into_archived_empty_warehouse(app, operational):
    d = operational
    with signed(app, d):
        seed_stock(d, "20")
        moved = transfer(d)
        assert amount(d) == 0
        db.session.get(Warehouse, d["warehouse"]).archived_at = now()
        db.session.commit()
        with pytest.raises(DomainError, match="active"):
            op.reverse_stock(
                d["company"], moved.stock_transaction_id, "stale-source", "Return stock"
            )
        assert amount(d) == 0 and amount(d, location=d["destination"]) == 20
        assert op.reconciliation(d["company"]) == []


@pytest.mark.parametrize("action", ["edit", "delete", "post"])
def test_oversized_version_form_is_rejected_without_server_error(app, operational, client, action):
    d = operational
    with signed(app, d):
        order = op.create_document(
            d["company"],
            "purchase-orders",
            {
                "reference": "VERSION-PO",
                "supplier_id": d["supplier"],
                "delivery_site_id": d["site"],
            },
        )
        order_id = order.id
    login(client)
    base = f"/companies/{d['company']}/operations/purchase-orders/{order_id}"
    response = client.post(
        base + "/" + action,
        data={
            "csrf_token": csrf(client.get(base)),
            "version": "9" * 5000,
            "reference": "MALICIOUS",
            "supplier_id": str(d["supplier"]),
            "delivery_site_id": str(d["site"]),
            "idempotency_key": "bad-version",
        },
    )
    assert response.status_code in {400, 422}
    assert db.session.get(op.PurchaseOrder, order_id).reference == "VERSION-PO"
