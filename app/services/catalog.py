"""Each mutation owns its transaction; database FKs enforce tenant boundaries."""

from flask import abort
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import Item, ItemVariant, UnitsOfMeasure, now
from app.policies import require

MODELS = {"items": Item, "variants": ItemVariant, "units": UnitsOfMeasure}
FIELDS = {
    "items": ("code", "name", "kind"),
    "units": ("code", "name", "dimension", "decimal_places"),
    "variants": ("sku", "revision", "description", "item_id", "base_unit_id"),
}


class CatalogConflict(Exception):
    pass


def lookup(company_id, kind, record_id, lock=False):
    require(company_id, "catalog.read")
    query = select(MODELS[kind]).where(
        MODELS[kind].organization_id == company_id, MODELS[kind].id == record_id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = db.session.scalar(query)
    if record is None:
        abort(404)
    return record


def save(company_id, kind, values, record_id=None, version=None):
    require(company_id, "catalog.manage")
    try:
        record = (
            lookup(company_id, kind, record_id, lock=True)
            if record_id
            else MODELS[kind](organization_id=company_id)
        )
        if record_id and (record.version != version or record.archived_at):
            raise CatalogConflict("This record changed or was archived. Reload before editing.")
        if kind == "variants":
            # Lock parents in a stable order; archive/delete uses the same row locks.
            item = lookup(company_id, "items", values["item_id"], lock=True)
            unit = lookup(company_id, "units", values["base_unit_id"], lock=True)
            if item.archived_at or unit.archived_at:
                raise CatalogConflict("Choose active item and unit records.")
        if kind == "units" and record_id:
            used = db.session.scalar(
                select(ItemVariant.id)
                .where(
                    ItemVariant.organization_id == company_id, ItemVariant.base_unit_id == record.id
                )
                .limit(1)
            )
            if used and any(
                getattr(record, key) != values[key] for key in ("dimension", "decimal_places")
            ):
                raise CatalogConflict("Referenced unit semantics cannot change; create a new unit.")
        for field in FIELDS[kind]:
            setattr(record, field, values[field])
        db.session.add(record)
        db.session.commit()
        return record
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise CatalogConflict(
            "Code/SKU already exists or a related record changed. Reload and try again."
        ) from exc
    except CatalogConflict:
        db.session.rollback()
        raise


def remove(company_id, kind, record_id, version):
    require(company_id, "catalog.manage")
    try:
        record = lookup(company_id, kind, record_id, lock=True)
        if record.version != version:
            raise CatalogConflict("This record changed. Reload before removing it.")
        referenced = False
        if kind in ("items", "units"):
            field = ItemVariant.item_id if kind == "items" else ItemVariant.base_unit_id
            referenced = (
                db.session.scalar(
                    select(ItemVariant.id)
                    .where(ItemVariant.organization_id == company_id, field == record_id)
                    .limit(1)
                )
                is not None
            )
        if referenced:
            record.archived_at = now()
            message = "Referenced record archived; existing variants preserved."
        else:
            db.session.delete(record)
            message = "Unused record deleted."
        db.session.commit()
        return message
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise CatalogConflict("Record is referenced or changed; reload before retrying.") from exc
    except CatalogConflict:
        db.session.rollback()
        raise
