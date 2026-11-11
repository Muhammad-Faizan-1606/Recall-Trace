"""Finite master-data operations; each mutation owns a checked transaction."""

import uuid
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email
from flask import g
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import Item, ItemVariant, now
from app.models.master import (
    Carrier,
    ItemCategory,
    ItemCategoryAssignment,
    Lot,
    Partner,
    PartnerAddress,
    PartnerContact,
    PartnerRoleAssignment,
    Site,
    StorageLocation,
    SupplierItem,
    Warehouse,
)
from app.policies import require
from app.services.audit import record as audit
from app.services.business import DomainError, company_lock, scoped

MODELS = {
    "sites": Site,
    "partners": Partner,
    "partner-roles": PartnerRoleAssignment,
    "contacts": PartnerContact,
    "addresses": PartnerAddress,
    "categories": ItemCategory,
    "classifications": ItemCategoryAssignment,
    "supplier-items": SupplierItem,
    "warehouses": Warehouse,
    "locations": StorageLocation,
    "lots": Lot,
    "carriers": Carrier,
}
FIELDS = {
    "sites": ("code", "name", "address_text", "country_code"),
    "partners": ("code", "name", "status"),
    "partner-roles": ("partner_id", "role_code"),
    "contacts": ("partner_id", "name", "email", "phone", "purpose"),
    "addresses": ("partner_id", "label", "address_text", "country_code"),
    "categories": ("code", "name", "parent_id"),
    "classifications": ("item_id", "category_id"),
    "supplier-items": ("partner_id", "variant_id", "supplier_sku", "lead_time_days"),
    "warehouses": ("code", "name", "site_id"),
    "locations": ("code", "name", "kind", "warehouse_id"),
    "lots": (
        "lot_code",
        "supplier_lot_code",
        "variant_id",
        "supplier_id",
        "manufactured_at",
        "expires_on",
    ),
    "carriers": ("code", "name", "tracking_url_template"),
}
PARENTS = {
    "partner_id": Partner,
    "supplier_id": Partner,
    "variant_id": ItemVariant,
    "item_id": Item,
    "category_id": ItemCategory,
    "parent_id": ItemCategory,
    "site_id": Site,
    "warehouse_id": Warehouse,
}
OPTIONAL = {
    "email",
    "phone",
    "parent_id",
    "supplier_id",
    "lead_time_days",
    "supplier_lot_code",
    "manufactured_at",
    "expires_on",
    "tracking_url_template",
}


# Human-readable names for stored field names, shown on detail pages.
FIELD_LABELS = {
    "partner_id": "Partner",
    "supplier_id": "Supplier",
    "variant_id": "Product (SKU)",
    "item_id": "Item",
    "category_id": "Category",
    "parent_id": "Parent category",
    "site_id": "Site",
    "warehouse_id": "Warehouse",
    "lot_code": "Lot code",
    "supplier_lot_code": "Supplier's own lot code",
    "manufactured_at": "Manufactured at",
    "expires_on": "Expires on",
    "role_code": "Role",
    "address_text": "Address",
    "country_code": "Country",
    "supplier_sku": "Supplier's part number",
    "lead_time_days": "Lead time (days)",
    "tracking_url_template": "Tracking link template",
    "kind": "Location type",
}


def field_label(field):
    return FIELD_LABELS.get(field, field.replace("_", " ").capitalize())


def lot_name(lot):
    """'L1 — LED desk lamp': a lot code alone means nothing to a first-time reader."""
    # Lots of one product variant share a name, so look each variant up once per request.
    cache = g.setdefault("_variant_item_names", {})
    key = (lot.organization_id, lot.variant_id)
    if key not in cache:
        cache[key] = db.session.scalar(
            select(Item.name)
            .join(ItemVariant, ItemVariant.item_id == Item.id)
            .where(
                ItemVariant.id == lot.variant_id,
                ItemVariant.organization_id == lot.organization_id,
                Item.organization_id == lot.organization_id,
            )
        )
    item_name = cache[key]
    return f"{lot.lot_code} — {item_name}" if item_name else lot.lot_code


def label(row):
    if isinstance(row, Lot):
        return lot_name(row)
    for name in ("lot_code", "sku", "code", "supplier_sku", "name", "label", "role_code"):
        value = getattr(row, name, None)
        if value:
            detail = getattr(row, "name", "")
            return f"{value} — {detail}" if detail and detail != value else str(value)
    return str(row.id)


def lookup(company_id, resource, record_id, lock=False):
    require(company_id, "catalog.read")
    return scoped(MODELS[resource], company_id, record_id, lock=lock)


def references(row):
    """Find actual references using declared FKs, including workflows outside this module."""
    target = row.__table__
    for table in db.metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            matching = [
                element
                for element in constraint.elements
                if element.column.table is target and element.column.name == "id"
            ]
            if not matching:
                continue
            predicates = [matching[0].parent == row.id]
            if "organization_id" in table.c:
                predicates.append(table.c.organization_id == row.organization_id)
            if table is target:
                predicates.append(table.c.id != row.id)
            if db.session.execute(select(table.c.id).where(*predicates).limit(1)).first():
                return True
    return False


def _values(company_id, resource, values):
    result = {}
    model = MODELS[resource]
    for field in FIELDS[resource]:
        value = values.get(field)
        if isinstance(value, str):
            if "\x00" in value:
                raise DomainError("Text cannot contain NUL characters.")
            value = value.strip()
        if value in ("", None):
            if field in OPTIONAL:
                result[field] = None
                continue
            raise DomainError(f"{field.replace('_', ' ').capitalize()} is required.")
        if field in PARENTS:
            try:
                value = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
            except (TypeError, ValueError) as exc:
                raise DomainError("Choose a valid related record.") from exc
            parent = scoped(PARENTS[field], company_id, value, lock=True)
            if (
                getattr(parent, "archived_at", None)
                or getattr(parent, "status", "active") != "active"
            ):
                raise DomainError("Choose an active related record.")
        elif field == "lead_time_days":
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise DomainError("Lead time must be a whole number.") from exc
            if not 0 <= value <= 36500:
                raise DomainError("Lead time must be between 0 and 36500 days.")
        elif field == "manufactured_at":
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value)
                except ValueError as exc:
                    raise DomainError("Enter a valid manufacturing date and time.") from exc
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
        elif field == "expires_on":
            if isinstance(value, str):
                try:
                    value = date.fromisoformat(value)
                except ValueError as exc:
                    raise DomainError("Enter a valid expiry date.") from exc
        else:
            value = str(value)
            maximum = getattr(model.__table__.c[field].type, "length", None) or 4000
            if len(value) > maximum:
                raise DomainError(f"{field.replace('_', ' ').capitalize()} is too long.")
        result[field] = value
    if resource in ("sites", "addresses"):
        country = result["country_code"].upper()
        if len(country) != 2 or not country.isascii() or not country.isalpha():
            raise DomainError("Use a two-letter country code.")
        result["country_code"] = country
    choices = {
        "partners": ("status", ("active", "inactive")),
        "partner-roles": ("role_code", ("supplier", "customer", "distributor")),
        "locations": ("kind", ("storage", "quarantine", "dispatch", "production")),
    }
    if resource in choices:
        field, permitted = choices[resource]
        if result[field] not in permitted:
            raise DomainError("Choose a permitted classification.")
    if resource == "contacts":
        if not result["email"] and not result["phone"]:
            raise DomainError("Provide an email address or phone number.")
        if result["email"]:
            try:
                result["email"] = validate_email(
                    result["email"], check_deliverability=False, test_environment=True
                ).normalized
            except EmailNotValidError as exc:
                raise DomainError("Enter a valid contact email address.") from exc
    if resource == "supplier-items" or (resource == "lots" and result["supplier_id"]):
        partner_id = result.get("partner_id", result.get("supplier_id"))
        if not db.session.scalar(
            select(PartnerRoleAssignment.id).where(
                PartnerRoleAssignment.organization_id == company_id,
                PartnerRoleAssignment.partner_id == partner_id,
                PartnerRoleAssignment.role_code == "supplier",
            )
        ):
            raise DomainError("The selected partner must have the supplier role.")
    if resource == "lots" and result["manufactured_at"] and result["expires_on"]:
        if result["expires_on"] < result["manufactured_at"].date():
            raise DomainError("Expiry cannot precede manufacture.")
    if resource == "carriers" and result["tracking_url_template"]:
        url = result["tracking_url_template"]
        parsed = urlsplit(url.replace("{tracking}", "example"))
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or "\n" in url
            or "\r" in url
        ):
            raise DomainError("Tracking templates must be HTTPS URLs without credentials.")
        if "{" in url.replace("{tracking}", "") or "}" in url.replace("{tracking}", ""):
            raise DomainError("Only the {tracking} placeholder is supported.")
    return result


def _cycle(company_id, record_id, parent_id):
    seen = {record_id} if record_id else set()
    while parent_id:
        if parent_id in seen:
            raise DomainError("A category cannot become its own ancestor.")
        seen.add(parent_id)
        parent_id = scoped(ItemCategory, company_id, parent_id).parent_id


def save(company_id, resource, values, record_id=None, version=None):
    require(company_id, "catalog.manage")
    try:
        # Shared company guard prevents taxonomy cycles and semantic changes racing posting.
        company_lock(company_id)
        require(company_id, "catalog.manage")
        row = (
            lookup(company_id, resource, record_id, lock=True)
            if record_id
            else MODELS[resource](organization_id=company_id)
        )
        if record_id and (row.version != version or getattr(row, "archived_at", None)):
            raise DomainError("This record changed or was archived; reload before editing.")
        clean = _values(company_id, resource, values)
        if resource == "categories":
            _cycle(company_id, record_id, clean["parent_id"])
        frozen = {
            "lots": FIELDS["lots"],
            "warehouses": ("site_id",),
            "locations": ("warehouse_id", "kind"),
            "contacts": ("partner_id",),
            "addresses": ("partner_id",),
        }
        if record_id and resource in frozen and references(row):
            if any(getattr(row, field) != clean[field] for field in frozen[resource]):
                raise DomainError("Referenced identity cannot change; create a new record instead.")
        if (
            record_id
            and resource == "partner-roles"
            and (row.partner_id != clean["partner_id"] or row.role_code != clean["role_code"])
        ):
            _role_unused(company_id, row)
        for field, value in clean.items():
            setattr(row, field, value)
        db.session.add(row)
        db.session.flush()
        audit(
            company_id,
            "master.updated" if record_id else "master.created",
            row.__tablename__,
            row.id,
            {"version": row.version},
        )
        db.session.commit()
        return row
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError(
            "A duplicate code, association, or concurrent change prevented saving."
        ) from exc
    except Exception:
        db.session.rollback()
        raise


def _role_unused(company_id, row):
    usage = {
        "supplier": (
            ("supplier_items", "partner_id"),
            ("lots", "supplier_id"),
            ("purchase_orders", "supplier_id"),
            ("goods_receipts", "supplier_id"),
        ),
        "customer": (("sales_orders", "customer_id"),),
        "distributor": (("sales_orders", "customer_id"),),
    }
    for table_name, field in usage.get(row.role_code, ()):
        table = db.metadata.tables.get(table_name)
        if (
            table is not None
            and db.session.execute(
                select(table.c.id)
                .where(table.c.organization_id == company_id, table.c[field] == row.partner_id)
                .limit(1)
            ).first()
        ):
            raise DomainError(
                "This partner role is referenced by business records and cannot be removed."
            )


def _stock_present(company_id, resource, record_id):
    balances = db.metadata.tables.get("stock_balances")
    if balances is None or resource not in {"lots", "locations", "warehouses", "sites"}:
        return False
    query = select(balances.c.id).where(
        balances.c.organization_id == company_id, balances.c.quantity > 0
    )
    if resource == "lots":
        query = query.where(balances.c.lot_id == record_id)
    elif resource == "locations":
        query = query.where(balances.c.location_id == record_id)
    else:
        locations = StorageLocation.__table__
        query = query.join(locations, locations.c.id == balances.c.location_id)
        if resource == "warehouses":
            query = query.where(locations.c.warehouse_id == record_id)
        else:
            warehouses = Warehouse.__table__
            query = query.join(warehouses, warehouses.c.id == locations.c.warehouse_id).where(
                warehouses.c.site_id == record_id
            )
    return db.session.execute(query.limit(1)).first() is not None


def remove(company_id, resource, record_id, version):
    require(company_id, "catalog.manage")
    try:
        company_lock(company_id)
        require(company_id, "catalog.manage")
        row = lookup(company_id, resource, record_id, lock=True)
        if row.version != version:
            raise DomainError("This record changed; reload before removing it.")
        if _stock_present(company_id, resource, record_id):
            raise DomainError("Move or resolve the remaining stock before archiving this record.")
        if resource == "partner-roles":
            _role_unused(company_id, row)
        if references(row):
            if not hasattr(row, "archived_at"):
                raise DomainError("Referenced associations cannot be removed.")
            row.archived_at = now()
            message = "Referenced record archived; history preserved."
        else:
            db.session.delete(row)
            message = "Unused record deleted."
        audit(
            company_id,
            "master.archived" if getattr(row, "archived_at", None) else "master.deleted",
            row.__tablename__,
            row.id,
        )
        db.session.commit()
        return message
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError("A related record or concurrent change prevented removal.") from exc
    except Exception:
        db.session.rollback()
        raise
