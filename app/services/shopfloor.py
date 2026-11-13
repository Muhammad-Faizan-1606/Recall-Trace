"""Shop floor execution: hourly output, downtime, batch cards and bundle tickets.

Achieved efficiency for a line and day (blueprint section 3.5):

    earned minutes   = Σ good pieces × garment SAM
    clock minutes    = Σ operators present × minutes worked, hour by hour
    off-standard     = Σ downtime minutes × operators affected, for approved reasons
    efficiency       = earned ÷ (clock − off-standard) × 100

Output logs and downtime events are append-only. A correction is a new row restating the
whole entry and pointing at the original (`corrects_id`); the newest row for an entry is
the one that counts, and the database refuses to change or delete any row.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import now
from app.models.factory import (
    CutBundle,
    DowntimeEvent,
    DowntimeReason,
    DyeBatch,
    KnitRoll,
    Machine,
    MachineClass,
    OutputLog,
    ProductionOrder,
    WorkCenter,
)
from app.policies import membership_for, require
from app.services import engineering
from app.services.audit import record as audit
from app.services.business import DomainError, company_lock, scoped

PERMISSION = "factory.record"
BACKDATE_DAYS = 7
MAX_BUNDLES = 400


# ---------- Reading a line's day ----------


def effective(rows):
    """{original id: newest row} for append-only entries with restating corrections."""
    latest = {}
    for row in rows:
        key = row.corrects_id or row.id
        current = latest.get(key)
        if current is None or (row.recorded_at, row.corrects_id is not None) > (
            current.recorded_at,
            current.corrects_id is not None,
        ):
            latest[key] = row
    return latest


@dataclass
class Day:
    hours: list = field(default_factory=list)  # [(original id, effective OutputLog, corrected?)]
    downtime: list = field(
        default_factory=list
    )  # [(original id, DowntimeEvent, reason, corrected?)]
    good: int = 0
    rejects: int = 0
    earned: Decimal = Decimal(0)
    clock: Decimal = Decimal(0)
    off_standard: Decimal = Decimal(0)
    lost: Decimal = Decimal(0)  # downtime the line answers for (operator-minutes)

    @property
    def available(self):
        return self.clock - self.off_standard

    @property
    def efficiency(self):
        return self.earned / self.available * 100 if self.available > 0 else None

    @property
    def reject_rate(self):
        made = self.good + self.rejects
        return Decimal(self.rejects) / made * 100 if made else None

    @property
    def downtime_minutes(self):
        return sum(event.minutes for _, event, _, _ in self.downtime)


def line_day(company_id, line_id, day):
    logs = db.session.scalars(
        select(OutputLog).where(
            OutputLog.organization_id == company_id,
            OutputLog.work_center_id == line_id,
            OutputLog.day == day,
        )
    ).all()
    events = db.session.scalars(
        select(DowntimeEvent).where(
            DowntimeEvent.organization_id == company_id,
            DowntimeEvent.work_center_id == line_id,
            DowntimeEvent.day == day,
        )
    ).all()
    reasons = {
        r.id: r
        for r in db.session.scalars(
            select(DowntimeReason).where(DowntimeReason.organization_id == company_id)
        )
    }
    return summarize(logs, events, reasons)


def summarize(logs, events, reasons):
    result = Day()
    for original, row in sorted(effective(logs).items(), key=lambda pair: pair[1].hour):
        result.hours.append((original, row, row.id != original))
        result.good += row.good_pieces
        result.rejects += row.rejects
        result.earned += row.good_pieces * row.sam
        result.clock += Decimal(row.operators * row.minutes)
    for original, event in sorted(effective(events).items(), key=lambda pair: pair[1].hour):
        reason = reasons.get(event.reason_id)
        if event.minutes == 0:
            continue  # withdrawn by a correction
        result.downtime.append((original, event, reason, event.id != original))
        lost = Decimal(event.minutes * event.operators_affected)
        if reason is not None and reason.efficiency_rule == "off_standard":
            result.off_standard += lost
        else:
            result.lost += lost
    # Off-standard time cannot exceed the time people were actually booked for.
    result.off_standard = min(result.off_standard, result.clock)
    return result


def floor(company_id, day, line_ids):
    """{line id: Day} for many lines in three queries."""
    if not line_ids:
        return {}
    logs, events = {}, {}
    for row in db.session.scalars(
        select(OutputLog).where(
            OutputLog.organization_id == company_id,
            OutputLog.day == day,
            OutputLog.work_center_id.in_(line_ids),
        )
    ):
        logs.setdefault(row.work_center_id, []).append(row)
    for row in db.session.scalars(
        select(DowntimeEvent).where(
            DowntimeEvent.organization_id == company_id,
            DowntimeEvent.day == day,
            DowntimeEvent.work_center_id.in_(line_ids),
        )
    ):
        events.setdefault(row.work_center_id, []).append(row)
    reasons = {
        r.id: r
        for r in db.session.scalars(
            select(DowntimeReason).where(DowntimeReason.organization_id == company_id)
        )
    }
    return {
        line_id: summarize(logs.get(line_id, []), events.get(line_id, []), reasons)
        for line_id in line_ids
    }


def history(company_id, model, original_id):
    """Every row of one entry, oldest first: the original and its corrections."""
    return db.session.scalars(
        select(model)
        .where(
            model.organization_id == company_id,
            (model.id == original_id) | (model.corrects_id == original_id),
        )
        .order_by(model.recorded_at, model.corrects_id.is_not(None))
    ).all()


def running_orders(company_id):
    return db.session.scalars(
        select(ProductionOrder)
        .where(
            ProductionOrder.organization_id == company_id,
            ProductionOrder.status == "released",
        )
        .order_by(ProductionOrder.priority, ProductionOrder.ex_factory_on)
    ).all()


# ---------- Writing helpers ----------


def _transaction(action):
    try:
        result = action()
        db.session.commit()
        return result
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError(
            "That entry already exists or changed at the same time; reload and try again."
        ) from exc
    except Exception:
        db.session.rollback()
        raise


def _start(company_id):
    company_lock(company_id)
    require(company_id, PERMISSION)
    member = membership_for(company_id)
    return member.id if member else None


def _int(values, name, label, low, high):
    try:
        number = Decimal(str(values.get(name)).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise DomainError(f"{label} must be a whole number.") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise DomainError(f"{label} must be a whole number.")
    number = int(number)
    if not low <= number <= high:
        raise DomainError(f"{label} must be between {low} and {high}.")
    return number


def _uuid(value, message):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise DomainError(message) from exc


def _day(value, today=None):
    today = today or date.today()
    if not isinstance(value, date):
        try:
            value = date.fromisoformat(str(value))
        except ValueError as exc:
            raise DomainError("Enter the day as YYYY-MM-DD.") from exc
    if value > today:
        raise DomainError("Output and downtime cannot be recorded for a future day.")
    if value < today - timedelta(days=BACKDATE_DAYS):
        raise DomainError(f"Late entries are accepted for up to {BACKDATE_DAYS} days.")
    return value


def _note(values):
    note = str(values.get("note") or "").strip()
    if len(note) > 200 or "\x00" in note:
        raise DomainError("Keep the note under 200 characters.")
    return note or None


def _sewing_line(company_id, line_id):
    line = scoped(WorkCenter, company_id, line_id)
    if line.department != "sewing" or line.archived_at:
        raise DomainError("Choose an active sewing line.")
    return line


def _released_order(company_id, order_id):
    order = scoped(ProductionOrder, company_id, _uuid(order_id, "Choose the order being sewn."))
    if order.status != "released":
        raise DomainError("Only orders released to the floor can receive output.")
    return order


def _order_sam(company_id, order):
    sam = engineering.bulletin_sams(company_id, [order.bulletin_id]).get(order.bulletin_id)
    if not sam:
        raise DomainError("The order's bulletin has no SAM.")
    return Decimal(sam)


# ---------- Hourly output ----------


def _output_values(company_id, values, today):
    order = _released_order(company_id, values.get("production_order_id"))
    clean = {
        "production_order_id": order.id,
        "good_pieces": _int(values, "good_pieces", "Good pieces", 0, 100000),
        "rejects": _int(values, "rejects", "Rejects", 0, 100000),
        "operators": _int(values, "operators", "Operators", 0, 500),
        "minutes": _int(values, "minutes", "Minutes worked", 0, 60),
        "note": _note(values),
        "sam": _order_sam(company_id, order),
    }
    if clean["good_pieces"] and not clean["operators"]:
        raise DomainError("Pieces were made, so at least one operator was present.")
    return clean


def record_output(company_id, line_id, values, today=None):
    require(company_id, PERMISSION)

    def action():
        member_id = _start(company_id)
        line = _sewing_line(company_id, line_id)
        day = _day(values.get("day"), today)
        hour = _int(values, "hour", "Hour", 1, 24)
        if db.session.scalar(
            select(OutputLog.id).where(
                OutputLog.organization_id == company_id,
                OutputLog.work_center_id == line.id,
                OutputLog.day == day,
                OutputLog.hour == hour,
                OutputLog.corrects_id.is_(None),
            )
        ):
            raise DomainError(f"Hour {hour} is already recorded; correct it instead.")
        row = OutputLog(
            organization_id=company_id,
            work_center_id=line.id,
            day=day,
            hour=hour,
            recorded_by_id=member_id,
            **_output_values(company_id, values, today),
        )
        db.session.add(row)
        db.session.flush()
        audit(
            company_id,
            "factory.output_recorded",
            "output_logs",
            row.id,
            {"quantity": row.good_pieces, "count": row.rejects, "step": hour},
        )
        return row

    return _transaction(action)


def correct_output(company_id, log_id, values, today=None):
    """Restate an hour; the original stays as history and the new row counts."""
    require(company_id, PERMISSION)

    def action():
        member_id = _start(company_id)
        row = scoped(OutputLog, company_id, log_id)
        original = scoped(OutputLog, company_id, row.corrects_id) if row.corrects_id else row
        current = effective(history(company_id, OutputLog, original.id))[original.id]
        _day(original.day, today)
        clean = _output_values(company_id, values, today)
        unchanged = all(
            getattr(current, name) == value
            for name, value in clean.items()
            if name not in ("note", "sam")
        )
        if unchanged:
            raise DomainError("Nothing changed; the hour already reads like that.")
        if not clean["note"]:
            raise DomainError("Say why the hour is being corrected.")
        correction = OutputLog(
            organization_id=company_id,
            work_center_id=original.work_center_id,
            day=original.day,
            hour=original.hour,
            corrects_id=original.id,
            recorded_by_id=member_id,
            **clean,
        )
        db.session.add(correction)
        db.session.flush()
        audit(
            company_id,
            "factory.output_corrected",
            "output_logs",
            correction.id,
            {"source_id": str(original.id), "quantity": correction.good_pieces},
        )
        return correction

    return _transaction(action)


# ---------- Downtime ----------


def _downtime_values(company_id, line, values, allow_zero=False):
    reason = scoped(DowntimeReason, company_id, _uuid(values.get("reason_id"), "Choose a reason."))
    if reason.archived_at:
        raise DomainError("Choose an active downtime reason.")
    machine_id = None
    if values.get("machine_id"):
        machine = scoped(Machine, company_id, _uuid(values["machine_id"], "Choose a machine."))
        if machine.work_center_id != line.id:
            raise DomainError("That machine is not on this line.")
        machine_id = machine.id
    return {
        "reason_id": reason.id,
        "machine_id": machine_id,
        "hour": _int(values, "hour", "Hour", 1, 24),
        "minutes": _int(values, "minutes", "Minutes lost", 0 if allow_zero else 1, 600),
        "operators_affected": _int(values, "operators_affected", "Operators affected", 0, 500),
        "note": _note(values),
    }


def record_downtime(company_id, line_id, values, today=None):
    require(company_id, PERMISSION)

    def action():
        member_id = _start(company_id)
        line = _sewing_line(company_id, line_id)
        day = _day(values.get("day"), today)
        clean = _downtime_values(company_id, line, values)
        if not clean["operators_affected"]:
            raise DomainError("At least one operator was affected.")
        row = DowntimeEvent(
            organization_id=company_id,
            work_center_id=line.id,
            day=day,
            recorded_by_id=member_id,
            **clean,
        )
        db.session.add(row)
        db.session.flush()
        audit(
            company_id,
            "factory.downtime_recorded",
            "downtime_events",
            row.id,
            {"quantity": row.minutes, "count": row.operators_affected},
        )
        return row

    return _transaction(action)


def correct_downtime(company_id, event_id, values, today=None):
    """Restate a stop. Zero minutes withdraws it while keeping the history."""
    require(company_id, PERMISSION)

    def action():
        member_id = _start(company_id)
        row = scoped(DowntimeEvent, company_id, event_id)
        original = scoped(DowntimeEvent, company_id, row.corrects_id) if row.corrects_id else row
        line = scoped(WorkCenter, company_id, original.work_center_id)
        _day(original.day, today)
        clean = _downtime_values(company_id, line, values, allow_zero=True)
        if not clean["note"]:
            raise DomainError("Say why the stop is being corrected.")
        correction = DowntimeEvent(
            organization_id=company_id,
            work_center_id=original.work_center_id,
            day=original.day,
            corrects_id=original.id,
            recorded_by_id=member_id,
            **clean,
        )
        db.session.add(correction)
        db.session.flush()
        audit(
            company_id,
            "factory.downtime_corrected",
            "downtime_events",
            correction.id,
            {"source_id": str(original.id), "quantity": correction.minutes},
        )
        return correction

    return _transaction(action)


# ---------- Batch cards ----------


def _text(values, name, label, maximum, required=True):
    value = str(values.get(name) or "").strip()
    if "\x00" in value or len(value) > maximum:
        raise DomainError(f"{label} is too long.")
    if required and not value:
        raise DomainError(f"{label} is required.")
    return value or None


def _machine(company_id, value, department, label):
    machine = scoped(Machine, company_id, _uuid(value, f"Choose a {label}."))
    center = scoped(WorkCenter, company_id, machine.work_center_id)
    if center.department != department or machine.archived_at:
        raise DomainError(f"Choose an active {label}.")
    if machine.status == "decommissioned":
        raise DomainError(f"That {label} is decommissioned.")
    return machine


def _optional_order(company_id, value):
    if not value:
        return None
    order = scoped(ProductionOrder, company_id, _uuid(value, "Choose a valid order."))
    if order.status in ("completed", "cancelled"):
        raise DomainError("That order is closed.")
    return order.id


def record_roll(company_id, values, today=None):
    require(company_id, PERMISSION)

    def action():
        _start(company_id)
        machine = _machine(company_id, values.get("machine_id"), "knitting", "knitting machine")
        try:
            kg = Decimal(str(values.get("kg")).strip()).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError) as exc:
            raise DomainError("Roll weight must be a number of kilograms.") from exc
        if not (kg.is_finite() and 0 < kg <= 100):
            raise DomainError("A roll weighs more than 0 and at most 100 kg.")
        grade = str(values.get("grade") or "A")
        if grade not in ("A", "B", "C"):
            raise DomainError("Grade is A, B or C.")
        row = KnitRoll(
            organization_id=company_id,
            roll_number=_text(values, "roll_number", "Roll number", 40),
            machine_id=machine.id,
            production_order_id=_optional_order(company_id, values.get("production_order_id")),
            knitted_on=_day(values.get("knitted_on"), today),
            kg=kg,
            grade=grade,
        )
        db.session.add(row)
        db.session.flush()
        audit(company_id, "factory.roll_recorded", "knit_rolls", row.id, {"quantity": str(kg)})
        return row

    return _transaction(action)


def loadable_rolls(company_id):
    """Rolls not yet in a batch, or whose batch must be dyed again."""
    redye = select(DyeBatch.id).where(
        DyeBatch.organization_id == company_id, DyeBatch.status == "re_dye"
    )
    return db.session.scalars(
        select(KnitRoll)
        .where(
            KnitRoll.organization_id == company_id,
            KnitRoll.grade != "C",
            KnitRoll.dye_batch_id.is_(None) | KnitRoll.dye_batch_id.in_(redye),
        )
        .order_by(KnitRoll.knitted_on, KnitRoll.roll_number)
    ).all()


def vessel_kg(company_id, machine):
    """Rated kg per load of a batch vessel."""
    machine_class = scoped(MachineClass, company_id, machine.machine_class_id)
    if machine_class.capacity_basis != "batch":
        raise DomainError("Choose a batch dyeing vessel.")
    return Decimal(machine.rated_value)


def load_batch(company_id, values):
    """Create a dye batch from rolls; the load must fit the vessel."""
    require(company_id, PERMISSION)

    def action():
        _start(company_id)
        machine = _machine(company_id, values.get("machine_id"), "dyeing", "dyeing vessel")
        if machine.status != "active":
            raise DomainError("That vessel is not running; choose an active one.")
        capacity = vessel_kg(company_id, machine)
        roll_ids = [_uuid(value, "Choose valid rolls.") for value in values.get("roll_ids") or []]
        if not roll_ids:
            raise DomainError("Load at least one roll.")
        allowed = {roll.id: roll for roll in loadable_rolls(company_id)}
        missing = [value for value in roll_ids if value not in allowed]
        if missing:
            raise DomainError("Some rolls are already in a batch, graded C, or not found.")
        rolls = [
            db.session.scalar(
                select(KnitRoll)
                .where(KnitRoll.organization_id == company_id, KnitRoll.id == value)
                .with_for_update()
            )
            for value in sorted(set(roll_ids))
        ]
        total = sum(roll.kg for roll in rolls)
        if total > capacity:
            raise DomainError(
                f"{total} kg is more than the vessel's {capacity.normalize()} kg load."
            )
        batch = DyeBatch(
            organization_id=company_id,
            batch_number=_text(values, "batch_number", "Batch number", 40),
            machine_id=machine.id,
            production_order_id=_optional_order(company_id, values.get("production_order_id")),
            colour=_text(values, "colour", "Colour", 60),
            recipe_reference=_text(values, "recipe_reference", "Recipe reference", 60),
            note=_note(values),
        )
        db.session.add(batch)
        db.session.flush()
        for roll in rolls:
            roll.dye_batch_id = batch.id
        db.session.flush()
        audit(
            company_id,
            "factory.batch_loaded",
            "dye_batches",
            batch.id,
            {"count": len(rolls), "quantity": str(total)},
        )
        return batch, total, capacity

    return _transaction(action)


BATCH_STEPS = {
    "start": ("loaded", "dyeing"),
    "passed": ("dyeing", "passed"),
    "re_dye": ("dyeing", "re_dye"),
    "rejected": ("dyeing", "rejected"),
}


def batch_step(company_id, batch_id, step, version):
    require(company_id, PERMISSION)
    if step not in BATCH_STEPS:
        raise DomainError("Unknown batch step.")

    def action():
        _start(company_id)
        batch = scoped(DyeBatch, company_id, batch_id, lock=True)
        if batch.version != version:
            raise DomainError("This batch changed; reload before continuing.")
        before, after = BATCH_STEPS[step]
        if batch.status != before:
            raise DomainError(f"A {batch.status.replace('_', ' ')} batch cannot do that.")
        batch.status = after
        if step == "start":
            batch.started_at = now()
        else:
            batch.finished_at = now()
        db.session.flush()
        audit(
            company_id,
            "factory.batch_step",
            "dye_batches",
            batch.id,
            {"from_status": before, "to_status": after},
        )
        return batch

    return _transaction(action)


def batch_kg(company_id, batch_ids):
    if not batch_ids:
        return {}
    return dict(
        db.session.execute(
            select(KnitRoll.dye_batch_id, func.sum(KnitRoll.kg))
            .where(KnitRoll.organization_id == company_id, KnitRoll.dye_batch_id.in_(batch_ids))
            .group_by(KnitRoll.dye_batch_id)
        ).all()
    )


# ---------- Cut bundles ----------


def parse_sizes(text_value):
    """'S:120, M:240' → [('S', 120), ('M', 240)]."""
    sizes = []
    for part in str(text_value or "").replace(";", ",").split(","):
        if not part.strip():
            continue
        name, _, count = part.partition(":")
        name = name.strip().upper()
        if not name or len(name) > 10 or "\x00" in name:
            raise DomainError("Write sizes like S:120, M:240.")
        try:
            pieces = int(count.strip())
        except ValueError as exc:
            raise DomainError(f"Pieces for size {name} must be a whole number.") from exc
        if not 1 <= pieces <= 100000:
            raise DomainError(f"Pieces for size {name} must be between 1 and 100,000.")
        sizes.append((name, pieces))
    if not sizes:
        raise DomainError("Enter at least one size, like S:120, M:240.")
    if len({name for name, _ in sizes}) != len(sizes):
        raise DomainError("Each size can appear once.")
    return sizes


def cut_bundles(company_id, values):
    """Cut a lay into numbered bundles of at most `bundle_size` pieces per size."""
    require(company_id, PERMISSION)

    def action():
        _start(company_id)
        order = scoped(
            ProductionOrder,
            company_id,
            _uuid(values.get("production_order_id"), "Choose the order being cut."),
            lock=True,
        )
        if order.status != "released":
            raise DomainError("Cut only orders released to the floor.")
        batch_id = None
        if values.get("dye_batch_id"):
            batch = scoped(DyeBatch, company_id, _uuid(values["dye_batch_id"], "Choose a batch."))
            if batch.status != "passed":
                raise DomainError("Cut only fabric from a dye batch that passed.")
            batch_id = batch.id
        lay = _text(values, "lay_number", "Lay number", 40)
        size_of_bundle = _int(values, "bundle_size", "Pieces per bundle", 1, 500)
        sizes = parse_sizes(values.get("sizes"))
        planned = []
        for size, pieces in sizes:
            full, rest = divmod(pieces, size_of_bundle)
            planned += [(size, size_of_bundle)] * full + ([(size, rest)] if rest else [])
        if len(planned) > MAX_BUNDLES:
            raise DomainError(f"That makes {len(planned)} bundles; cut at most {MAX_BUNDLES}.")
        already = db.session.scalar(
            select(func.coalesce(func.sum(CutBundle.pieces), 0)).where(
                CutBundle.organization_id == company_id,
                CutBundle.production_order_id == order.id,
            )
        )
        cutting = sum(pieces for _, pieces in planned)
        if already + cutting > order.quantity * Decimal("1.05"):
            raise DomainError(
                f"That would cut {already + cutting:,} pieces against an order of "
                f"{order.quantity:,} (5% cutting allowance)."
            )
        count = db.session.scalar(
            select(func.count(CutBundle.id)).where(
                CutBundle.organization_id == company_id,
                CutBundle.production_order_id == order.id,
            )
        )
        bundles = []
        for offset, (size, pieces) in enumerate(planned, 1):
            bundle = CutBundle(
                organization_id=company_id,
                bundle_number=f"{order.reference}-{count + offset:04d}",
                production_order_id=order.id,
                dye_batch_id=batch_id,
                lay_number=lay,
                size=size,
                pieces=pieces,
            )
            db.session.add(bundle)
            bundles.append(bundle)
        db.session.flush()
        audit(
            company_id,
            "factory.bundles_cut",
            "production_orders",
            order.id,
            {"count": len(bundles), "quantity": cutting},
        )
        return bundles

    return _transaction(action)


def bundle_step(company_id, bundle_id, step, version, line_id=None):
    """Issue a cut bundle to a sewing line, or mark an issued bundle sewn."""
    require(company_id, PERMISSION)

    def action():
        _start(company_id)
        bundle = scoped(CutBundle, company_id, bundle_id, lock=True)
        if bundle.version != version:
            raise DomainError("This bundle changed; reload before continuing.")
        if step == "issue":
            if bundle.status != "cut":
                raise DomainError("Only cut bundles can be issued.")
            line = _sewing_line(company_id, line_id)
            bundle.status, bundle.issued_line_id, bundle.issued_at = "issued", line.id, now()
        elif step == "sewn":
            if bundle.status != "issued":
                raise DomainError("Only bundles on a line can be marked sewn.")
            bundle.status, bundle.sewn_at = "sewn", now()
        else:
            raise DomainError("Unknown bundle step.")
        db.session.flush()
        audit(
            company_id,
            "factory.bundle_step",
            "cut_bundles",
            bundle.id,
            {"to_status": bundle.status},
        )
        return bundle

    return _transaction(action)


def find_bundle(company_id, number):
    return db.session.scalar(
        select(CutBundle).where(
            CutBundle.organization_id == company_id,
            CutBundle.bundle_number == str(number or "").strip().upper(),
        )
    )
