"""The live factory map: every department, its machines and the work flowing between them.

Everything here is read from recorded data (machines, bookings, rolls, batches, bundles,
lots and shipments); nothing is simulated. The page refreshes these figures every 30 seconds.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.extensions import db
from app.models import ItemVariant
from app.models.factory import (
    CutBundle,
    DyeBatch,
    FactoryAlert,
    KnitRoll,
    Machine,
    MachineClass,
    OutputLog,
    WorkCenter,
)
from app.models.master import Lot, Site
from app.models.operations import Shipment, ShipmentLine, StockBalance
from app.services import planning, shopfloor

# The stations of the map in process order: (key, title, departments).
STATIONS = (
    ("yarn", "Yarn store", ()),
    ("knitting", "Knitting", ("knitting",)),
    ("dyeing", "Dyeing", ("dyeing",)),
    ("finishing", "Finishing", ("finishing", "relaxation")),
    ("cutting", "Cutting", ("cutting", "embellishment")),
    ("sewing", "Sewing", ("sewing",)),
    ("packing", "Packing", ("packing", "washing")),
    ("shipped", "Shipped", ()),
)


@dataclass
class Station:
    key: str
    title: str
    sites: list = field(default_factory=list)
    running: int = 0
    idle: int = 0
    down: int = 0
    load: float | None = None  # booked ÷ capacity today, percent
    figure: str = ""  # the headline number
    note: str = ""  # what the number means
    state: str = "ok"  # ok, busy, alert, quiet
    href: str | None = None


@dataclass
class Flow:
    source: str
    target: str
    amount: str
    label: str
    moving: bool


def _f(value, places=0):
    value = Decimal(value or 0)
    return f"{value:,.{places}f}"


def _sum(query):
    return Decimal(db.session.scalar(query) or 0)


def build(company_id, today=None):
    today = today or date.today()
    stations = {key: Station(key, title) for key, title, _ in STATIONS}
    department_of = {d: key for key, _, departments in STATIONS for d in departments}

    # Machines by department and status, and which sites each station spans.
    rows = db.session.execute(
        select(WorkCenter.department, Machine.status, func.count(Machine.id))
        .join(
            WorkCenter,
            (WorkCenter.id == Machine.work_center_id)
            & (WorkCenter.organization_id == Machine.organization_id),
        )
        .where(Machine.organization_id == company_id, Machine.archived_at.is_(None))
        .group_by(WorkCenter.department, Machine.status)
    ).all()
    for department, status, count in rows:
        station = stations.get(department_of.get(department))
        if station is None:
            continue
        if status == "active":
            station.running += count
        elif status == "idle":
            station.idle += count
        elif status == "maintenance":
            station.down += count
    site_rows = db.session.execute(
        select(WorkCenter.department, Site.name, func.count(WorkCenter.id))
        .join(
            Site,
            (Site.id == WorkCenter.site_id) & (Site.organization_id == WorkCenter.organization_id),
        )
        .where(WorkCenter.organization_id == company_id, WorkCenter.archived_at.is_(None))
        .group_by(WorkCenter.department, Site.name)
        .order_by(Site.name)
    ).all()
    for department, site, count in site_rows:
        station = stations.get(department_of.get(department))
        if station is not None and site not in [s for s, _ in station.sites]:
            station.sites.append((site, count))

    # Today's booked load against capacity.
    _, departments, _ = planning.load_board(company_id, today, 1)
    totals = {}
    for department, cells in departments:
        key = department_of.get(department)
        if key:
            cap, used = totals.get(key, (Decimal(0), Decimal(0)))
            totals[key] = (cap + cells[0][0], used + cells[0][1])
    for key, (cap, used) in totals.items():
        stations[key].load = float(used / cap * 100) if cap > 0 else None

    # Live work at each station.
    yarn_kg = _sum(
        select(func.sum(StockBalance.quantity))
        .join(
            Lot,
            (Lot.id == StockBalance.lot_id) & (Lot.organization_id == StockBalance.organization_id),
        )
        .join(
            ItemVariant,
            (ItemVariant.id == Lot.variant_id)
            & (ItemVariant.organization_id == Lot.organization_id),
        )
        .where(StockBalance.organization_id == company_id, ItemVariant.sku.like("YARN-%"))
    )
    stations["yarn"].figure, stations["yarn"].note = f"{_f(yarn_kg)} kg", "yarn in stock"
    knitted = _sum(
        select(func.sum(KnitRoll.kg)).where(
            KnitRoll.organization_id == company_id, KnitRoll.knitted_on >= today - timedelta(days=1)
        )
    )
    stations["knitting"].figure, stations["knitting"].note = (
        f"{_f(knitted)} kg",
        "knitted since yesterday",
    )
    dyeing = db.session.execute(
        select(func.count(DyeBatch.id)).where(
            DyeBatch.organization_id == company_id, DyeBatch.status == "dyeing"
        )
    ).scalar()
    stations["dyeing"].figure, stations["dyeing"].note = str(dyeing), "batches in the vessels now"
    stations["finishing"].figure = f"{stations['finishing'].running}"
    stations["finishing"].note = "machines running"
    cut_waiting = _sum(
        select(func.sum(CutBundle.pieces)).where(
            CutBundle.organization_id == company_id, CutBundle.status == "cut"
        )
    )
    stations["cutting"].figure, stations["cutting"].note = (
        _f(cut_waiting),
        "pieces cut, waiting for a line",
    )
    latest = db.session.scalar(
        select(func.max(OutputLog.day)).where(
            OutputLog.organization_id == company_id, OutputLog.day <= today
        )
    )
    lines = db.session.scalars(
        select(WorkCenter.id).where(
            WorkCenter.organization_id == company_id,
            WorkCenter.department == "sewing",
            WorkCenter.archived_at.is_(None),
        )
    ).all()
    good = 0
    reporting = 0
    if latest:
        for figures in shopfloor.floor(company_id, latest, lines).values():
            good += figures.good
            reporting += bool(figures.hours)
    stations["sewing"].figure = _f(good)
    stations["sewing"].note = (
        f"good pieces {'today' if latest == today else latest.strftime('%a %d %b') if latest else ''}"
        f" · {reporting} of {len(lines)} lines reporting"
    )
    sewn_waiting = _sum(
        select(func.sum(CutBundle.pieces)).where(
            CutBundle.organization_id == company_id,
            CutBundle.status == "sewn",
            CutBundle.garment_lot_id.is_(None),
        )
    )
    stations["packing"].figure, stations["packing"].note = (
        _f(sewn_waiting),
        "sewn pieces waiting to pack",
    )
    shipped = _sum(
        select(func.sum(ShipmentLine.quantity))
        .join(
            Shipment,
            (Shipment.id == ShipmentLine.shipment_id)
            & (Shipment.organization_id == ShipmentLine.organization_id),
        )
        .where(
            ShipmentLine.organization_id == company_id,
            Shipment.status == "posted",
            Shipment.updated_at >= func.now() - timedelta(days=7),
        )
    )
    stations["shipped"].figure, stations["shipped"].note = _f(shipped), "pieces shipped this week"

    # Station state: an alert, a busy department, or quiet.
    alert_departments = set(
        db.session.scalars(
            select(WorkCenter.department)
            .join(
                FactoryAlert,
                (FactoryAlert.work_center_id == WorkCenter.id)
                & (FactoryAlert.organization_id == WorkCenter.organization_id),
            )
            .where(
                FactoryAlert.organization_id == company_id,
                FactoryAlert.status != "resolved",
                FactoryAlert.cleared_at.is_(None),
                FactoryAlert.severity == "critical",
            )
        )
    )
    for key, _, departments in STATIONS:
        station = stations[key]
        if set(departments) & alert_departments:
            station.state = "alert"
        elif station.down or (station.load is not None and station.load > 85):
            station.state = "busy"
        elif departments and not station.running:
            station.state = "quiet"

    # Work waiting between stations.
    waiting_rolls = sum((r.kg for r in shopfloor.loadable_rolls(company_id)), Decimal(0))
    passed_uncut = _sum(
        select(func.sum(KnitRoll.kg))
        .join(
            DyeBatch,
            (DyeBatch.id == KnitRoll.dye_batch_id)
            & (DyeBatch.organization_id == KnitRoll.organization_id),
        )
        .where(
            KnitRoll.organization_id == company_id,
            DyeBatch.status == "passed",
            ~select(CutBundle.id)
            .where(CutBundle.organization_id == company_id, CutBundle.dye_batch_id == DyeBatch.id)
            .exists(),
        )
    )
    on_lines = _sum(
        select(func.sum(CutBundle.pieces)).where(
            CutBundle.organization_id == company_id, CutBundle.status == "issued"
        )
    )
    packed = _sum(
        select(func.sum(StockBalance.quantity))
        .join(
            Lot,
            (Lot.id == StockBalance.lot_id) & (Lot.organization_id == StockBalance.organization_id),
        )
        .join(
            ItemVariant,
            (ItemVariant.id == Lot.variant_id)
            & (ItemVariant.organization_id == Lot.organization_id),
        )
        .where(StockBalance.organization_id == company_id, ItemVariant.sku.like("GMT-%"))
    )
    flows = [
        Flow("yarn", "knitting", f"{_f(yarn_kg)} kg", "yarn available", yarn_kg > 0),
        Flow(
            "knitting",
            "dyeing",
            f"{_f(waiting_rolls)} kg",
            "greige rolls waiting",
            waiting_rolls > 0,
        ),
        Flow("dyeing", "finishing", f"{dyeing}", "batches dyeing", dyeing > 0),
        Flow(
            "finishing",
            "cutting",
            f"{_f(passed_uncut)} kg",
            "fabric ready to cut",
            passed_uncut > 0,
        ),
        Flow("cutting", "sewing", f"{_f(on_lines)} pcs", "bundles on the lines", on_lines > 0),
        Flow("sewing", "packing", f"{_f(sewn_waiting)} pcs", "sewn, to pack", sewn_waiting > 0),
        Flow("packing", "shipped", f"{_f(packed)} pcs", "packed, ready to ship", packed > 0),
    ]
    return [stations[key] for key, _, _ in STATIONS], flows, latest


def as_json(stations, flows):
    return {
        "stations": [
            {
                k: v
                for k, v in asdict(s).items()
                if k in ("key", "running", "idle", "down", "load", "figure", "note", "state")
            }
            for s in stations
        ],
        "flows": [asdict(f) for f in flows],
    }


def department_machines(company_id, departments):
    """[(work centre, [(Machine, class name)])] for a station's departments, for the drill-in."""
    centers = db.session.scalars(
        select(WorkCenter)
        .where(
            WorkCenter.organization_id == company_id,
            WorkCenter.department.in_(departments),
            WorkCenter.archived_at.is_(None),
        )
        .order_by(WorkCenter.code)
    ).all()
    rows = (
        db.session.execute(
            select(Machine, MachineClass.name)
            .join(
                MachineClass,
                (MachineClass.id == Machine.machine_class_id)
                & (MachineClass.organization_id == Machine.organization_id),
            )
            .where(
                Machine.organization_id == company_id,
                Machine.work_center_id.in_([c.id for c in centers]),
                Machine.archived_at.is_(None),
            )
            .order_by(Machine.asset_tag)
        ).all()
        if centers
        else []
    )
    grouped = {}
    for machine, name in rows:
        grouped.setdefault(machine.work_center_id, []).append((machine, name))
    return [(center, grouped.get(center.id, [])) for center in centers]
