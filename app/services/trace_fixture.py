"""Repeatable fictional C10 demonstration using the real posting services.

Call in an authenticated request context after granting business permissions. No
external notices are sent and no existing credentials or posted records change.
"""

from sqlalchemy import select

from app.extensions import db
from app.models import Item, ItemVariant, UnitsOfMeasure
from app.models.master import Lot, Partner, PartnerRoleAssignment, Site, StorageLocation, Warehouse
from app.services import operations
from app.services.business import DomainError, actor
from app.services.recall import save_case, source


def seed_c10(company_id):
    actor(company_id, "case.prepare")

    def get_or_create(model, filters, values):
        row = db.session.scalar(select(model).filter_by(organization_id=company_id, **filters))
        if row is None:
            row = model(organization_id=company_id, **filters, **values)
            db.session.add(row)
            db.session.commit()
        return row

    unit = get_or_create(
        UnitsOfMeasure, {"code": "EA"}, {"name": "Each", "dimension": "count", "decimal_places": 0}
    )
    lamp = get_or_create(
        Item, {"code": "C10-LAMP"}, {"name": "Demonstration lamp", "kind": "finished"}
    )
    switch = get_or_create(
        Item, {"code": "C10-SWITCH"}, {"name": "Demonstration switch", "kind": "component"}
    )
    lamp_variant = get_or_create(
        ItemVariant,
        {"sku": "C10-LAMP-01"},
        {"revision": "A", "item_id": lamp.id, "base_unit_id": unit.id},
    )
    switch_variant = get_or_create(
        ItemVariant,
        {"sku": "C10-SWITCH-01"},
        {"revision": "A", "item_id": switch.id, "base_unit_id": unit.id},
    )
    site = get_or_create(
        Site,
        {"code": "C10-SITE"},
        {
            "name": "Fictional demonstration factory",
            "address_text": "Demo campus",
            "country_code": "PK",
        },
    )
    warehouse = get_or_create(
        Warehouse, {"code": "C10-WH"}, {"name": "Demonstration warehouse", "site_id": site.id}
    )
    location = get_or_create(
        StorageLocation,
        {"code": "C10-STOCK", "warehouse_id": warehouse.id},
        {"name": "Demonstration stock", "kind": "storage"},
    )
    supplier = get_or_create(
        Partner, {"code": "C10-SUPPLIER"}, {"name": "Fictional Switch Supplier"}
    )
    customer = get_or_create(Partner, {"code": "C10-CUSTOMER"}, {"name": "Fictional Lamp Customer"})
    for partner, role in [(supplier, "supplier"), (customer, "customer")]:
        get_or_create(PartnerRoleAssignment, {"partner_id": partner.id, "role_code": role}, {})
    lots = {}
    for code in ["C10", "C11", "L1", "L2", "L3"]:
        lots[code] = get_or_create(
            Lot,
            {"lot_code": code},
            {
                "variant_id": switch_variant.id if code.startswith("C") else lamp_variant.id,
                "supplier_id": supplier.id if code.startswith("C") else None,
            },
        )

    def document(kind, reference, values):
        model = operations.DOCUMENTS[kind][0]
        row = db.session.scalar(
            select(model).filter_by(organization_id=company_id, reference=reference)
        )
        return row or operations.create_document(
            company_id, kind, {"reference": reference, **values}
        )

    def line(kind, parent, values):
        model, parent_field, _ = operations.LINES[kind]
        rows = db.session.scalars(
            select(model).where(
                model.organization_id == company_id, getattr(model, parent_field) == parent.id
            )
        ).all()
        for row in rows:
            identity = "variant_id" if "variant_id" in values else "lot_id"
            if getattr(row, identity) == values[identity]:
                if row.quantity != values["quantity"]:
                    raise DomainError(
                        "Existing C10 fixture differs from its expected quantities; preserve and review it."
                    )
                return row
        return operations.add_line(company_id, kind, parent.id, values)

    def post(kind, row):
        return operations.post_document(company_id, kind, row.id, "demo-c10-" + str(row.id))

    po = document(
        "purchase-orders", "C10-PO", {"supplier_id": supplier.id, "delivery_site_id": site.id}
    )
    po_line = line("purchase-orders", po, {"variant_id": switch_variant.id, "quantity": 210})
    post("purchase-orders", po)
    receipt = document(
        "receipts", "C10-RECEIPT", {"supplier_id": supplier.id, "warehouse_id": warehouse.id}
    )
    for code, amount in [("C10", 200), ("C11", 10)]:
        line(
            "receipts",
            receipt,
            {
                "lot_id": lots[code].id,
                "quantity": amount,
                "purchase_order_line_id": po_line.id,
                "location_id": location.id,
            },
        )
    post("receipts", receipt)
    for reference, origin, destination, amount in [
        ("C10-RUN-A", "C10", "L1", 100),
        ("C10-RUN-B", "C10", "L2", 50),
        ("C11-RUN-C", "C11", "L3", 10),
    ]:
        run = document("production", reference, {"site_id": site.id})
        line(
            "production-inputs",
            run,
            {"lot_id": lots[origin].id, "quantity": amount, "source_location_id": location.id},
        )
        line(
            "production-outputs",
            run,
            {
                "lot_id": lots[destination].id,
                "quantity": amount,
                "destination_location_id": location.id,
            },
        )
        post("production", run)
    sales = document(
        "sales-orders",
        "C10-SO",
        {"customer_id": customer.id, "destination": "Fictional customer campus"},
    )
    order_line = line("sales-orders", sales, {"variant_id": lamp_variant.id, "quantity": 120})
    post("sales-orders", sales)
    shipments = {}
    for reference, code, amount in [("S1", "L1", 60), ("S2", "L2", 50), ("S3", "L3", 10)]:
        shipment = document(
            "shipments",
            "C10-" + reference,
            {"sales_order_id": sales.id, "warehouse_id": warehouse.id},
        )
        shipments[reference] = line(
            "shipments",
            shipment,
            {
                "lot_id": lots[code].id,
                "quantity": amount,
                "sales_order_line_id": order_line.id,
                "source_location_id": location.id,
            },
        )
        post("shipments", shipment)
    from app.models.recall import CaseSource, RecallCase

    case = db.session.scalar(
        select(RecallCase).filter_by(organization_id=company_id, reference="C10-INVESTIGATION")
    )
    if case is None:
        case = save_case(
            company_id,
            "C10-INVESTIGATION",
            "Suspect C10 switch lot",
            "Fictional investigation fixture; not a real safety notice.",
            "high",
        )
    if not db.session.scalar(
        select(CaseSource.id).where(
            CaseSource.case_id == case.id, CaseSource.lot_id == lots["C10"].id
        )
    ):
        source(company_id, case.id, lots["C10"].id, "Fictional supplier quality finding for C10")
    return {
        "case_id": case.id,
        "lots": {code: row.id for code, row in lots.items()},
        "shipment_lines": {code: row.id for code, row in shipments.items()},
        "location_id": location.id,
        "warehouse_id": warehouse.id,
        "site_id": site.id,
        "customer_id": customer.id,
    }
