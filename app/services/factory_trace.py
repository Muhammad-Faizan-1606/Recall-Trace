"""Connect the factory floor to RecallTrace's lot genealogy, from yarn to carton.

Each stage is posted as an ordinary Core production run through the existing operations
services (the same validation, stock journal, idempotency and genealogy checks as the
Operations screens), so the existing recall trace follows the chain without changes:

    received yarn lot ──knit & dye──▶ fabric lot  FAB-<batch>           (kg)
    fabric lot        ──cut a lay───▶ cut lot     CUT-<order>-<lay>     (pieces)
    cut lots          ──sew & pack──▶ garment lot <order>-G<n>          (pieces)
    garment lot       ──ship────────▶ shipment lines to the buyer (Operations screens)

Work-in-progress stock is held in one factory WIP location. Moves between sites are
planned (transit times) but not posted as stock transfers; genealogy, which is what a recall
needs, is complete either way.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select

from app.extensions import db
from app.models import Item, ItemVariant, UnitsOfMeasure
from app.models.factory import CutBundle, DyeBatch, FabricSpec, KnitRoll, ProductionOrder, Style
from app.models.master import Lot, Site, StorageLocation, Warehouse
from app.models.operations import ProductionRun, StockBalance
from app.policies import require
from app.services import operations as op
from app.services.audit import record as audit
from app.services.business import DomainError, company_lock, scoped

WIP_WAREHOUSE = "FACTORY-WIP"
WIP_LOCATION = "WIP"
YARN_PREFIX = "YARN-"
KG = Decimal("0.001")


@dataclass
class Master:
    site: Site
    warehouse: Warehouse
    location: StorageLocation
    kg: UnitsOfMeasure
    pcs: UnitsOfMeasure


def _unit(company_id, code, name, dimension, places):
    unit = db.session.scalar(
        select(UnitsOfMeasure).where(
            UnitsOfMeasure.organization_id == company_id, UnitsOfMeasure.code == code
        )
    )
    if unit is None:
        unit = UnitsOfMeasure(
            organization_id=company_id,
            code=code,
            name=name,
            dimension=dimension,
            decimal_places=places,
        )
        db.session.add(unit)
        db.session.flush()
    return unit


def ensure_master(company_id):
    """Units, the factory WIP warehouse and location: created once, inside the caller's work."""
    site = db.session.scalar(
        select(Site)
        .where(Site.organization_id == company_id, Site.archived_at.is_(None))
        .order_by(Site.code)
        .limit(1)
    )
    if site is None:
        raise DomainError("Add a site before posting factory work to traceability.")
    warehouse = db.session.scalar(
        select(Warehouse).where(
            Warehouse.organization_id == company_id, Warehouse.code == WIP_WAREHOUSE
        )
    )
    if warehouse is None:
        warehouse = Warehouse(
            organization_id=company_id,
            site_id=site.id,
            code=WIP_WAREHOUSE,
            name="Factory work in progress",
        )
        db.session.add(warehouse)
        db.session.flush()
    location = db.session.scalar(
        select(StorageLocation).where(
            StorageLocation.organization_id == company_id,
            StorageLocation.warehouse_id == warehouse.id,
            StorageLocation.code == WIP_LOCATION,
        )
    )
    if location is None:
        location = StorageLocation(
            organization_id=company_id,
            warehouse_id=warehouse.id,
            code=WIP_LOCATION,
            name="Factory floor WIP",
            kind="production",
        )
        db.session.add(location)
        db.session.flush()
    site = db.session.get(Site, warehouse.site_id)
    return Master(
        site,
        warehouse,
        location,
        _unit(company_id, "KG", "Kilogram", "mass", 3),
        _unit(company_id, "PCS", "Pieces", "count", 0),
    )


def variant(company_id, code, name, kind, unit):
    """The item variant for `code`, created on first use."""
    row = db.session.scalar(
        select(ItemVariant).where(
            ItemVariant.organization_id == company_id, ItemVariant.sku == code
        )
    )
    if row is not None:
        return row
    item = db.session.scalar(
        select(Item).where(Item.organization_id == company_id, Item.code == code)
    )
    if item is None:
        item = Item(organization_id=company_id, code=code, name=name[:160], kind=kind)
        db.session.add(item)
        db.session.flush()
    row = ItemVariant(
        organization_id=company_id, item_id=item.id, sku=code, revision="A", base_unit_id=unit.id
    )
    db.session.add(row)
    db.session.flush()
    return row


def garment_variant(company_id, style, master):
    """The style's finished-goods variant, linking the style to its item the first time."""
    if style.item_id:
        found = db.session.scalar(
            select(ItemVariant)
            .where(ItemVariant.organization_id == company_id, ItemVariant.item_id == style.item_id)
            .order_by(ItemVariant.created_at)
            .limit(1)
        )
        if found is not None:
            return found
    row = variant(company_id, f"GMT-{style.code}", style.name, "finished", master.pcs)
    if style.item_id is None:
        style.item_id = row.item_id
    return row


def new_lot(company_id, code, variant_row):
    """The output lot for a stage. A retry after an interrupted posting reuses the lot it made;
    the production posting itself refuses a lot that already has stock history."""
    lot = db.session.scalar(
        select(Lot).where(Lot.organization_id == company_id, Lot.lot_code == code)
    )
    if lot is not None:
        if lot.variant_id != variant_row.id:
            raise DomainError(f"Lot {code} already exists for a different item.")
        return lot
    lot = Lot(organization_id=company_id, lot_code=code, variant_id=variant_row.id)
    db.session.add(lot)
    db.session.flush()
    return lot


def kg_text(value):
    """'240.5 kg' rather than Decimal's scientific notation."""
    return f"{Decimal(value).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):,f} kg"


def on_hand(company_id, lot_id, location_id):
    return db.session.scalar(
        select(StockBalance.quantity).where(
            StockBalance.organization_id == company_id,
            StockBalance.lot_id == lot_id,
            StockBalance.location_id == location_id,
        )
    ) or Decimal(0)


def post_run(company_id, reference, site_id, inputs, outputs):
    """Create and post one production run: [(lot id, location id, quantity)] in and out.

    The reference doubles as the idempotency key, so a retried posting resumes safely: a
    posted run is returned as it is, and a draft left by an interrupted attempt is replaced.
    """
    existing = db.session.scalar(
        select(ProductionRun).where(
            ProductionRun.organization_id == company_id, ProductionRun.reference == reference
        )
    )
    if existing is not None and existing.status == "posted":
        return existing
    if existing is not None and existing.status == "draft":
        op.delete_draft(company_id, "production", existing.id, existing.version)
    run = op.create_document(company_id, "production", {"reference": reference, "site_id": site_id})
    for lot_id, location_id, quantity in inputs:
        op.add_line(
            company_id,
            "production-inputs",
            run.id,
            {"lot_id": lot_id, "source_location_id": location_id, "quantity": str(quantity)},
        )
    for lot_id, location_id, quantity in outputs:
        op.add_line(
            company_id,
            "production-outputs",
            run.id,
            {"lot_id": lot_id, "destination_location_id": location_id, "quantity": str(quantity)},
        )
    return op.post_document(company_id, "production", run.id, f"factory:{reference}")


def _begin(company_id):
    require(company_id, "factory.manage")
    require(company_id, "production.post")
    company_lock(company_id)
    require(company_id, "factory.manage")


# ---------- Stage postings ----------


def post_batch(company_id, batch_id):
    """Knit and dye: the batch's yarn lots become one fabric lot named after the batch."""
    _begin(company_id)
    batch = scoped(DyeBatch, company_id, batch_id, lock=True)
    if batch.status != "passed":
        raise DomainError("Post fabric when the dye batch has passed its shade check.")
    if batch.fabric_lot_id:
        raise DomainError("This batch's fabric is already posted.")
    rolls = db.session.scalars(
        select(KnitRoll).where(
            KnitRoll.organization_id == company_id, KnitRoll.dye_batch_id == batch.id
        )
    ).all()
    if not rolls:
        raise DomainError("This batch has no rolls.")
    if any(r.yarn_lot_id is None for r in rolls):
        raise DomainError("Record the yarn lot on every roll of the batch first.")
    master = ensure_master(company_id)
    yarn = {}
    for roll in rolls:
        yarn[roll.yarn_lot_id] = yarn.get(roll.yarn_lot_id, Decimal(0)) + roll.kg
    for lot_id, kg in yarn.items():
        have = on_hand(company_id, lot_id, master.location.id)
        if have < kg:
            lot = db.session.get(Lot, lot_id)
            raise DomainError(
                f"Yarn lot {lot.lot_code} has {kg_text(have)} in factory WIP; the rolls used "
                f"{kg_text(kg)}. Receive the yarn into {WIP_WAREHOUSE} first."
            )
    order = (
        scoped(ProductionOrder, company_id, batch.production_order_id)
        if batch.production_order_id
        else None
    )
    style = scoped(Style, company_id, order.style_id) if order else None
    fabric = variant(
        company_id,
        f"FAB-{style.code}" if style else "FAB-GENERIC",
        f"Dyed fabric for {style.name}" if style else "Dyed fabric",
        "component",
        master.kg,
    )
    lot = new_lot(company_id, f"FAB-{batch.batch_number}", fabric)
    db.session.commit()
    total = sum(yarn.values())
    post_run(
        company_id,
        f"KD-{batch.batch_number}",
        master.site.id,
        [(lot_id, master.location.id, kg) for lot_id, kg in yarn.items()],
        [(lot.id, master.location.id, total)],
    )
    _begin(company_id)
    batch = scoped(DyeBatch, company_id, batch_id, lock=True)
    batch.fabric_lot_id = lot.id
    audit(
        company_id, "factory.trace_fabric_posted", "dye_batches", batch.id, {"lot_id": str(lot.id)}
    )
    db.session.commit()
    return lot


def consumption_kg(company_id, style_id):
    """Fabric per garment (all components), in kg."""
    return db.session.scalar(
        select(func.coalesce(func.sum(FabricSpec.consumption_kg), 0)).where(
            FabricSpec.organization_id == company_id, FabricSpec.style_id == style_id
        )
    ) or Decimal(0)


def post_lays(company_id, order_id):
    """Cut: each unposted lay of the order becomes a cut-panel lot made from its fabric lot."""
    _begin(company_id)
    order = scoped(ProductionOrder, company_id, order_id, lock=True)
    style = scoped(Style, company_id, order.style_id)
    bundles = db.session.scalars(
        select(CutBundle)
        .where(
            CutBundle.organization_id == company_id,
            CutBundle.production_order_id == order.id,
            CutBundle.cut_lot_id.is_(None),
        )
        .order_by(CutBundle.bundle_number)
    ).all()
    lays = {}
    for bundle in bundles:
        lays.setdefault(bundle.lay_number, []).append(bundle)
    if not lays:
        raise DomainError("Every cut lay of this order is already posted.")
    master = ensure_master(company_id)
    per_piece = Decimal(consumption_kg(company_id, style.id))
    panels = variant(
        company_id, f"PNL-{style.code}", f"Cut panels for {style.name}", "component", master.pcs
    )
    posted = []
    for lay, rows in lays.items():
        batch_ids = {b.dye_batch_id for b in rows}
        if None in batch_ids or len(batch_ids) != 1:
            raise DomainError(f"Lay {lay} must be cut from one recorded dye batch to be traced.")
        batch = scoped(DyeBatch, company_id, batch_ids.pop())
        if not batch.fabric_lot_id:
            raise DomainError(f"Post the fabric of batch {batch.batch_number} before lay {lay}.")
        pieces = sum(b.pieces for b in rows)
        kg = (per_piece * pieces).quantize(KG, rounding=ROUND_HALF_UP)
        have = on_hand(company_id, batch.fabric_lot_id, master.location.id)
        if kg <= 0 or have < kg:
            raise DomainError(
                f"Lay {lay} needs {kg_text(kg)} of fabric; batch {batch.batch_number} has "
                f"{kg_text(have)} left in factory WIP."
            )
        code = f"CUT-{order.reference}-{lay}"[:80]
        lot = new_lot(company_id, code, panels)
        db.session.commit()
        post_run(
            company_id,
            f"CT-{order.reference}-{lay}"[:80],
            master.site.id,
            [(batch.fabric_lot_id, master.location.id, kg)],
            [(lot.id, master.location.id, pieces)],
        )
        _begin(company_id)
        for bundle in rows:
            row = scoped(CutBundle, company_id, bundle.id, lock=True)
            row.cut_lot_id = lot.id
        audit(
            company_id,
            "factory.trace_lay_posted",
            "production_orders",
            order.id,
            {"lot_id": str(lot.id), "quantity": pieces},
        )
        db.session.commit()
        posted.append(lot)
    return posted


def post_packing(company_id, order_id):
    """Sew and pack: sewn, unpacked bundles become one garment lot for the order."""
    _begin(company_id)
    order = scoped(ProductionOrder, company_id, order_id, lock=True)
    style = scoped(Style, company_id, order.style_id)
    bundles = db.session.scalars(
        select(CutBundle).where(
            CutBundle.organization_id == company_id,
            CutBundle.production_order_id == order.id,
            CutBundle.status == "sewn",
            CutBundle.garment_lot_id.is_(None),
        )
    ).all()
    if not bundles:
        raise DomainError("No sewn bundles are waiting to be packed.")
    if any(b.cut_lot_id is None for b in bundles):
        raise DomainError("Post the cut lays of this order before packing.")
    master = ensure_master(company_id)
    inputs = {}
    for bundle in bundles:
        inputs[bundle.cut_lot_id] = inputs.get(bundle.cut_lot_id, 0) + bundle.pieces
    for lot_id, pieces in inputs.items():
        if on_hand(company_id, lot_id, master.location.id) < pieces:
            raise DomainError("A cut lot has fewer panels in WIP than the sewn bundles need.")
    count = db.session.scalar(
        select(func.count(Lot.id)).where(
            Lot.organization_id == company_id, Lot.lot_code.like(f"{order.reference}-G%")
        )
    )
    garments = garment_variant(company_id, style, master)
    lot = new_lot(company_id, f"{order.reference}-G{count + 1}", garments)
    db.session.commit()
    total = sum(inputs.values())
    post_run(
        company_id,
        f"PK-{order.reference}-G{count + 1}",
        master.site.id,
        [(lot_id, master.location.id, pieces) for lot_id, pieces in inputs.items()],
        [(lot.id, master.location.id, total)],
    )
    _begin(company_id)
    for bundle in bundles:
        row = scoped(CutBundle, company_id, bundle.id, lock=True)
        row.garment_lot_id = lot.id
    audit(
        company_id,
        "factory.trace_packed",
        "production_orders",
        order.id,
        {"lot_id": str(lot.id), "quantity": total},
    )
    db.session.commit()
    return lot


# ---------- Reading the chain ----------


@dataclass
class Chain:
    yarn: dict = field(default_factory=dict)  # lot id -> Lot
    batches: list = field(
        default_factory=list
    )  # [(DyeBatch, fabric Lot | None, roll count, yarn lot ids)]
    lays: list = field(default_factory=list)  # [(lay, pieces, cut Lot | None, batch)]
    garments: list = field(default_factory=list)  # [(Lot, pieces)]
    shipments: list = field(default_factory=list)  # [(Shipment, ShipmentLine)]
    sewn_unpacked: int = 0


def chain(company_id, order_id):
    from app.models.operations import Shipment, ShipmentLine

    order = scoped(ProductionOrder, company_id, order_id)
    result = Chain()
    batches = db.session.scalars(
        select(DyeBatch).where(
            DyeBatch.organization_id == company_id, DyeBatch.production_order_id == order.id
        )
    ).all()
    bundles = db.session.scalars(
        select(CutBundle).where(
            CutBundle.organization_id == company_id, CutBundle.production_order_id == order.id
        )
    ).all()
    batch_ids = {b.id for b in batches} | {b.dye_batch_id for b in bundles if b.dye_batch_id}
    if batch_ids - {b.id for b in batches}:
        batches += db.session.scalars(
            select(DyeBatch).where(
                DyeBatch.organization_id == company_id,
                DyeBatch.id.in_(batch_ids - {b.id for b in batches}),
            )
        ).all()
    rolls = (
        db.session.scalars(
            select(KnitRoll).where(
                KnitRoll.organization_id == company_id, KnitRoll.dye_batch_id.in_(batch_ids)
            )
        ).all()
        if batch_ids
        else []
    )
    lot_ids = (
        {r.yarn_lot_id for r in rolls}
        | {b.fabric_lot_id for b in batches}
        | {b.cut_lot_id for b in bundles}
        | {b.garment_lot_id for b in bundles}
    )
    lot_ids.discard(None)
    lots = (
        {
            lot.id: lot
            for lot in db.session.scalars(
                select(Lot).where(Lot.organization_id == company_id, Lot.id.in_(lot_ids))
            )
        }
        if lot_ids
        else {}
    )
    for batch in sorted(batches, key=lambda b: b.batch_number):
        mine = [r for r in rolls if r.dye_batch_id == batch.id]
        yarn_ids = {r.yarn_lot_id for r in mine if r.yarn_lot_id}
        for yarn_id in yarn_ids:
            result.yarn[yarn_id] = lots[yarn_id]
        result.batches.append((batch, lots.get(batch.fabric_lot_id), len(mine), yarn_ids))
    by_lay = {}
    for bundle in bundles:
        lay = by_lay.setdefault(bundle.lay_number, [0, None, bundle.dye_batch_id])
        lay[0] += bundle.pieces
        lay[1] = lay[1] or lots.get(bundle.cut_lot_id)
    names = {b.id: b for b in batches}
    result.lays = [
        (lay, pieces, lot, names.get(batch_id))
        for lay, (pieces, lot, batch_id) in sorted(by_lay.items())
    ]
    packed = {}
    for bundle in bundles:
        if bundle.garment_lot_id:
            packed[bundle.garment_lot_id] = packed.get(bundle.garment_lot_id, 0) + bundle.pieces
        elif bundle.status == "sewn":
            result.sewn_unpacked += bundle.pieces
    result.garments = [
        (lots[lot_id], pieces)
        for lot_id, pieces in sorted(packed.items(), key=lambda p: lots[p[0]].lot_code)
    ]
    if packed:
        result.shipments = db.session.execute(
            select(Shipment, ShipmentLine)
            .join(ShipmentLine, ShipmentLine.shipment_id == Shipment.id)
            .where(
                Shipment.organization_id == company_id,
                ShipmentLine.lot_id.in_(list(packed)),
            )
            .order_by(Shipment.reference)
        ).all()
    return result


def yarn_lots(company_id):
    """Lots of yarn variants, for choosing the yarn a roll was knitted from."""
    return db.session.scalars(
        select(Lot)
        .join(
            ItemVariant,
            (ItemVariant.id == Lot.variant_id)
            & (ItemVariant.organization_id == Lot.organization_id),
        )
        .where(
            Lot.organization_id == company_id,
            Lot.archived_at.is_(None),
            ItemVariant.sku.like(f"{YARN_PREFIX}%"),
        )
        .order_by(Lot.lot_code)
    ).all()
