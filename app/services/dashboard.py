"""Management dashboard figures for the factory, all derived from recorded data.

utilisation     booked ÷ capacity for the next 14 days, per site and department
efficiency      earned ÷ (clock − approved off-standard), per site and day, last 7 days
OEE (sewing)    availability × performance × quality, per site, last 7 days
                availability = (clock − all stop operator-minutes) ÷ clock
                performance  = earned ÷ (clock − all stop operator-minutes)
                quality      = good ÷ (good + rejects)
downtime        minutes and operator-minutes per reason, last 7 days
on time         open orders whose planned finish is on or before ex-factory
"""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.extensions import db
from app.models.factory import DowntimeEvent, DowntimeReason, ProductionOrder
from app.models.master import Site
from app.services import balancing, planning, shopfloor

ZERO = Decimal(0)


@dataclass
class Totals:
    good: int = 0
    rejects: int = 0
    earned: Decimal = ZERO
    clock: Decimal = ZERO
    off_standard: Decimal = ZERO
    stopped: Decimal = ZERO

    def add(self, day):
        self.good += day.good
        self.rejects += day.rejects
        self.earned += day.earned
        self.clock += day.clock
        self.off_standard += day.off_standard
        self.stopped += day.off_standard + day.lost

    @property
    def efficiency(self):
        available = self.clock - self.off_standard
        return self.earned / available * 100 if available > 0 else None

    @property
    def availability(self):
        return (self.clock - min(self.stopped, self.clock)) / self.clock if self.clock else None

    @property
    def performance(self):
        running = self.clock - min(self.stopped, self.clock)
        return self.earned / running if running else None

    @property
    def quality(self):
        made = self.good + self.rejects
        return Decimal(self.good) / made if made else None

    @property
    def oee(self):
        parts = (self.availability, self.performance, self.quality)
        if any(part is None for part in parts):
            return None
        return parts[0] * parts[1] * parts[2] * 100


@dataclass
class Board:
    sites: list = field(default_factory=list)
    departments: list = field(default_factory=list)
    utilisation: dict = field(default_factory=dict)  # (site id, department) -> percent
    days: list = field(default_factory=list)
    trend: dict = field(default_factory=dict)  # site id -> [Totals per day]
    week: dict = field(default_factory=dict)  # site id -> Totals
    floor_total: Totals = field(default_factory=Totals)
    downtime: list = field(default_factory=list)  # [(reason, minutes, operator minutes)]
    orders_open: int = 0
    orders_on_time: int = 0
    at_risk: list = field(default_factory=list)  # [(order, spare days)]


def build(company_id, today, latest_day):
    board = Board()
    sites = {
        s.id: s
        for s in db.session.scalars(
            select(Site).where(Site.organization_id == company_id).order_by(Site.code)
        )
    }

    # Utilisation for the next 14 days.
    _, _, centers = planning.load_board(company_id, today, 14)
    sums = {}
    for center, cells in centers.values():
        key = (center.site_id, center.department)
        cap, used = sums.get(key, (ZERO, ZERO))
        sums[key] = (cap + sum(c for c, _ in cells), used + sum(u for _, u in cells))
    order = [stage for _, stage, _ in planning.STAGES]
    board.departments = [d for d in order if any(key[1] == d for key in sums)]
    board.utilisation = {key: used / cap * 100 for key, (cap, used) in sums.items() if cap > 0}

    # Floor efficiency for the 7 days ending on the latest day with entries.
    lines = balancing.sewing_lines(company_id)
    line_site = {line.id: line.site_id for line in lines}
    board.days = [latest_day - timedelta(days=offset) for offset in range(6, -1, -1)]
    for index, day in enumerate(board.days):
        for line_id, figures in shopfloor.floor(company_id, day, list(line_site)).items():
            site_id = line_site[line_id]
            trend = board.trend.setdefault(site_id, [Totals() for _ in board.days])
            trend[index].add(figures)
            board.week.setdefault(site_id, Totals()).add(figures)
            board.floor_total.add(figures)
    used_sites = {site_id for site_id, _ in sums} | set(board.trend)
    board.sites = [site for site_id, site in sites.items() if site_id in used_sites]

    # Top downtime reasons over the same week.
    events = shopfloor.effective(
        db.session.scalars(
            select(DowntimeEvent).where(
                DowntimeEvent.organization_id == company_id,
                DowntimeEvent.day >= board.days[0],
                DowntimeEvent.day <= board.days[-1],
            )
        ).all()
    )
    reasons = {
        r.id: r
        for r in db.session.scalars(
            select(DowntimeReason).where(DowntimeReason.organization_id == company_id)
        )
    }
    pareto = {}
    for event in events.values():
        if not event.minutes:
            continue
        minutes, people = pareto.get(event.reason_id, (0, 0))
        pareto[event.reason_id] = (
            minutes + event.minutes,
            people + event.minutes * event.operators_affected,
        )
    board.downtime = sorted(
        ((reasons.get(rid), m, p) for rid, (m, p) in pareto.items()),
        key=lambda row: row[2],
        reverse=True,
    )[:6]

    # On-time forecast for open orders.
    open_orders = db.session.scalars(
        select(ProductionOrder).where(
            ProductionOrder.organization_id == company_id,
            ProductionOrder.status.in_(("planned", "released")),
            ProductionOrder.planned_finish_on.is_not(None),
        )
    ).all()
    board.orders_open = len(open_orders)
    for o in open_orders:
        spare = (o.ex_factory_on - o.planned_finish_on).days
        if spare >= 0:
            board.orders_on_time += 1
        if spare <= 2:
            board.at_risk.append((o, spare))
    board.at_risk.sort(key=lambda pair: pair[1])
    return board
