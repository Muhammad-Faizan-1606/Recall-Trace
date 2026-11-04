"""Fictional, self-explanatory demonstration records around the C10 investigation.

Everything goes through the normal services, so validation, permissions, versioning and
audit apply exactly as for a user. The command is idempotent: existing records (matched
by code or reference) are preserved, and fixture names are only replaced while they
still have their original generic value.
"""

from sqlalchemy import select

from app.extensions import db
from app.models import Item, ItemVariant, Membership
from app.models.master import (
    Carrier,
    ItemCategory,
    ItemCategoryAssignment,
    Lot,
    Partner,
    PartnerAddress,
    PartnerContact,
    Site,
    StorageLocation,
    SupplierItem,
    Warehouse,
)
from app.models.quality import Inspection, InspectionCheck, InspectionTemplate, Nonconformance
from app.models.recall import CaseComment, CaseTask, RecallCase
from app.services import catalog, master, quality, recall

# (model, code field, code, old fixture name, clearer fictional name)
RENAMES = [
    (Item, "code", "C10-LAMP", "Demonstration lamp", "LED desk lamp"),
    (Item, "code", "C10-SWITCH", "Demonstration switch", "Lamp power switch"),
    (
        Partner,
        "code",
        "C10-SUPPLIER",
        "Fictional Switch Supplier",
        "Brightway Components (fictional switch supplier)",
    ),
    (
        Partner,
        "code",
        "C10-CUSTOMER",
        "Fictional Lamp Customer",
        "Northside Home Stores (fictional retailer)",
    ),
    (
        Site,
        "code",
        "C10-SITE",
        "Fictional demonstration factory",
        "Lamp assembly plant (fictional)",
    ),
    (Warehouse, "code", "C10-WH", "Demonstration warehouse", "Main warehouse"),
    (StorageLocation, "code", "C10-STOCK", "Demonstration stock", "Stock room, shelf A"),
]


def _one(model, company_id, **filters):
    return db.session.scalar(select(model).filter_by(organization_id=company_id, **filters))


def _master_values(resource, row, **changes):
    values = {field: getattr(row, field) for field in master.FIELDS[resource]}
    values.update(changes)
    return values


def _rename(company_id, report):
    resources = {
        Partner: "partners",
        Site: "sites",
        Warehouse: "warehouses",
        StorageLocation: "locations",
    }
    for model, field, code, old, new in RENAMES:
        row = _one(model, company_id, **{field: code})
        if row is None or row.name != old:
            continue
        if model is Item:
            catalog.save(
                company_id,
                "items",
                {"code": row.code, "name": new, "kind": row.kind},
                row.id,
                row.version,
            )
        else:
            resource = resources[model]
            master.save(
                company_id, resource, _master_values(resource, row, name=new), row.id, row.version
            )
        report.append(f"Renamed {code}: {new}")


def _create_master(company_id, resource, model, match, values, report, description):
    if _one(model, company_id, **match) is None:
        master.save(company_id, resource, values)
        report.append(f"Added {description}")


def seed_extras(company_id, owner_membership_id):
    """Create or reuse the demonstration records; return a list of what changed."""
    report = []
    _rename(company_id, report)
    lamp = _one(Item, company_id, code="C10-LAMP")
    switch = _one(Item, company_id, code="C10-SWITCH")
    switch_variant = _one(ItemVariant, company_id, sku="C10-SWITCH-01")
    supplier = _one(Partner, company_id, code="C10-SUPPLIER")
    customer = _one(Partner, company_id, code="C10-CUSTOMER")
    c10 = _one(Lot, company_id, lot_code="C10")
    if not all([lamp, switch, switch_variant, supplier, customer, c10]):
        raise ValueError("Seed the C10 investigation before adding demonstration extras.")

    # Catalog classification.
    finished = "FINISHED-LIGHTING"
    _create_master(
        company_id,
        "categories",
        ItemCategory,
        {"code": finished},
        {"code": finished, "name": "Finished lighting products", "parent_id": None},
        report,
        "category Finished lighting products",
    )
    components = "ELECTRICAL-PARTS"
    _create_master(
        company_id,
        "categories",
        ItemCategory,
        {"code": components},
        {"code": components, "name": "Electrical components", "parent_id": None},
        report,
        "category Electrical components",
    )
    parent = _one(ItemCategory, company_id, code=components)
    _create_master(
        company_id,
        "categories",
        ItemCategory,
        {"code": "SWITCHES"},
        {"code": "SWITCHES", "name": "Switches", "parent_id": parent.id},
        report,
        "category Switches (inside Electrical components)",
    )
    for item, code in [(lamp, finished), (switch, "SWITCHES")]:
        category = _one(ItemCategory, company_id, code=code)
        _create_master(
            company_id,
            "classifications",
            ItemCategoryAssignment,
            {"item_id": item.id, "category_id": category.id},
            {"item_id": item.id, "category_id": category.id},
            report,
            f"classification {item.code} in {category.name}",
        )

    # Partner contacts, addresses and the supplier's own part number.
    for partner, name, email, phone, purpose in [
        (
            supplier,
            "Ayesha Khan, supplier quality manager",
            "quality@brightway-components.test",
            "+92 42 0000 0001",
            "Quality complaints and lot investigations",
        ),
        (
            customer,
            "Bilal Ahmed, recall coordinator",
            "recalls@northside-stores.test",
            "+92 21 0000 0002",
            "Receives recall notices and confirms returned stock",
        ),
    ]:
        _create_master(
            company_id,
            "contacts",
            PartnerContact,
            {"partner_id": partner.id, "email": email},
            {
                "partner_id": partner.id,
                "name": name,
                "email": email,
                "phone": phone,
                "purpose": purpose,
            },
            report,
            f"contact {name}",
        )
    for partner, label, address in [
        (supplier, "Head office and factory", "Plot 12, Industrial Estate, Lahore (fictional)"),
        (customer, "Distribution centre", "Warehouse 4, Ring Road, Karachi (fictional)"),
    ]:
        _create_master(
            company_id,
            "addresses",
            PartnerAddress,
            {"partner_id": partner.id, "label": label},
            {
                "partner_id": partner.id,
                "label": label,
                "address_text": address,
                "country_code": "PK",
            },
            report,
            f"address {label}",
        )
    _create_master(
        company_id,
        "supplier-items",
        SupplierItem,
        {"partner_id": supplier.id, "variant_id": switch_variant.id},
        {
            "partner_id": supplier.id,
            "variant_id": switch_variant.id,
            "supplier_sku": "BW-SW-200",
            "lead_time_days": 14,
        },
        report,
        "supplier part BW-SW-200 for the lamp power switch",
    )
    _create_master(
        company_id,
        "carriers",
        Carrier,
        {"code": "SWIFT-FREIGHT"},
        {
            "code": "SWIFT-FREIGHT",
            "name": "Swift Freight (fictional courier)",
            "tracking_url_template": "https://tracking.example.test/track/{tracking}",
        },
        report,
        "carrier Swift Freight",
    )

    # Quality: a published incoming-inspection checklist and a failed inspection of C10.
    template = _one(InspectionTemplate, company_id, code="INCOMING-SWITCH-CHECK", revision=1)
    if template is None:
        template = quality.save_template(company_id, "INCOMING-SWITCH-CHECK", 1)
        for sequence, label, value_type, rule in [
            (1, "Switch press force in newtons (allowed 2 to 6)", "number", {"min": 2, "max": 6}),
            (2, "Casing free of cracks or burn marks", "boolean", {"equals": True}),
        ]:
            quality.save_check(company_id, template.id, sequence, label, value_type, rule)
        quality.publish_template(company_id, template.id, template.version)
        report.append("Added and published inspection checklist INCOMING-SWITCH-CHECK")
    inspection = _one(Inspection, company_id, reference="INSPECTION-C10-001")
    if inspection is None:
        inspection = quality.create_inspection(
            company_id, "INSPECTION-C10-001", c10.id, template.id
        )
        checks = db.session.scalars(
            select(InspectionCheck)
            .where(InspectionCheck.template_id == template.id)
            .order_by(InspectionCheck.sequence)
        ).all()
        for check, value, comment in [
            (checks[0], "7.4", "Measured on 20 sample switches; average above the limit."),
            (checks[1], False, "Three samples show scorch marks near the contacts."),
        ]:
            db.session.refresh(inspection)
            quality.observe(company_id, inspection.id, check.id, value, comment, inspection.version)
        db.session.refresh(inspection)
        quality.complete_inspection(company_id, inspection.id, inspection.version)
        report.append("Added completed inspection INSPECTION-C10-001 (2 failed checks)")
    if _one(Nonconformance, company_id, reference="QUALITY-ISSUE-C10-001") is None:
        quality.save_nonconformance(
            company_id,
            "QUALITY-ISSUE-C10-001",
            c10.id,
            "Switch lot C10 fails incoming inspection: press force above specification and "
            "scorch marks near the contacts. Customer reports of lamps flickering or warming "
            "at the switch. Fictional demonstration record.",
            "high",
            inspection_id=inspection.id,
        )
        report.append("Added quality issue QUALITY-ISSUE-C10-001 (high)")

    # Investigation work and discussion on the C10 case.
    case = _one(RecallCase, company_id, reference="C10-INVESTIGATION")
    owner = db.session.get(Membership, owner_membership_id)
    if case is not None and owner is not None:
        title = "Confirm affected lamps with the retailer"
        if _one(CaseTask, company_id, case_id=case.id, title=title) is None:
            recall.task(
                company_id,
                case.id,
                title,
                "Ask Northside Home Stores how many lamps from shipments C10-S1 and C10-S2 "
                "are still on their shelves, and agree how they will be returned.",
                owner.id,
            )
            report.append(f"Added investigation task: {title}")
        body = (
            "Supplier confirmed that switch lot C10 used a substitute contact material. "
            "Lamp lots L1 and L2 were built with C10 switches; lot L3 used switch lot C11 "
            "and is not affected. (Fictional demonstration note.)"
        )
        if _one(CaseComment, company_id, case_id=case.id, body=body) is None:
            recall.comment(company_id, case.id, body)
            report.append("Added investigation discussion note")
    return report
