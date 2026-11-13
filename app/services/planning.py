"""Finite-capacity forward scheduling of production orders (Machine Capacity Management).

How an order becomes a plan (every number is shown to the planner with its working):

1. Stage loads from the style:
     knitting kg   = pieces × fabric kg per piece × 1.10   (greige before process loss)
     dyeing kg     = pieces × fabric kg per piece × 1.05
     finishing m   = Σ pieces × kg per piece × 1000 ÷ (GSM × width)  per fabric
     cutting       = pieces × panels per piece (by product type)
     embellishment = pieces × prints per piece (only when the order has prints)
     sewing        = pieces × garment SAM (standard minutes, from the frozen bulletin)
     packing       = pieces
2. Each stage is booked day by day on real work centres: a day offers the centre's hourly
   rate (step 1) × productive hours that day (shift pattern, holidays), minus what earlier
   orders already booked. Orders are placed by priority, then ex-factory date.
3. Between stages the material may travel between sites (transit matrix, 8 h when no
   route is recorded) and finished fabric must rest flat before cutting (the style's
   relaxation hours). Waits are rounded up to whole days: a stage that needs no wait may
   start on the day the previous one ends, as material flows in batches.
4. Sewing is split evenly across the number of lines the planner chose, picking the
   lines that would finish earliest. Other stages use the single work centre that
   finishes earliest (ties prefer the shorter journey).
5. Released orders keep their bookings and are planned around; draft and planned orders
   are re-planned from scratch, so the result is the same every time for the same data.
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import now
from app.models.factory import (
    CapacityBooking,
    FabricSpec,
    ProductionOrder,
    ShiftPattern,
    SiteTransitTime,
    Style,
    WorkCenter,
)
from app.policies import require
from app.services import capacity, engineering
from app.services.audit import record as audit
from app.services.business import DomainError, company_lock, scoped
from app.services.factory import exceptions_by_site, machines_by_center

STAGES = (
    ("knitting", "knitting", "kg"),
    ("dyeing", "dyeing", "kg"),
    ("finishing", "finishing", "m"),
    ("cutting", "cutting", "panels"),
    ("embellishment", "embellishment", "impressions"),
    ("sewing", "sewing", "SAM min"),
    ("packing", "packing", "pieces"),
)
DEPARTMENT_UNIT = {department: unit for _, department, unit in STAGES}
KNIT_FACTOR = Decimal("1.10")
DYE_FACTOR = Decimal("1.05")
PANELS_PER_PIECE = {
    "tee": 5,
    "tank": 4,
    "long_sleeve": 6,
    "polo": 8,
    "hoodie": 10,
    "sweatshirt": 7,
    "jogger": 8,
    "shorts": 6,
    "leggings": 5,
    "other": 6,
}
DEFAULT_TRANSIT_HOURS = Decimal(8)
HORIZON_DAYS = 240
TINY = Decimal("0.001")
OPEN = ("draft", "planned", "released")


@dataclass
class Load:
    quantity: Decimal
    unit: str
    working: str


def order_loads(order, style, fabrics, garment_sam):
    """{stage: Load} for one order, with the arithmetic written out."""
    pieces = Decimal(order.quantity)
    kg = sum((Decimal(f.consumption_kg) for f in fabrics), Decimal(0))
    loads = {}
    if kg:
        loads["knitting"] = Load(
            pieces * kg * KNIT_FACTOR,
            "kg",
            f"{order.quantity:,} pcs × {capacity.q(kg, '0.001')} kg × {KNIT_FACTOR} process loss",
        )
        loads["dyeing"] = Load(
            pieces * kg * DYE_FACTOR,
            "kg",
            f"{order.quantity:,} pcs × {capacity.q(kg, '0.001')} kg × {DYE_FACTOR} process loss",
        )
        metres = sum(
            (
                pieces * Decimal(f.consumption_kg) * 1000 / (Decimal(f.gsm) * Decimal(f.width_m))
                for f in fabrics
            ),
            Decimal(0),
        )
        loads["finishing"] = Load(
            metres, "m", "Σ pieces × kg per piece × 1000 ÷ (GSM × width) over the fabrics"
        )
    panels = PANELS_PER_PIECE.get(style.product_type, 6)
    loads["cutting"] = Load(
        pieces * panels,
        "panels",
        f"{order.quantity:,} pcs × {panels} panels ({style.product_type})",
    )
    if order.prints_per_piece:
        loads["embellishment"] = Load(
            pieces * order.prints_per_piece,
            "impressions",
            f"{order.quantity:,} pcs × {order.prints_per_piece} prints",
        )
    loads["sewing"] = Load(
        pieces * Decimal(garment_sam),
        "SAM min",
        f"{order.quantity:,} pcs × {capacity.q(garment_sam, '0.01')} SAM",
    )
    loads["packing"] = Load(pieces, "pieces", f"{order.quantity:,} pcs")
    return loads


@dataclass
class Step:
    stage: str
    centers: list
    start: date
    end: date
    quantity: Decimal
    unit: str
    working: str
    transit_hours: Decimal = Decimal(0)
    wait_hours: int = 0


@dataclass
class Plan:
    order_id: object
    steps: list = field(default_factory=list)
    bookings: list = field(default_factory=list)  # (stage, center_id, day, quantity, unit)
    problems: list = field(default_factory=list)
    start: date | None = None
    finish: date | None = None

    def late_days(self, ex_factory_on):
        if self.finish is None:
            return None
        return (self.finish - ex_factory_on).days


class Floor:
    """Daily capacity per work centre and the load already booked against it."""

    def __init__(self, company_id, today):
        self.today = today
        self.company_id = company_id
        self.centers = db.session.scalars(
            select(WorkCenter)
            .where(WorkCenter.organization_id == company_id, WorkCenter.archived_at.is_(None))
            .order_by(WorkCenter.code)
        ).all()
        self.patterns = {
            row.id: row
            for row in db.session.scalars(
                select(ShiftPattern).where(ShiftPattern.organization_id == company_id)
            )
        }
        grouped = machines_by_center(company_id, [c.id for c in self.centers])
        self.rates = {
            center.id: capacity.center_capacity(center, grouped.get(center.id, [])).per_hour
            for center in self.centers
        }
        self.exceptions = exceptions_by_site(
            company_id, today, today + timedelta(days=HORIZON_DAYS)
        )
        self.transit = {
            (row.from_site_id, row.to_site_id): Decimal(row.hours)
            for row in db.session.scalars(
                select(SiteTransitTime).where(SiteTransitTime.organization_id == company_id)
            )
        }
        self.used = {}
        self._capacity = {}

    def capacity(self, center, day, unit):
        key = (center.id, day, unit)
        if key not in self._capacity:
            hours, _ = capacity.shift_hours(
                self.patterns[center.shift_pattern_id],
                day,
                self.exceptions.get(center.site_id, {}),
            )
            self._capacity[key] = self.rates[center.id].get(unit, Decimal(0)) * hours
        return self._capacity[key]

    def candidates(self, department, unit):
        return [
            c
            for c in self.centers
            if c.department == department and self.rates[c.id].get(unit, Decimal(0)) > 0
        ]

    def transit_hours(self, from_site, to_site):
        if from_site is None or from_site == to_site:
            return Decimal(0)
        return self.transit.get((from_site, to_site), DEFAULT_TRANSIT_HOURS)

    def allocate(self, center, start, quantity, unit):
        """Dry run: [(day, quantity)] from `start`, or None if it does not fit the horizon."""
        remaining = Decimal(quantity)
        days = []
        day = start
        last = self.today + timedelta(days=HORIZON_DAYS)
        while remaining > TINY:
            if day > last:
                return None
            free = self.capacity(center, day, unit) - self.used.get((center.id, day), 0)
            if free > TINY:
                take = min(free, remaining)
                days.append((day, take))
                remaining -= take
            day += timedelta(days=1)
        return days

    def commit(self, center, days):
        for day, quantity in days:
            key = (center.id, day)
            self.used[key] = self.used.get(key, Decimal(0)) + quantity


def _offset(hours):
    return timedelta(days=math.ceil(hours / 24)) if hours > 0 else timedelta(0)


def plan_order(floor, order, loads, relaxation_hours):
    plan = Plan(order_id=order.id)
    previous_end = None
    previous_site = None
    for stage, department, unit in STAGES:
        load = loads.get(stage)
        if load is None or load.quantity <= TINY:
            continue
        centers = floor.candidates(department, unit)
        if not centers:
            plan.problems.append(
                f"No {department} capacity is registered, so this stage is skipped."
            )
            continue
        wait = relaxation_hours if stage == "cutting" else 0
        options = []
        lines = min(order.sewing_lines, len(centers)) if stage == "sewing" else 1
        share = load.quantity / lines
        for center in centers:
            transit = floor.transit_hours(previous_site, center.site_id)
            start = floor.today if previous_end is None else previous_end + _offset(transit + wait)
            days = floor.allocate(center, max(start, floor.today), share, unit)
            if days:
                options.append((days[-1][0], transit, center.code, center, days))
        if len(options) < lines:
            plan.problems.append(
                f"Not enough {department} capacity within {HORIZON_DAYS} days to plan this stage."
            )
            plan.finish = None
            return plan
        options.sort(key=lambda option: option[:3])
        chosen = options[:lines]
        for _, _, _, center, days in chosen:
            floor.commit(center, days)
            plan.bookings.extend((stage, center.id, day, quantity, unit) for day, quantity in days)
        start = min(days[0][0] for *_, days in chosen)
        end = max(days[-1][0] for *_, days in chosen)
        plan.steps.append(
            Step(
                stage,
                [option[3] for option in chosen],
                start,
                end,
                load.quantity,
                unit,
                load.working,
                chosen[0][1],
                wait,
            )
        )
        plan.start = plan.start or start
        previous_end, previous_site = end, chosen[0][3].site_id
    plan.finish = previous_end
    return plan


# ---------- Reading orders ----------


def _style_inputs(company_id, orders):
    style_ids = {o.style_id for o in orders}
    styles = (
        {
            s.id: s
            for s in db.session.scalars(
                select(Style).where(Style.organization_id == company_id, Style.id.in_(style_ids))
            )
        }
        if style_ids
        else {}
    )
    fabrics = {}
    if style_ids:
        for row in db.session.scalars(
            select(FabricSpec).where(
                FabricSpec.organization_id == company_id, FabricSpec.style_id.in_(style_ids)
            )
        ):
            fabrics.setdefault(row.style_id, []).append(row)
    sams = engineering.bulletin_sams(company_id, list({o.bulletin_id for o in orders}))
    return styles, fabrics, sams


def loads_for(company_id, order):
    styles, fabrics, sams = _style_inputs(company_id, [order])
    style = styles[order.style_id]
    rows = fabrics.get(order.style_id, [])
    return (
        order_loads(order, style, rows, sams.get(order.bulletin_id, Decimal(0))),
        max((f.relaxation_hours for f in rows), default=0),
        sams.get(order.bulletin_id, Decimal(0)),
    )


def open_orders(company_id):
    return db.session.scalars(
        select(ProductionOrder)
        .where(ProductionOrder.organization_id == company_id, ProductionOrder.status.in_(OPEN))
        .order_by(
            ProductionOrder.priority, ProductionOrder.ex_factory_on, ProductionOrder.created_at
        )
    ).all()


def simulate(company_id, today=None, overrides=None):
    """Plan every open order in memory. `overrides` = {order_id: {field: value}} for what-ifs.

    Returns (plans by order id, the orders as planned, the floor).
    """
    today = today or date.today()
    overrides = overrides or {}
    floor = Floor(company_id, today)
    orders = open_orders(company_id)
    released = [o for o in orders if o.status == "released"]
    if released:
        for booking in db.session.scalars(
            select(CapacityBooking).where(
                CapacityBooking.organization_id == company_id,
                CapacityBooking.production_order_id.in_([o.id for o in released]),
            )
        ):
            key = (booking.work_center_id, booking.day)
            floor.used[key] = floor.used.get(key, Decimal(0)) + booking.quantity
    candidates = []
    for order in orders:
        if order.status == "released":
            continue
        view = SimpleNamespace(
            **{c.name: getattr(order, c.name) for c in ProductionOrder.__table__.columns}
        )
        for name, value in overrides.get(order.id, {}).items():
            setattr(view, name, value)
        candidates.append(view)
    candidates.sort(key=lambda o: (o.priority, o.ex_factory_on, o.created_at))
    styles, fabrics, sams = _style_inputs(company_id, candidates)
    plans = {}
    for order in candidates:
        rows = fabrics.get(order.style_id, [])
        loads = order_loads(
            order, styles[order.style_id], rows, sams.get(order.bulletin_id, Decimal(0))
        )
        relax = max((f.relaxation_hours for f in rows), default=0)
        plans[order.id] = plan_order(floor, order, loads, relax)
    return plans, candidates, floor


def replan(company_id, today=None):
    """Re-plan every draft and planned order and store the bookings. Returns the plans."""
    require(company_id, "factory.manage")
    company_lock(company_id)
    require(company_id, "factory.manage")
    plans, candidates, _ = simulate(company_id, today)
    ids = [o.id for o in candidates]
    if ids:
        db.session.execute(
            delete(CapacityBooking).where(
                CapacityBooking.organization_id == company_id,
                CapacityBooking.production_order_id.in_(ids),
            )
        )
    stamp = now()
    rows = (
        {
            o.id: o
            for o in db.session.scalars(select(ProductionOrder).where(ProductionOrder.id.in_(ids)))
        }
        if ids
        else {}
    )
    merged = {}
    for order_id, plan in plans.items():
        order = rows[order_id]
        complete = plan.finish is not None
        order.status = "planned" if complete else "draft"
        order.planned_start_on = plan.start if complete else None
        order.planned_finish_on = plan.finish
        order.planned_at = stamp if complete else None
        if not complete:
            continue
        for stage, center_id, day, quantity, unit in plan.bookings:
            key = (order_id, stage, center_id, day)
            total = merged.get(key, (Decimal(0), unit))[0]
            merged[key] = (total + quantity, unit)
    for (order_id, stage, center_id, day), (quantity, unit) in merged.items():
        db.session.add(
            CapacityBooking(
                organization_id=company_id,
                production_order_id=order_id,
                stage=stage,
                work_center_id=center_id,
                day=day,
                quantity=quantity.quantize(TINY),
                unit=unit,
            )
        )
    db.session.flush()
    audit(company_id, "factory.replanned", "production_orders", None, {"count": len(plans)})
    return plans


# ---------- Orders ----------


def _clean(company_id, values):
    reference = str(values.get("reference") or "").strip()
    colour = str(values.get("colour") or "").strip()
    if not reference or len(reference) > 40 or "\x00" in reference:
        raise DomainError("Give the order a reference (up to 40 characters).")
    if not colour or len(colour) > 60 or "\x00" in colour:
        raise DomainError("Give the colour (up to 60 characters).")
    try:
        quantity = int(values.get("quantity"))
        priority = int(values.get("priority") or 3)
        lines = int(values.get("sewing_lines") or 2)
        prints = int(values.get("prints_per_piece") or 0)
    except (TypeError, ValueError) as exc:
        raise DomainError("Quantity, priority, lines and prints must be whole numbers.") from exc
    if not 1 <= quantity <= 10_000_000:
        raise DomainError("Quantity must be between 1 and 10,000,000 pieces.")
    if not 1 <= priority <= 5 or not 1 <= lines <= 20 or not 0 <= prints <= 10:
        raise DomainError("Priority is 1–5, sewing lines 1–20 and prints 0–10.")
    ex_factory = values.get("ex_factory_on")
    if isinstance(ex_factory, str):
        try:
            ex_factory = date.fromisoformat(ex_factory)
        except ValueError as exc:
            raise DomainError("Enter the ex-factory date as YYYY-MM-DD.") from exc
    if not isinstance(ex_factory, date):
        raise DomainError("Enter the ex-factory date.")
    style = scoped(Style, company_id, values.get("style_id"))
    if style.archived_at:
        raise DomainError("Choose an active style.")
    bulletin = engineering.current_bulletins(company_id, [style.id]).get(style.id)
    if bulletin is None:
        raise DomainError("Publish an operation bulletin for this style before ordering it.")
    if not db.session.scalar(
        select(FabricSpec.id).where(
            FabricSpec.organization_id == company_id, FabricSpec.style_id == style.id
        )
    ):
        raise DomainError("Record the style's fabric before ordering it.")
    return {
        "reference": reference,
        "colour": colour,
        "quantity": quantity,
        "priority": priority,
        "sewing_lines": lines,
        "prints_per_piece": prints,
        "ex_factory_on": ex_factory,
        "style_id": style.id,
        "bulletin_id": bulletin.id,
    }


def save_order(company_id, values, order_id=None, version=None, today=None):
    """Create or change an order, then re-plan everything so priorities stay consistent."""
    require(company_id, "factory.manage")
    try:
        company_lock(company_id)
        require(company_id, "factory.manage")
        if order_id:
            order = scoped(ProductionOrder, company_id, order_id, lock=True)
            if version is not None and order.version != version:
                raise DomainError("This order changed; reload before saving.")
            if order.status not in ("draft", "planned"):
                raise DomainError("Released, completed and cancelled orders cannot be edited.")
        else:
            order = ProductionOrder(organization_id=company_id, status="draft")
        for name, value in _clean(company_id, values).items():
            setattr(order, name, value)
        db.session.add(order)
        db.session.flush()
        audit(
            company_id,
            "factory.order_saved",
            "production_orders",
            order.id,
            {"version": order.version},
        )
        replan(company_id, today)
        db.session.commit()
        return order
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError(
            "That reference is already used, or the order changed meanwhile."
        ) from exc
    except Exception:
        db.session.rollback()
        raise


TRANSITIONS = {
    "release": ("planned", "released"),
    "complete": ("released", "completed"),
    "cancel": (("draft", "planned", "released"), "cancelled"),
}


def transition(company_id, order_id, action, version, today=None):
    """release: freeze the plan · complete: finish · cancel: free the capacity."""
    require(company_id, "factory.manage")
    if action not in TRANSITIONS:
        raise DomainError("Unknown order action.")
    allowed, target = TRANSITIONS[action]
    allowed = (allowed,) if isinstance(allowed, str) else allowed
    try:
        company_lock(company_id)
        require(company_id, "factory.manage")
        order = scoped(ProductionOrder, company_id, order_id, lock=True)
        if order.version != version:
            raise DomainError("This order changed; reload and try again.")
        if order.status not in allowed:
            raise DomainError(f"A {order.status} order cannot be {target}.")
        if action == "release" and order.planned_finish_on is None:
            raise DomainError("Only an order with a complete plan can be released.")
        order.status = target
        if action == "cancel":
            db.session.execute(
                delete(CapacityBooking).where(
                    CapacityBooking.organization_id == company_id,
                    CapacityBooking.production_order_id == order.id,
                )
            )
        db.session.flush()
        audit(
            company_id, f"factory.order_{target}", "production_orders", order.id, {"status": target}
        )
        if action in ("cancel", "complete"):
            replan(company_id, today)
        db.session.commit()
        return order
    except Exception:
        db.session.rollback()
        raise


# ---------- Reading plans for screens ----------


def stored_steps(company_id, order_ids):
    """{order_id: [(stage, start, end, quantity, unit, [center ids])]} from saved bookings."""
    if not order_ids:
        return {}
    rows = db.session.scalars(
        select(CapacityBooking)
        .where(
            CapacityBooking.organization_id == company_id,
            CapacityBooking.production_order_id.in_(order_ids),
        )
        .order_by(CapacityBooking.day)
    ).all()
    found = {}
    for row in rows:
        stages = found.setdefault(row.production_order_id, {})
        entry = stages.setdefault(row.stage, [row.day, row.day, Decimal(0), row.unit, []])
        entry[0] = min(entry[0], row.day)
        entry[1] = max(entry[1], row.day)
        entry[2] += row.quantity
        if row.work_center_id not in entry[4]:
            entry[4].append(row.work_center_id)
    order = [stage for stage, _, _ in STAGES]
    return {
        order_id: [(stage, *stages[stage]) for stage in order if stage in stages]
        for order_id, stages in found.items()
    }


def load_board(company_id, start, days):
    """Department and work-centre utilisation per day: (cap, used) in each department's unit."""
    floor = Floor(company_id, start)
    end = start + timedelta(days=days - 1)
    booked = {}
    for row in db.session.scalars(
        select(CapacityBooking).where(
            CapacityBooking.organization_id == company_id,
            CapacityBooking.day >= start,
            CapacityBooking.day <= end,
        )
    ):
        key = (row.work_center_id, row.day)
        booked[key] = booked.get(key, Decimal(0)) + row.quantity
    span = [start + timedelta(days=offset) for offset in range(days)]
    departments, centers = {}, {}
    for center in floor.centers:
        unit = DEPARTMENT_UNIT.get(center.department)
        if unit is None or floor.rates[center.id].get(unit, 0) <= 0:
            continue
        cells = []
        for day in span:
            cap = floor.capacity(center, day, unit)
            used = booked.get((center.id, day), Decimal(0))
            cells.append((cap, used))
            dept = departments.setdefault(
                center.department, [[Decimal(0), Decimal(0)] for _ in span]
            )
            dept[len(cells) - 1][0] += cap
            dept[len(cells) - 1][1] += used
        centers[center.id] = (center, cells)
    order = [d for _, d, _ in STAGES]
    return span, [(d, departments[d]) for d in order if d in departments], centers
