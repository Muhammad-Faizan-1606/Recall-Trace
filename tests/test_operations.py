"""Operational integration checks use PostgreSQL, real Decimal balances and locks."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from conftest import csrf, login
from flask_login import login_user
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import NotFound

from app.extensions import db
from app.models import (
    Item,
    ItemVariant,
    Membership,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.models.master import Lot, Partner, PartnerRoleAssignment, Site, StorageLocation, Warehouse
from app.models.operations import (
    GoodsReceiptLine,
    ProductionRun,
    StockBalance,
    StockTransaction,
    StockTransactionLine,
)
from app.models.quality import QualityHold
from app.services import operations as op
from app.services.business import DomainError


@pytest.fixture
def operational(records):
    company_id = records["companies"]["aurora"]
    role = db.session.scalar(
        select(Role).where(Role.organization_id == company_id, Role.code == "catalog-editor")
    )
    for code in (
        "inventory.receive",
        "inventory.transfer",
        "inventory.dispatch",
        "production.post",
    ):
        permission = db.session.scalar(select(Permission).where(Permission.code == code))
        if not permission:
            permission = Permission(code=code, description=code)
            db.session.add(permission)
            db.session.flush()
        if not db.session.scalar(
            select(RolePermission.id).where(
                RolePermission.role_id == role.id, RolePermission.permission_id == permission.id
            )
        ):
            db.session.add(
                RolePermission(
                    organization_id=company_id, role_id=role.id, permission_id=permission.id
                )
            )
    site = Site(
        organization_id=company_id,
        code="HQ",
        name="Fictional factory",
        address_text="Demo road",
        country_code="PK",
    )
    supplier = Partner(organization_id=company_id, code="SUP", name="Fictional supplier")
    customer = Partner(organization_id=company_id, code="CUS", name="Fictional customer")
    db.session.add_all([site, supplier, customer])
    db.session.flush()
    db.session.add_all(
        [
            PartnerRoleAssignment(
                organization_id=company_id, partner_id=supplier.id, role_code="supplier"
            ),
            PartnerRoleAssignment(
                organization_id=company_id, partner_id=customer.id, role_code="customer"
            ),
        ]
    )
    warehouse = Warehouse(
        organization_id=company_id, site_id=site.id, code="MAIN", name="Main warehouse"
    )
    other = Warehouse(
        organization_id=company_id, site_id=site.id, code="OTHER", name="Other warehouse"
    )
    db.session.add_all([warehouse, other])
    db.session.flush()
    location = StorageLocation(
        organization_id=company_id,
        warehouse_id=warehouse.id,
        code="A",
        name="Shelf A",
        kind="storage",
    )
    destination = StorageLocation(
        organization_id=company_id, warehouse_id=other.id, code="B", name="Shelf B", kind="storage"
    )
    input_item = Item(organization_id=company_id, code="SWITCH", name="Switch", kind="component")
    db.session.add_all([location, destination, input_item])
    db.session.flush()
    input_variant = ItemVariant(
        organization_id=company_id,
        item_id=input_item.id,
        base_unit_id=db.session.get(ItemVariant, records["aurora_variants"]).base_unit_id,
        sku="SWITCH-01",
        revision="A",
    )
    db.session.add(input_variant)
    db.session.flush()
    lot = Lot(
        organization_id=company_id,
        lot_code="C10",
        variant_id=input_variant.id,
        supplier_id=supplier.id,
    )
    output = Lot(organization_id=company_id, lot_code="L1", variant_id=records["aurora_variants"])
    output2 = Lot(organization_id=company_id, lot_code="L2", variant_id=records["aurora_variants"])
    db.session.add_all([lot, output, output2])
    db.session.commit()
    member = db.session.scalar(
        select(Membership)
        .join(User)
        .where(Membership.organization_id == company_id, User.email == "catalog-editor@aurora.test")
    )
    return {
        "company": company_id,
        "site": site.id,
        "supplier": supplier.id,
        "customer": customer.id,
        "warehouse": warehouse.id,
        "other": other.id,
        "location": location.id,
        "destination": destination.id,
        "lot": lot.id,
        "output": output.id,
        "output2": output2.id,
        "input_variant": input_variant.id,
        "output_variant": records["aurora_variants"],
        "member": member.id,
        "user": member.user_id,
    }


def seed_stock(data, amount="200"):
    purchase = op.create_document(
        data["company"],
        "purchase-orders",
        {"reference": "PO-C10", "supplier_id": data["supplier"], "delivery_site_id": data["site"]},
    )
    order_line = op.add_line(
        data["company"],
        "purchase-orders",
        purchase.id,
        {"variant_id": data["input_variant"], "quantity": amount},
    )
    op.post_document(data["company"], "purchase-orders", purchase.id, "order-confirm")
    receipt = op.create_document(
        data["company"],
        "receipts",
        {"reference": "GR-C10", "supplier_id": data["supplier"], "warehouse_id": data["warehouse"]},
    )
    op.add_line(
        data["company"],
        "receipts",
        receipt.id,
        {
            "purchase_order_line_id": order_line.id,
            "lot_id": data["lot"],
            "location_id": data["location"],
            "quantity": amount,
        },
    )
    op.post_document(data["company"], "receipts", receipt.id, "receipt-c10")
    return receipt


def production(data, reference, input_amount, output_amount, lot=None):
    run = op.create_document(
        data["company"], "production", {"reference": reference, "site_id": data["site"]}
    )
    op.add_line(
        data["company"],
        "production-inputs",
        run.id,
        {"lot_id": data["lot"], "source_location_id": data["location"], "quantity": input_amount},
    )
    op.add_line(
        data["company"],
        "production-outputs",
        run.id,
        {
            "lot_id": lot or data["output"],
            "destination_location_id": data["location"],
            "quantity": output_amount,
        },
    )
    return run


def amount(data, lot=None, location=None):
    return db.session.scalar(
        select(StockBalance.quantity).where(
            StockBalance.organization_id == data["company"],
            StockBalance.lot_id == (lot or data["lot"]),
            StockBalance.location_id == (location or data["location"]),
        )
    ) or Decimal("0")


def test_receipt_production_shipping_and_reconciliation(app, operational):
    d = operational
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        seed_stock(d)
        run = production(d, "RUN-A", "100", "100")
        op.post_document(d["company"], "production", run.id, "production-a")
        order = op.create_document(
            d["company"],
            "sales-orders",
            {
                "reference": "SO-1",
                "customer_id": d["customer"],
                "destination": "Fictional customer depot",
            },
        )
        line = op.add_line(
            d["company"],
            "sales-orders",
            order.id,
            {"variant_id": d["output_variant"], "quantity": "60"},
        )
        op.post_document(d["company"], "sales-orders", order.id, "so-confirm")
        shipment = op.create_document(
            d["company"],
            "shipments",
            {"reference": "S1", "sales_order_id": order.id, "warehouse_id": d["warehouse"]},
        )
        op.add_line(
            d["company"],
            "shipments",
            shipment.id,
            {
                "sales_order_line_id": line.id,
                "lot_id": d["output"],
                "source_location_id": d["location"],
                "quantity": "60",
            },
        )
        op.post_document(d["company"], "shipments", shipment.id, "dispatch-s1")
        assert amount(d) == Decimal("100")
        assert amount(d, d["output"]) == Decimal("40")
        assert shipment.status == "posted" and shipment.dispatched_at
        assert op.reconciliation(d["company"]) == []
        assert (
            op.post_document(d["company"], "shipments", shipment.id, "dispatch-s1").id
            == shipment.id
        )
        with pytest.raises(DomainError, match="already posted"):
            op.post_document(d["company"], "shipments", shipment.id, "different-key")
        with pytest.raises(DomainError, match="history"):
            op.delete_draft(d["company"], "shipments", shipment.id, shipment.version)


def test_precision_invalid_quantity_and_foreign_parent(app, operational, records):
    d = operational
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        order = op.create_document(
            d["company"],
            "purchase-orders",
            {"reference": "PO", "supplier_id": d["supplier"], "delivery_site_id": d["site"]},
        )
        for bad in ("-1", "0", "1.1", "NaN", "Infinity", "100000000000000"):
            with pytest.raises(DomainError):
                op.add_line(
                    d["company"],
                    "purchase-orders",
                    order.id,
                    {"variant_id": d["input_variant"], "quantity": bad},
                )
        with pytest.raises(NotFound):
            op.add_line(
                d["company"],
                "purchase-orders",
                order.id,
                {"variant_id": records["beacon_variants"], "quantity": "1"},
            )
        assert not op.lines_for(d["company"], "purchase-orders", order.id)


def test_holds_overspend_and_idempotency_payload(app, operational):
    d = operational
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        seed_stock(d, "100")
        hold = QualityHold(
            organization_id=d["company"],
            lot_id=d["lot"],
            reason="Fictional issue",
            placed_by_id=d["member"],
        )
        db.session.add(hold)
        db.session.commit()
        run = production(d, "BLOCKED", "50", "50")
        with pytest.raises(DomainError, match="hold"):
            op.post_document(d["company"], "production", run.id, "blocked-key")
        assert amount(d) == 100 and amount(d, d["output"]) == 0
        assert db.session.get(ProductionRun, run.id).status == "draft"
        with pytest.raises(DomainError, match="different payload"):
            op.post_stock(
                d["company"],
                "receipts",
                [(d["lot"], d["location"], Decimal("101"))],
                "receipt-c10",
                d["member"],
                source=uuid.uuid4(),
            )
        db.session.rollback()
        assert amount(d) == 100


def test_reversal_preserves_history_and_is_repeatable(app, operational):
    d = operational
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        receipt = seed_stock(d, "100")
        original_id = receipt.stock_transaction_id
        reversal = op.reverse_stock(
            d["company"], original_id, "reversal-key", "Duplicate receipt correction"
        )
        assert amount(d) == 0
        assert db.session.get(StockTransaction, original_id)
        assert op.reconciliation(d["company"]) == []
        assert (
            op.reverse_stock(
                d["company"], original_id, "reversal-key", "Duplicate receipt correction"
            ).id
            == reversal.id
        )
        with pytest.raises(DomainError, match="different reversal payload"):
            op.reverse_stock(d["company"], original_id, "reversal-key", "Different reason")
        assert db.session.scalar(select(func.count()).select_from(StockTransactionLine)) == 2


def test_over_receipt_and_stale_line_edit_roll_back(app, operational):
    d = operational
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        receipt = seed_stock(d, "100")
        line = db.session.scalar(
            select(GoodsReceiptLine).where(GoodsReceiptLine.receipt_id == receipt.id)
        )
        another = op.create_document(
            d["company"],
            "receipts",
            {
                "reference": "GR-EXCESS",
                "supplier_id": d["supplier"],
                "warehouse_id": d["warehouse"],
            },
        )
        op.add_line(
            d["company"],
            "receipts",
            another.id,
            {
                "purchase_order_line_id": line.purchase_order_line_id,
                "lot_id": d["lot"],
                "location_id": d["location"],
                "quantity": "1",
            },
        )
        with pytest.raises(DomainError, match="ordered quantity"):
            op.post_document(d["company"], "receipts", another.id, "excess")
        with pytest.raises(DomainError, match="changed"):
            op.add_line(
                d["company"],
                "receipts",
                another.id,
                {
                    "purchase_order_line_id": line.purchase_order_line_id,
                    "lot_id": d["lot"],
                    "location_id": d["location"],
                    "quantity": "1",
                },
                version=0,
            )
        assert amount(d) == 100


def test_competing_consumption_has_one_winner(app, operational):
    d = operational
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        seed_stock(d, "100")
        first = production(d, "RACE-A", "80", "80")
        second = production(d, "RACE-B", "80", "80", d["output2"])
        ids = [first.id, second.id]
    db.session.remove()
    barrier = Barrier(2)

    def post(index):
        with app.test_request_context():
            login_user(db.session.get(User, d["user"]))
            barrier.wait(timeout=10)
            try:
                op.post_document(d["company"], "production", ids[index], f"race-{index}")
                return "posted"
            except DomainError:
                return "insufficient"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(post, range(2)))
    assert sorted(outcomes) == ["insufficient", "posted"]
    assert amount(d) == 20
    assert (
        db.session.scalar(
            select(func.count()).select_from(ProductionRun).where(ProductionRun.status == "posted")
        )
        == 1
    )


def test_operation_pages_guard_csrf_and_tenant(client, operational, records):
    d = operational
    login(client)
    base = f"/companies/{d['company']}/operations"
    assert client.get(base).status_code == 200
    page = client.get(base + "/purchase-orders/new")
    assert page.status_code == 200
    payload = {
        "reference": "UI-PO",
        "supplier_id": str(d["supplier"]),
        "delivery_site_id": str(d["site"]),
        "version": "0",
    }
    assert client.post(base + "/purchase-orders/new", data=payload).status_code == 400
    payload["csrf_token"] = csrf(page)
    result = client.post(base + "/purchase-orders/new", data=payload)
    assert result.status_code == 303
    assert client.get(result.location).status_code == 200
    foreign = f"/companies/{records['companies']['beacon']}/operations/purchase-orders/new"
    assert client.get(foreign).status_code == 404
    login(client, "auditor@aurora.test")
    assert client.get(base + "/purchase-orders/new").status_code == 403
    assert client.get(base).status_code == 200


def test_cross_tenant_stock_line_fk_rejected(operational, records):
    d = operational
    line = StockBalance(
        organization_id=records["companies"]["beacon"],
        lot_id=d["lot"],
        location_id=d["location"],
        quantity=Decimal("1"),
    )
    db.session.add(line)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_transfer_conserves_stock_and_line_crud(app, operational):
    d = operational
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        seed_stock(d, "100")
        transfer = op.create_document(
            d["company"],
            "transfers",
            {
                "reference": "MOVE",
                "source_warehouse_id": d["warehouse"],
                "destination_warehouse_id": d["other"],
            },
        )
        line = op.add_line(
            d["company"],
            "transfers",
            transfer.id,
            {
                "lot_id": d["lot"],
                "source_location_id": d["location"],
                "destination_location_id": d["destination"],
                "quantity": "20",
            },
            version=transfer.version,
        )
        op.add_line(
            d["company"],
            "transfers",
            transfer.id,
            {
                "lot_id": d["lot"],
                "source_location_id": d["location"],
                "destination_location_id": d["destination"],
                "quantity": "30",
            },
            version=transfer.version,
            line_id=line.id,
        )
        op.delete_line(d["company"], "transfers", transfer.id, line.id, transfer.version)
        assert op.lines_for(d["company"], "transfers", transfer.id) == []
        op.add_line(
            d["company"],
            "transfers",
            transfer.id,
            {
                "lot_id": d["lot"],
                "source_location_id": d["location"],
                "destination_location_id": d["destination"],
                "quantity": "40",
            },
            version=transfer.version,
        )
        op.post_document(
            d["company"], "transfers", transfer.id, "move-40", version=transfer.version
        )
        assert amount(d) == 60
        assert amount(d, location=d["destination"]) == 40
        assert op.reconciliation(d["company"]) == []
        op.reverse_stock(
            d["company"], transfer.stock_transaction_id, "undo-move", "Wrong warehouse"
        )
        assert amount(d) == 100 and amount(d, location=d["destination"]) == 0


def test_production_rejects_self_ancestry_and_new_output_refill(app, operational):
    d = operational
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        seed_stock(d, "100")
        run = production(d, "SELF", "10", "10", d["lot"])
        with pytest.raises(DomainError, match="also be an input"):
            op.post_document(d["company"], "production", run.id, "self-cycle")
        assert amount(d) == 100
        valid = production(d, "VALID", "10", "10")
        op.post_document(d["company"], "production", valid.id, "valid")
        repeated = production(d, "REFILL", "10", "10")
        with pytest.raises(DomainError, match="producing event"):
            op.post_document(d["company"], "production", repeated.id, "refill")
        assert amount(d) == 90 and amount(d, d["output"]) == 10


def grant_evidence_read(data):
    role = db.session.scalar(
        select(Role).where(Role.organization_id == data["company"], Role.code == "catalog-editor")
    )
    permission = db.session.scalar(select(Permission).where(Permission.code == "evidence.read"))
    if permission is None:
        permission = Permission(code="evidence.read", description="Read authorized evidence")
        db.session.add(permission)
        db.session.flush()
    if not db.session.scalar(
        select(RolePermission.id).where(
            RolePermission.role_id == role.id, RolePermission.permission_id == permission.id
        )
    ):
        db.session.add(
            RolePermission(
                organization_id=data["company"], role_id=role.id, permission_id=permission.id
            )
        )
    db.session.commit()


def evidence_record(data, state="active", scan_status="clean", archived=False):
    from app.models import now
    from app.models.evidence import Document

    record = Document(
        organization_id=data["company"],
        object_key=f"{uuid.uuid4().hex}.pdf",
        original_name="Fictional accepted report.pdf",
        media_type="application/pdf",
        size_bytes=100,
        sha256="0" * 64,
        scan_status=scan_status,
        state=state,
        uploaded_by_id=data["member"],
        archived_at=now() if archived else None,
    )
    db.session.add(record)
    db.session.commit()
    return record


def draft_receipt(data, reference="GR-EVIDENCE"):
    return op.create_document(
        data["company"],
        "receipts",
        {
            "reference": reference,
            "supplier_id": data["supplier"],
            "warehouse_id": data["warehouse"],
        },
    )


def test_receipt_evidence_requires_separate_read_permission(app, operational):
    from werkzeug.exceptions import Forbidden

    from app.models.operations import ReceiptDocument

    d = operational
    report = evidence_record(d)
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        receipt = draft_receipt(d)
        with pytest.raises(Forbidden):
            op.attach_receipt_document(d["company"], receipt.id, report.id, receipt.version)
        assert not db.session.scalar(select(ReceiptDocument.id))


@pytest.mark.parametrize(
    ("state", "scan_status", "archived"),
    [
        ("source", "clean", False),
        ("export", "clean", False),
        ("quarantined", "clean", False),
        ("active", "pending", False),
        ("active", "infected", False),
        ("active", "unavailable", False),
        ("active", "clean", True),
    ],
)
def test_receipt_rejects_private_non_evidence_or_unaccepted_document(
    app, operational, state, scan_status, archived
):
    from app.models.operations import ReceiptDocument

    d = operational
    grant_evidence_read(d)
    report = evidence_record(d, state, scan_status, archived)
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        receipt = draft_receipt(d)
        with pytest.raises(DomainError, match="accepted private evidence"):
            op.attach_receipt_document(d["company"], receipt.id, report.id, receipt.version)
        assert not db.session.scalar(select(ReceiptDocument.id))


def test_receipt_accepted_evidence_attach_detach_and_tenant_scope(app, operational, records):
    from app.models.operations import ReceiptDocument

    d = operational
    grant_evidence_read(d)
    report = evidence_record(d)
    other_member = db.session.scalar(
        select(Membership).where(Membership.organization_id == records["companies"]["beacon"])
    )
    foreign = evidence_record({"company": other_member.organization_id, "member": other_member.id})
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        receipt = draft_receipt(d)
        with pytest.raises(NotFound):
            op.attach_receipt_document(d["company"], receipt.id, foreign.id, receipt.version)
        assert not db.session.scalar(select(ReceiptDocument.id))
        attachment = op.attach_receipt_document(
            d["company"], receipt.id, report.id, receipt.version
        )
        assert db.session.get(ReceiptDocument, attachment.id).document_id == report.id
        op.detach_receipt_document(d["company"], receipt.id, attachment.id, receipt.version)
        assert db.session.get(ReceiptDocument, attachment.id) is None


def test_receipt_form_hides_document_choices_without_evidence_access(client, app, operational):
    d = operational
    evidence_record(d)
    with app.test_request_context():
        login_user(db.session.get(User, d["user"]))
        receipt_id = draft_receipt(d).id
    login(client)
    path = f"/companies/{d['company']}/operations/receipts/{receipt_id}"
    page = client.get(path)
    assert page.status_code == 200
    assert "Fictional accepted report.pdf" not in page.text
    assert "Attach document" not in page.text
    grant_evidence_read(d)
    source = evidence_record(d, "source")
    export = evidence_record(d, "export")
    page = client.get(path)
    assert "Fictional accepted report.pdf" in page.text
    assert f'value="{source.id}"' not in page.text
    assert f'value="{export.id}"' not in page.text
