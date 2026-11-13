"""Line balancing: share a style's sewing operations between the stations of one line.

Vocabulary (blueprint section 5.5):

    station load        = Σ share × operation SAM, for the work given to that station
    pitch time          = garment SAM ÷ stations (the load each station would carry if perfect)
    bottleneck          = the station with the highest load; it sets the pace of the line
    balance efficiency  = garment SAM ÷ (stations × bottleneck load) × 100
    output per hour     = 60 × efficiency ÷ bottleneck load
    output per day      = productive minutes × efficiency ÷ bottleneck load

A perfectly balanced line would make `stations × minutes × efficiency ÷ garment SAM`
pieces a day; the difference is output lost to imbalance.

One station is one operator with at most one kind of machine: it may combine operations
of the same machine class, plus manual work (trimming, folding) which needs no machine.
The calculations here are pure functions over plain rows so they are easy to test; the
database writes are at the end of the module.
"""

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import now
from app.models.factory import (
    LineBalance,
    LineStation,
    Machine,
    OperationBulletin,
    ShiftPattern,
    StationOperation,
    Style,
    WorkCenter,
)
from app.policies import require
from app.services import engineering
from app.services.audit import record as audit
from app.services.business import DomainError, company_lock, scoped
from app.services.capacity import AVAILABLE_STATUSES

SHARE = Decimal("0.0001")
ONE = Decimal(1)
MAX_STATIONS = 200
# A station more than this far above pitch time is overloaded; further below is idle.
OVER, UNDER = Decimal("1.10"), Decimal("0.80")


@dataclass(frozen=True)
class Op:
    id: uuid.UUID
    sequence: int
    name: str
    class_id: uuid.UUID | None
    class_name: str
    sam: Decimal


@dataclass
class Station:
    number: int
    work: list = field(default_factory=list)  # [(Op, share)]
    machine: object = None  # Machine or None
    id: uuid.UUID | None = None
    assignment_ids: dict = field(default_factory=dict)  # op id -> StationOperation

    @property
    def load(self):
        return sum((op.sam * share for op, share in self.work), Decimal(0))

    @property
    def classes(self):
        return {op.class_id for op, _ in self.work if op.class_id is not None}

    @property
    def class_id(self):
        classes = self.classes
        return next(iter(classes)) if len(classes) == 1 else None

    @property
    def class_name(self):
        names = {op.class_name for op, _ in self.work if op.class_id is not None}
        return " + ".join(sorted(names)) if names else "Manual work"


def compatible(station_class, op_class):
    return station_class is None or op_class is None or station_class == op_class


def split_shares(count):
    """`count` shares of 4-decimal precision that add up to exactly 1."""
    part = (ONE / count).quantize(SHARE, rounding=ROUND_HALF_UP)
    return [part] * (count - 1) + [ONE - part * (count - 1)]


# ---------- Automatic layout ----------

# Within this fraction of the target load a station takes a whole operation rather than
# leaving a sliver of it for the next operator.
SNAP = Decimal("0.05")


def operators_by_class(ops, operators):
    """Share operators between machine types so the busiest type is as light as possible.

    Every type with work gets one operator, then each further operator goes to the type
    whose operators currently carry the most minutes. Manual work counts as its own type.
    """
    work = {}
    for op in ops:
        work[op.class_id] = work.get(op.class_id, Decimal(0)) + op.sam
    if operators < len(work):
        raise ValueError(f"At least {len(work)} operators are needed, one per machine type.")
    counts = dict.fromkeys(work, 1)
    for _ in range(operators - len(work)):
        busiest = max(work, key=lambda key: (work[key] / counts[key], str(key)))
        counts[busiest] += 1
    return counts


def _fill(ops, count):
    """Divide one machine type's operations evenly over `count` stations, in sequence order.

    An operation is split between neighbouring stations only where a station boundary falls
    inside it, so there are at most `count - 1` splits per machine type.
    """
    total = sum(op.sam for op in ops)
    target = total / count
    stations = [Station(0) for _ in range(count)]
    index, room = 0, target
    for op in ops:
        left, parts = op.sam, []
        while left > 0:
            if index == count - 1 or left <= room + target * SNAP:
                take = left  # the whole remainder fits (or this is the last station)
            elif room < target * SNAP:
                index, room = index + 1, target  # station full: start the next one
                continue
            else:
                take = room  # a station boundary falls inside this operation: split it
            parts.append((index, take))
            room -= take
            left -= take
            if left > 0:
                index, room = index + 1, target
        shares = [(part / op.sam).quantize(SHARE, rounding=ROUND_HALF_UP) for _, part in parts]
        shares[-1] = ONE - sum(shares[:-1])
        for (station_index, _), share in zip(parts, shares, strict=True):
            if share > 0:
                stations[station_index].work.append((op, share))
        if room < target * SNAP and index < count - 1:
            index, room = index + 1, target
    return [station for station in stations if station.work]


def auto_layout(ops, operators):
    """Lay out a bulletin for `operators` stations.

    1. Share operators between machine types in proportion to their work (operators_by_class).
    2. Within each type, divide the work evenly in sequence order (_fill).
    3. Number the stations in the order the garment flows: by their first operation.
    """
    if not ops or operators < 1:
        return []
    counts = operators_by_class(ops, operators)
    stations = []
    for class_id, count in counts.items():
        group = [op for op in ops if op.class_id == class_id]
        stations.extend(_fill(group, min(count, MAX_STATIONS)))
    stations.sort(key=lambda station: min(op.sequence for op, _ in station.work))
    for number, station in enumerate(stations, 1):
        station.number = number
    return stations


def assign_machines(stations, machines):
    """Give each machine station a free machine of its class on the line, keeping current ones.

    `machines` is [(Machine, MachineClass)] for the line. Returns {class name: shortfall}.
    """
    usable = [m for m, _ in machines if m.status in AVAILABLE_STATUSES]
    taken = set()
    for station in stations:
        machine = station.machine
        if (
            machine is not None
            and station.class_id == machine.machine_class_id
            and machine.status in AVAILABLE_STATUSES
            and machine.id not in taken
        ):
            taken.add(machine.id)
        else:
            station.machine = None
    short = {}
    for station in stations:
        if station.machine is not None or station.class_id is None:
            continue
        free = next(
            (m for m in usable if m.machine_class_id == station.class_id and m.id not in taken),
            None,
        )
        if free is None:
            short[station.class_name] = short.get(station.class_name, 0) + 1
        else:
            station.machine = free
            taken.add(free.id)
    return short


# ---------- Measuring a layout ----------


@dataclass
class Row:
    station: Station
    load: Decimal
    percent: Decimal  # of pitch time
    state: str  # bottleneck, over, ok, under
    bar: int  # 0-20, width step for the load bar (pitch time sits at 14)


@dataclass
class Metrics:
    total_sam: Decimal
    stations: int
    pitch: Decimal
    bottleneck: Decimal
    bottleneck_numbers: list
    balance_efficiency: Decimal
    per_hour: Decimal
    per_day: Decimal
    balanced_per_day: Decimal
    rows: list
    unassigned: list  # [(Op, missing share)]
    mixed: list  # station numbers combining two machine classes
    by_class: list  # [(class name, stations needed, machines available)]

    @property
    def lost_per_day(self):
        return max(self.balanced_per_day - self.per_day, Decimal(0))

    @property
    def complete(self):
        return not self.unassigned and not self.mixed


def bar_step(load, pitch):
    """Width step for a load bar: the track shows 0 to 1.43 × pitch in 20 steps of 5%."""
    if not pitch:
        return 0
    return max(0, min(20, round(float(load / pitch) * 14)))


def measure(ops, stations, minutes_per_day, efficiency, machines=()):
    total = sum((op.sam for op in ops), Decimal(0))
    working = [s for s in stations if s.work]
    count = len(working)
    eta = Decimal(efficiency) / 100
    loads = [s.load for s in working]
    bottleneck = max(loads) if loads else Decimal(0)
    pitch = total / count if count else Decimal(0)
    assigned = {}
    for station in working:
        for op, share in station.work:
            assigned[op.id] = assigned.get(op.id, Decimal(0)) + share
    unassigned = [(op, ONE - assigned.get(op.id, 0)) for op in ops if assigned.get(op.id, 0) < 1]
    rows = []
    for station in stations:
        load = station.load
        percent = load / pitch * 100 if pitch else Decimal(0)
        if station.work and load == bottleneck:
            state = "bottleneck"
        elif pitch and load > pitch * OVER:
            state = "over"
        elif pitch and load < pitch * UNDER:
            state = "under"
        else:
            state = "ok"
        rows.append(Row(station, load, percent, state, bar_step(load, pitch)))
    needed = {}
    for station in working:
        if station.class_id is not None:
            needed[station.class_name] = needed.get(station.class_name, 0) + 1
    available = {}
    for machine, machine_class in machines:
        if machine.status in AVAILABLE_STATUSES:
            available[machine_class.name] = available.get(machine_class.name, 0) + 1
    names = sorted(set(needed) | set(available))
    return Metrics(
        total_sam=total,
        stations=count,
        pitch=pitch,
        bottleneck=bottleneck,
        bottleneck_numbers=[s.number for s in working if s.load == bottleneck],
        balance_efficiency=(total / (count * bottleneck) * 100) if bottleneck else Decimal(0),
        per_hour=(60 * eta / bottleneck) if bottleneck else Decimal(0),
        per_day=(Decimal(minutes_per_day) * eta / bottleneck) if bottleneck else Decimal(0),
        balanced_per_day=(count * Decimal(minutes_per_day) * eta / total) if total else Decimal(0),
        rows=rows,
        unassigned=unassigned,
        mixed=[s.number for s in working if len(s.classes) > 1],
        by_class=[(name, needed.get(name, 0), available.get(name, 0)) for name in names],
    )


# ---------- Suggestions ----------


@dataclass
class Suggestion:
    kind: str  # "move" or "add"
    from_number: int
    op: Op
    to_number: int | None  # None means a new station
    percent: int  # of the assignment's share that moves
    bottleneck_after: Decimal
    gain_per_day: Decimal


def _after(stations, changes):
    """Highest load after applying {station number: delta} (a None key is a new station)."""
    loads = [s.load + changes.get(s.number, 0) for s in stations if s.work]
    if None in changes:
        loads.append(changes[None])
    return max(loads)


def suggest(stations, minutes_per_day, efficiency):
    """The best single move off the bottleneck, and the effect of one extra operator."""
    working = [s for s in stations if s.work]
    if len(working) < 1:
        return []
    bottleneck = max(working, key=lambda s: s.load)
    peak = bottleneck.load
    eta = Decimal(efficiency) / 100
    minutes = Decimal(minutes_per_day)

    def per_day(load):
        return minutes * eta / load if load else Decimal(0)

    result = []
    best = None
    for op, share in bottleneck.work:
        amount = op.sam * share
        for other in working:
            if other is bottleneck or not compatible(other.class_id, op.class_id):
                continue
            if len(other.classes | ({op.class_id} if op.class_id else set())) > 1:
                continue
            ideal = min(amount, (peak - other.load) / 2)
            if ideal <= 0:
                continue
            percent = max(1, min(100, round(float(ideal / amount) * 100)))
            moved = amount * percent / 100
            after = _after(working, {bottleneck.number: -moved, other.number: moved})
            # Prefer the lowest bottleneck, then moving a whole operation, then a neighbour.
            key = (after, percent != 100, abs(other.number - bottleneck.number))
            if after < peak * Decimal("0.99") and (best is None or key < best[0]):
                best = (
                    key,
                    Suggestion(
                        "move",
                        bottleneck.number,
                        op,
                        other.number,
                        percent,
                        after,
                        per_day(after) - per_day(peak),
                    ),
                )
    if best:
        result.append(best[1])
    largest_op, largest_share = max(bottleneck.work, key=lambda pair: pair[0].sam * pair[1])
    half = largest_op.sam * largest_share / 2
    after = _after(working, {bottleneck.number: -half, None: half})
    if after < peak and len(stations) < MAX_STATIONS:
        result.append(
            Suggestion(
                "add",
                bottleneck.number,
                largest_op,
                None,
                50,
                after,
                per_day(after) - per_day(peak),
            )
        )
    return result


# ---------- Reading from the database ----------


def productive_minutes(pattern):
    """Productive minutes on a normal working day of a shift pattern."""
    per_shift = Decimal(pattern.hours_per_shift) * 60 - pattern.break_minutes_per_shift
    return max(per_shift, Decimal(0)) * pattern.shifts_per_day


def sewing_lines(company_id):
    return db.session.scalars(
        select(WorkCenter)
        .where(
            WorkCenter.organization_id == company_id,
            WorkCenter.department == "sewing",
            WorkCenter.archived_at.is_(None),
        )
        .order_by(WorkCenter.code)
    ).all()


def current_balances(company_id):
    """{work centre id: latest published balance}: what each line is running now."""
    latest = (
        select(LineBalance.work_center_id, func.max(LineBalance.revision).label("revision"))
        .where(LineBalance.organization_id == company_id, LineBalance.status == "published")
        .group_by(LineBalance.work_center_id)
        .subquery()
    )
    rows = db.session.scalars(
        select(LineBalance)
        .join(
            latest,
            (latest.c.work_center_id == LineBalance.work_center_id)
            & (latest.c.revision == LineBalance.revision),
        )
        .where(LineBalance.organization_id == company_id)
    ).all()
    return {row.work_center_id: row for row in rows}


def bulletin_ops(company_id, bulletin_id):
    return [
        Op(
            operation.id,
            operation.sequence,
            operation.name,
            operation.machine_class_id,
            machine_class.name if machine_class else "Manual work",
            operation.sam,
        )
        for operation, machine_class in engineering.operations(company_id, bulletin_id)
    ]


def stations_for(company_id, balance_id, ops):
    by_id = {op.id: op for op in ops}
    rows = db.session.scalars(
        select(LineStation)
        .where(LineStation.organization_id == company_id, LineStation.balance_id == balance_id)
        .order_by(LineStation.number)
    ).all()
    machines = {}
    machine_ids = [row.machine_id for row in rows if row.machine_id]
    if machine_ids:
        machines = {
            m.id: m
            for m in db.session.scalars(
                select(Machine).where(
                    Machine.organization_id == company_id, Machine.id.in_(machine_ids)
                )
            )
        }
    stations = {
        row.id: Station(row.number, machine=machines.get(row.machine_id), id=row.id) for row in rows
    }
    assignments = db.session.scalars(
        select(StationOperation).where(
            StationOperation.organization_id == company_id,
            StationOperation.balance_id == balance_id,
        )
    ).all()
    for assignment in assignments:
        station = stations[assignment.station_id]
        op = by_id[assignment.bulletin_operation_id]
        station.work.append((op, assignment.share))
        station.assignment_ids[op.id] = assignment
    for station in stations.values():
        station.work.sort(key=lambda pair: pair[0].sequence)
    return list(stations.values())


@dataclass
class Layout:
    balance: LineBalance
    line: WorkCenter
    style: Style
    bulletin: OperationBulletin
    ops: list
    stations: list
    machines: list
    minutes: Decimal
    metrics: Metrics
    suggestions: list


def layout(company_id, balance):
    from app.services.factory import machines_by_center

    line = scoped(WorkCenter, company_id, balance.work_center_id)
    bulletin = scoped(OperationBulletin, company_id, balance.bulletin_id)
    style = scoped(Style, company_id, bulletin.style_id)
    pattern = scoped(ShiftPattern, company_id, line.shift_pattern_id)
    ops = bulletin_ops(company_id, bulletin.id)
    stations = stations_for(company_id, balance.id, ops)
    machines = machines_by_center(company_id, [line.id]).get(line.id, [])
    minutes = productive_minutes(pattern)
    metrics = measure(ops, stations, minutes, balance.target_efficiency, machines)
    suggestions = suggest(stations, minutes, balance.target_efficiency) if metrics.complete else []
    return Layout(
        balance, line, style, bulletin, ops, stations, machines, minutes, metrics, suggestions
    )


# ---------- Writing ----------


def _transaction(action):
    try:
        result = action()
        db.session.commit()
        return result
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError("Someone else changed this balance; reload and try again.") from exc
    except Exception:
        db.session.rollback()
        raise


def _locked(company_id, balance_id, version=None, draft=True):
    company_lock(company_id)
    require(company_id, "factory.manage")
    balance = scoped(LineBalance, company_id, balance_id, lock=True)
    if version is not None and balance.version != version:
        raise DomainError("This balance changed; reload before saving.")
    if draft and balance.status != "draft":
        raise DomainError("Published balances are frozen. Start a new revision to change them.")
    return balance


def _sewing_line(company_id, work_center_id):
    line = scoped(WorkCenter, company_id, work_center_id)
    if line.department != "sewing" or line.archived_at:
        raise DomainError("Choose an active sewing line.")
    return line


def _operators(value):
    try:
        operators = int(value)
    except (TypeError, ValueError) as exc:
        raise DomainError("Operators must be a whole number.") from exc
    if not 1 <= operators <= MAX_STATIONS:
        raise DomainError(f"Operators must be between 1 and {MAX_STATIONS}.")
    return operators


def _efficiency(value):
    try:
        efficiency = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise DomainError("Efficiency must be a number.") from exc
    if not (efficiency.is_finite() and 0 < efficiency <= 100):
        raise DomainError("Efficiency must be above 0 and at most 100%.")
    return efficiency


def _auto(ops, operators):
    try:
        return auto_layout(ops, operators)
    except ValueError as exc:
        raise DomainError(str(exc)) from exc


def _write(company_id, balance, stations, machines):
    """Replace a draft's stations and assignments with `stations` (after machine choice)."""
    for row in db.session.scalars(
        select(StationOperation).where(
            StationOperation.organization_id == company_id,
            StationOperation.balance_id == balance.id,
        )
    ):
        db.session.delete(row)
    db.session.flush()
    for row in db.session.scalars(
        select(LineStation).where(
            LineStation.organization_id == company_id, LineStation.balance_id == balance.id
        )
    ):
        db.session.delete(row)
    db.session.flush()
    stations = [s for s in stations if s.work]
    if len(stations) > MAX_STATIONS:
        raise DomainError(f"A line can have at most {MAX_STATIONS} stations.")
    short = assign_machines(stations, machines)
    for number, station in enumerate(stations, 1):
        row = LineStation(
            organization_id=company_id,
            balance_id=balance.id,
            number=number,
            machine_id=station.machine.id if station.machine else None,
        )
        db.session.add(row)
        db.session.flush()
        merged = {}
        for op, share in station.work:
            merged[op.id] = merged.get(op.id, Decimal(0)) + share
        for op_id, share in merged.items():
            db.session.add(
                StationOperation(
                    organization_id=company_id,
                    balance_id=balance.id,
                    station_id=row.id,
                    bulletin_operation_id=op_id,
                    share=min(share, ONE),
                )
            )
    balance.updated_at = now()
    db.session.flush()
    return short


def _line_machines(company_id, line):
    from app.services.factory import machines_by_center

    return machines_by_center(company_id, [line.id]).get(line.id, [])


def create_balance(company_id, work_center_id, bulletin_id, operators, efficiency, note=None):
    """Open a draft balance for a style on a line, laid out automatically."""
    require(company_id, "factory.manage")
    operators = _operators(operators)
    efficiency = _efficiency(efficiency)
    note = (str(note).strip() or None) if note else None
    if note and (len(note) > 200 or "\x00" in note):
        raise DomainError("Keep the note under 200 characters.")

    def action():
        company_lock(company_id)
        require(company_id, "factory.manage")
        line = _sewing_line(company_id, work_center_id)
        bulletin = scoped(OperationBulletin, company_id, bulletin_id)
        if bulletin.status != "published":
            raise DomainError("Balance a published bulletin; drafts can still change.")
        if db.session.scalar(
            select(LineBalance.id).where(
                LineBalance.organization_id == company_id,
                LineBalance.work_center_id == line.id,
                LineBalance.status == "draft",
            )
        ):
            raise DomainError("This line already has a draft balance; finish or discard it first.")
        ops = bulletin_ops(company_id, bulletin.id)
        if not ops:
            raise DomainError("That bulletin has no operations.")
        latest = db.session.scalar(
            select(func.max(LineBalance.revision)).where(
                LineBalance.organization_id == company_id, LineBalance.work_center_id == line.id
            )
        )
        balance = LineBalance(
            organization_id=company_id,
            work_center_id=line.id,
            bulletin_id=bulletin.id,
            revision=(latest or 0) + 1,
            target_efficiency=efficiency,
            note=note,
        )
        db.session.add(balance)
        db.session.flush()
        short = _write(company_id, balance, _auto(ops, operators), _line_machines(company_id, line))
        audit(
            company_id,
            "factory.balance_created",
            "line_balances",
            balance.id,
            {"version": balance.version, "count": operators},
        )
        return balance, short

    return _transaction(action)


def rebalance(company_id, balance_id, operators, version):
    """Throw away the draft's layout and lay it out again for `operators`."""
    require(company_id, "factory.manage")
    operators = _operators(operators)

    def action():
        balance = _locked(company_id, balance_id, version)
        line = scoped(WorkCenter, company_id, balance.work_center_id)
        ops = bulletin_ops(company_id, balance.bulletin_id)
        short = _write(company_id, balance, _auto(ops, operators), _line_machines(company_id, line))
        audit(
            company_id,
            "factory.balance_rebalanced",
            "line_balances",
            balance.id,
            {"version": balance.version, "count": operators},
        )
        return short

    return _transaction(action)


def move(company_id, balance_id, from_number, op_id, to_number, percent, version):
    """Move `percent` of one station's share of an operation to another or a new station."""
    require(company_id, "factory.manage")
    try:
        from_number = int(from_number)
        percent = int(percent)
        to_number = None if to_number in (None, "", "new") else int(to_number)
        op_id = uuid.UUID(str(op_id))
    except (TypeError, ValueError) as exc:
        raise DomainError("Choose a station, an operation and a percentage.") from exc
    if not 1 <= percent <= 100:
        raise DomainError("Move between 1% and 100% of the work.")

    def action():
        balance = _locked(company_id, balance_id, version)
        line = scoped(WorkCenter, company_id, balance.work_center_id)
        ops = bulletin_ops(company_id, balance.bulletin_id)
        stations = stations_for(company_id, balance.id, ops)
        numbers = {s.number: s for s in stations}
        source = numbers.get(from_number)
        if source is None or to_number == from_number:
            raise DomainError("Choose two different stations.")
        found = next(((op, share) for op, share in source.work if op.id == op_id), None)
        if found is None:
            raise DomainError("That operation is not done at that station.")
        op, share = found
        if to_number is None:
            # A new station sits right after the one it relieves.
            target = Station(max(numbers) + 1)
            stations.insert(stations.index(source) + 1, target)
        else:
            target = numbers.get(to_number)
            if target is None:
                raise DomainError("That station does not exist.")
        if not compatible(target.class_id, op.class_id) or len(target.classes) > 1:
            raise DomainError(
                f"Station {target.number} uses {target.class_name}; {op.name} needs "
                f"{op.class_name}. One operator works one kind of machine."
            )
        moved = (share * percent / 100).quantize(SHARE, rounding=ROUND_HALF_UP)
        if moved <= 0:
            raise DomainError("That is too small a part to move.")
        source.work = [(o, s - moved if o.id == op.id else s) for o, s in source.work]
        source.work = [(o, s) for o, s in source.work if s > 0]
        target.work.append((op, moved))
        short = _write(company_id, balance, stations, _line_machines(company_id, line))
        audit(
            company_id,
            "factory.balance_moved",
            "line_balances",
            balance.id,
            {"version": balance.version, "operation": op.name[:160], "quantity": str(moved)},
        )
        return short

    return _transaction(action)


def publish(company_id, balance_id, version):
    require(company_id, "factory.manage")

    def action():
        balance = _locked(company_id, balance_id, version)
        ops = bulletin_ops(company_id, balance.bulletin_id)
        stations = stations_for(company_id, balance.id, ops)
        metrics = measure(ops, stations, 1, balance.target_efficiency)
        if metrics.unassigned:
            raise DomainError(
                "Every operation must be fully assigned before publishing: "
                + ", ".join(op.name for op, _ in metrics.unassigned[:5])
                + "."
            )
        if metrics.mixed:
            raise DomainError("Some stations combine two machine types; split them first.")
        balance.status = "published"
        balance.published_at = now()
        db.session.flush()
        audit(
            company_id,
            "factory.balance_published",
            "line_balances",
            balance.id,
            {"version": balance.version, "count": metrics.stations},
        )
        return balance

    return _transaction(action)


def start_revision(company_id, balance_id):
    """Copy a published balance into a new draft for the same line and style."""
    require(company_id, "factory.manage")

    def action():
        company_lock(company_id)
        require(company_id, "factory.manage")
        source = scoped(LineBalance, company_id, balance_id)
        existing = db.session.scalar(
            select(LineBalance).where(
                LineBalance.organization_id == company_id,
                LineBalance.work_center_id == source.work_center_id,
                LineBalance.status == "draft",
            )
        )
        if existing is not None:
            return existing
        line = _sewing_line(company_id, source.work_center_id)
        latest = db.session.scalar(
            select(func.max(LineBalance.revision)).where(
                LineBalance.organization_id == company_id, LineBalance.work_center_id == line.id
            )
        )
        balance = LineBalance(
            organization_id=company_id,
            work_center_id=line.id,
            bulletin_id=source.bulletin_id,
            revision=latest + 1,
            target_efficiency=source.target_efficiency,
            note=f"Copied from revision {source.revision}",
        )
        db.session.add(balance)
        db.session.flush()
        ops = bulletin_ops(company_id, balance.bulletin_id)
        _write(
            company_id,
            balance,
            stations_for(company_id, source.id, ops),
            _line_machines(company_id, line),
        )
        audit(
            company_id,
            "factory.balance_started",
            "line_balances",
            balance.id,
            {"version": balance.version, "source_id": str(source.id)},
        )
        return balance

    return _transaction(action)


def discard(company_id, balance_id, version):
    require(company_id, "factory.manage")

    def action():
        balance = _locked(company_id, balance_id, version)
        line_id = balance.work_center_id
        for model in (StationOperation, LineStation):
            for row in db.session.scalars(
                select(model).where(
                    model.organization_id == company_id, model.balance_id == balance.id
                )
            ):
                db.session.delete(row)
            db.session.flush()
        db.session.delete(balance)
        audit(company_id, "factory.balance_discarded", "line_balances", balance.id)
        return line_id

    return _transaction(action)


def summaries(company_id, balances):
    """{balance id: (stations, balance efficiency, output per day)} in a few queries."""
    from app.models.factory import BulletinOperation

    if not balances:
        return {}
    ids = [b.id for b in balances]
    loads = {}
    rows = db.session.execute(
        select(
            StationOperation.balance_id,
            StationOperation.station_id,
            StationOperation.share,
            BulletinOperation.sam,
        )
        .join(
            BulletinOperation,
            (BulletinOperation.id == StationOperation.bulletin_operation_id)
            & (BulletinOperation.organization_id == StationOperation.organization_id),
        )
        .where(StationOperation.organization_id == company_id, StationOperation.balance_id.in_(ids))
    ).all()
    for balance_id, station_id, share, sam in rows:
        per = loads.setdefault(balance_id, {})
        per[station_id] = per.get(station_id, Decimal(0)) + share * sam
    totals = engineering.bulletin_sams(company_id, list({b.bulletin_id for b in balances}))
    lines = {
        line.id: line
        for line in db.session.scalars(
            select(WorkCenter).where(
                WorkCenter.organization_id == company_id,
                WorkCenter.id.in_([b.work_center_id for b in balances]),
            )
        )
    }
    patterns = {
        p.id: p
        for p in db.session.scalars(
            select(ShiftPattern).where(ShiftPattern.organization_id == company_id)
        )
    }
    result = {}
    for balance in balances:
        per = loads.get(balance.id, {})
        total = Decimal(totals.get(balance.bulletin_id) or 0)
        if not per or not total:
            result[balance.id] = (len(per), Decimal(0), Decimal(0))
            continue
        peak = max(per.values())
        minutes = productive_minutes(patterns[lines[balance.work_center_id].shift_pattern_id])
        eta = Decimal(balance.target_efficiency) / 100
        result[balance.id] = (len(per), total / (len(per) * peak) * 100, minutes * eta / peak)
    return result
