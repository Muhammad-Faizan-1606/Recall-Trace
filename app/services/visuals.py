"""Data for the picture panels at the top of the factory sections.

Each panel is drawn by the server from recorded data (no simulation), in the same visual
language as the factory map: orders moving along the process, departments as tanks filling
with booked work, machines as lights in their rooms, line balances as skylines, bundles in
bins and dye vessels with their shade. Colours reach the browser as SVG attributes, so the
strict Content Security Policy needs no inline styles.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.extensions import db
from app.models.factory import (
    CutBundle,
    DyeBatch,
    Machine,
    MachineClass,
    MaintenanceTicket,
    ProductionOrder,
    Style,
    WorkCenter,
)
from app.services import clients, planning

STAGE_NAMES = {
    "knitting": "Knitting",
    "dyeing": "Dyeing",
    "finishing": "Finishing",
    "cutting": "Cutting",
    "embellishment": "Printing",
    "sewing": "Sewing",
    "packing": "Packing",
}
MAX_TOKENS = 8


# ---------- Production orders: where every open order is today ----------


@dataclass
class Token:
    order: ProductionOrder
    style: str
    badge: clients.Badge | None
    late: bool


@dataclass
class Station:
    key: str
    name: str
    tokens: list = field(default_factory=list)
    more: int = 0

    @property
    def count(self):
        return len(self.tokens) + self.more


def order_pipeline(company_id, today=None):
    """Open orders placed at the stage their saved plan has them in today."""
    today = today or date.today()
    orders = planning.open_orders(company_id)
    steps = planning.stored_steps(company_id, [o.id for o in orders])
    badges = clients.order_badges(company_id, orders)
    styles = dict(
        db.session.execute(
            select(Style.id, Style.code).where(Style.organization_id == company_id)
        ).all()
    )
    stations = [Station("waiting", "Not started")]
    stations += [Station(key, name) for key, name in STAGE_NAMES.items()]
    stations.append(Station("ready", "Plan finished"))
    by_key = {s.key: s for s in stations}
    for order in orders:
        plan = steps.get(order.id, [])
        key = "waiting"
        if plan:
            current = [stage for stage, first, last, *_ in plan if first <= today <= last]
            if current:
                key = current[-1]
            elif today > plan[-1][2]:
                key = "ready"
            elif today >= plan[0][1]:
                # Between two stages (transit, relaxation): show the next one.
                key = next(stage for stage, first, *_ in plan if first > today)
        late = bool(order.planned_finish_on and order.planned_finish_on > order.ex_factory_on)
        station = by_key[key]
        token = Token(order, styles.get(order.style_id, ""), badges.get(order.id), late)
        if len(station.tokens) < MAX_TOKENS:
            station.tokens.append(token)
        else:
            station.more += 1
    if not any(s.count for s in stations if s.key == "embellishment"):
        stations = [s for s in stations if s.key != "embellishment"]
    return stations


# ---------- Capacity: each department as a tank of booked work ----------


@dataclass
class Tank:
    department: str
    name: str
    unit: str
    capacity: Decimal
    used: Decimal

    @property
    def percent(self):
        return float(self.used / self.capacity * 100) if self.capacity else 0.0

    @property
    def level(self):
        """Fill height on a 0–100 scale (over-capacity tanks show full)."""
        return max(0.0, min(100.0, self.percent))

    @property
    def state(self):
        p = self.percent
        return "over" if p > 100 else "high" if p >= 85 else "mid" if p >= 50 else "low"


def capacity_tanks(company_id, today=None, days=7):
    today = today or date.today()
    _, departments, _ = planning.load_board(company_id, today, days)
    return [
        Tank(
            department,
            STAGE_NAMES.get(department, department.title()),
            planning.DEPARTMENT_UNIT[department],
            sum((c for c, _ in cells), Decimal(0)),
            sum((u for _, u in cells), Decimal(0)),
        )
        for department, cells in departments
    ]


# ---------- Machines: rooms of lights, with breakdowns and due maintenance ----------


@dataclass
class Light:
    machine: Machine
    state: str  # run, idle, down, off
    ticket: MaintenanceTicket | None = None
    due: bool = False


@dataclass
class Room:
    center: WorkCenter
    lights: list

    @property
    def counts(self):
        result = {"run": 0, "idle": 0, "down": 0}
        for light in self.lights:
            if light.state in result:
                result[light.state] += 1
        return result


STATE_OF = {"active": "run", "idle": "idle", "maintenance": "down", "decommissioned": "off"}


def machine_rooms(company_id, with_maintenance=False, today=None):
    centers = db.session.scalars(
        select(WorkCenter)
        .where(WorkCenter.organization_id == company_id, WorkCenter.archived_at.is_(None))
        .order_by(WorkCenter.department, WorkCenter.code)
    ).all()
    machines = db.session.scalars(
        select(Machine)
        .where(Machine.organization_id == company_id, Machine.archived_at.is_(None))
        .order_by(Machine.asset_tag)
    ).all()
    tickets, due = {}, set()
    if with_maintenance:
        from app.services import maintenance

        for ticket in maintenance.unfinished_tickets(company_id):
            tickets.setdefault(ticket.machine_id, ticket)
        today = today or date.today()
        due = {d.machine.id for d in maintenance.schedule(company_id, today) if d.due_on <= today}
    by_center = {}
    for machine in machines:
        by_center.setdefault(machine.work_center_id, []).append(
            Light(
                machine,
                STATE_OF.get(machine.status, "idle"),
                tickets.get(machine.id),
                machine.id in due,
            )
        )
    order = {name: i for i, name in enumerate(STAGE_NAMES)}
    rooms = [Room(c, by_center[c.id]) for c in centers if by_center.get(c.id)]

    def trouble(room):
        # Rooms with a breakdown, a ticket or service due come first, then process order.
        return not any(x.state == "down" or x.ticket or x.due for x in room.lights)

    rooms.sort(key=lambda r: (trouble(r), order.get(r.center.department, 99), r.center.code))
    return rooms


def class_names(company_id):
    return dict(
        db.session.execute(
            select(MachineClass.id, MachineClass.code).where(
                MachineClass.organization_id == company_id
            )
        ).all()
    )


# ---------- Line balancing: each line's stations as a skyline against pitch time ----------


@dataclass
class Skyline:
    line: WorkCenter
    bars: list  # [(station number, height 0-100, state)]
    pitch_level: float  # where pitch time sits on the 0-100 scale
    efficiency: Decimal | None
    style: str


def line_skylines(company_id):
    from app.services import balancing

    current = balancing.current_balances(company_id)
    result = []
    for line in balancing.sewing_lines(company_id):
        balance = current.get(line.id)
        if balance is None:
            result.append(Skyline(line, [], 70.0, None, ""))
            continue
        layout = balancing.layout(company_id, balance)
        metrics = layout.metrics
        bars = []
        top = max((row.load for row in metrics.rows), default=Decimal(0))
        scale = max(top, metrics.pitch * Decimal("1.25")) or Decimal(1)
        for row in metrics.rows:
            bars.append((row.station.number, float(row.load / scale * 100), row.state))
        pitch_level = float(metrics.pitch / scale * 100) if metrics.pitch else 70.0
        result.append(
            Skyline(line, bars, pitch_level, metrics.balance_efficiency, layout.style.code)
        )
    return result


# ---------- Batch cards: bundles in bins and dye vessels with their shade ----------

SHADES = {
    "black": "#1f2328",
    "white": "#f4f4f2",
    "navy": "#1f2f5c",
    "charcoal": "#3b3f45",
    "grey": "#9aa0a6",
    "heather grey": "#b5b8bc",
    "red": "#c0392b",
    "forest": "#2e5e3e",
    "green": "#3c8d4f",
    "volt green": "#b5e61d",
    "oatmeal": "#d9cbb0",
    "bone": "#e6dccb",
    "blue": "#2f6fb5",
    "royal": "#2546a8",
    "pink": "#e58fb3",
    "yellow": "#f2c94c",
    "orange": "#e67e22",
    "brown": "#7a5236",
    "maroon": "#6d1f2a",
    "olive": "#6b7a34",
    "sky": "#7ec8e3",
    "teal": "#1f8a8a",
    "purple": "#6c4ab6",
}


def shade(colour):
    """A drawing colour for a garment colour name (a stable guess for unknown names)."""
    name = (colour or "").strip().lower()
    if name in SHADES:
        return SHADES[name]
    for word, value in SHADES.items():
        if word in name:
            return value
    digest = hashlib.sha256(name.encode()).hexdigest()
    return "#" + digest[:6]


@dataclass
class Bin:
    key: str
    name: str
    bundles: int
    pieces: int
    boxes: list  # [(badge or None, size)] up to 24, newest first


def bundle_bins(company_id):
    names = {"cut": "At cutting", "issued": "On the lines", "sewn": "Sewn"}
    rows = db.session.execute(
        select(CutBundle.status, func.count(CutBundle.id), func.sum(CutBundle.pieces))
        .where(CutBundle.organization_id == company_id, CutBundle.status.in_(names))
        .group_by(CutBundle.status)
    ).all()
    totals = {status: (count, int(pieces or 0)) for status, count, pieces in rows}
    orders = {
        o.id: o
        for o in db.session.scalars(
            select(ProductionOrder).where(ProductionOrder.organization_id == company_id)
        )
    }
    badges = clients.order_badges(company_id, orders.values())
    bins = []
    for status, name in names.items():
        recent = db.session.scalars(
            select(CutBundle)
            .where(CutBundle.organization_id == company_id, CutBundle.status == status)
            .order_by(CutBundle.updated_at.desc())
            .limit(24)
        ).all()
        count, pieces = totals.get(status, (0, 0))
        bins.append(
            Bin(
                status,
                name,
                count,
                pieces,
                [(badges.get(b.production_order_id), b.size) for b in recent],
            )
        )
    return bins


@dataclass
class Vessel:
    machine: Machine
    batch: DyeBatch | None
    shade: str
    order: str


def dye_vessels(company_id, recent_days=3):
    vessels = db.session.scalars(
        select(Machine)
        .join(
            WorkCenter,
            (WorkCenter.id == Machine.work_center_id)
            & (WorkCenter.organization_id == Machine.organization_id),
        )
        .where(
            Machine.organization_id == company_id,
            Machine.archived_at.is_(None),
            WorkCenter.department == "dyeing",
        )
        .order_by(Machine.asset_tag)
    ).all()
    since = date.today() - timedelta(days=recent_days)
    batches = {}
    for batch in db.session.scalars(
        select(DyeBatch)
        .where(
            DyeBatch.organization_id == company_id, DyeBatch.machine_id.in_([v.id for v in vessels])
        )
        .order_by(DyeBatch.created_at.desc())
    ):
        if batch.machine_id in batches:
            continue
        active = batch.status in ("loaded", "dyeing")
        recent = batch.finished_at is not None and batch.finished_at.date() >= since
        if active or recent:
            batches[batch.machine_id] = batch
    orders = dict(
        db.session.execute(
            select(ProductionOrder.id, ProductionOrder.reference).where(
                ProductionOrder.organization_id == company_id
            )
        ).all()
    )
    return [
        Vessel(
            v,
            batches.get(v.id),
            shade(batches[v.id].colour) if v.id in batches else "#cfd8e3",
            orders.get(batches[v.id].production_order_id, "") if v.id in batches else "",
        )
        for v in vessels
    ]
