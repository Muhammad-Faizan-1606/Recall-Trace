"""Line quality: in-line and end-line checks, DHU, and where defects come from.

    DHU (defects per hundred units)  = defects ÷ pieces checked × 100
    defect rate                      = pieces with a defect ÷ pieces checked × 100

A piece can carry several defects, so DHU is at least the defect rate. Each defect row names
the operation (and, optionally, the station) at fault, which is what lets a supervisor talk
to the right operator. Checks are append-only; a correction restates the whole check.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select

from app.extensions import db
from app.models.factory import (
    DEFECT_CODES,
    BulletinOperation,
    LineCheckDefect,
    LineQualityCheck,
    ProductionOrder,
)
from app.services import shopfloor
from app.services.audit import record as audit
from app.services.business import DomainError, scoped

# End-line DHU above this raises an alert (a common knitwear target is 5 or lower).
DHU_LIMIT = Decimal("7.5")
MAX_DEFECT_ROWS = 6


@dataclass
class Quality:
    checks: list = field(default_factory=list)  # [(original id, effective check, corrected?)]
    pieces: dict = field(default_factory=lambda: {"inline": 0, "endline": 0})
    defective: dict = field(default_factory=lambda: {"inline": 0, "endline": 0})
    defects: dict = field(default_factory=lambda: {"inline": 0, "endline": 0})
    by_code: dict = field(default_factory=dict)  # code -> count
    by_operation: dict = field(default_factory=dict)  # operation id -> count

    def dhu(self, stage):
        pieces = self.pieces[stage]
        return Decimal(self.defects[stage]) / pieces * 100 if pieces else None

    def defect_rate(self, stage):
        pieces = self.pieces[stage]
        return Decimal(self.defective[stage]) / pieces * 100 if pieces else None


def summarize(checks, defects_by_check):
    result = Quality()
    for original, check in sorted(
        shopfloor.effective(checks).items(), key=lambda pair: (pair[1].hour, pair[1].stage)
    ):
        result.checks.append((original, check, check.id != original))
        result.pieces[check.stage] += check.pieces_checked
        result.defective[check.stage] += check.defective_pieces
        result.defects[check.stage] += check.defects
        for row in defects_by_check.get(check.id, []):
            result.by_code[row.defect_code] = result.by_code.get(row.defect_code, 0) + row.count
            if row.bulletin_operation_id:
                result.by_operation[row.bulletin_operation_id] = (
                    result.by_operation.get(row.bulletin_operation_id, 0) + row.count
                )
    return result


def _load(company_id, condition):
    checks = db.session.scalars(
        select(LineQualityCheck).where(LineQualityCheck.organization_id == company_id, *condition)
    ).all()
    rows = {}
    if checks:
        for row in db.session.scalars(
            select(LineCheckDefect).where(
                LineCheckDefect.organization_id == company_id,
                LineCheckDefect.check_id.in_([c.id for c in checks]),
            )
        ):
            rows.setdefault(row.check_id, []).append(row)
    return checks, rows


def line_day(company_id, line_id, day):
    checks, rows = _load(
        company_id, (LineQualityCheck.work_center_id == line_id, LineQualityCheck.day == day)
    )
    return summarize(checks, rows)


def floor(company_id, day, line_ids):
    """{line id: Quality} for one day."""
    if not line_ids:
        return {}
    checks, rows = _load(
        company_id, (LineQualityCheck.day == day, LineQualityCheck.work_center_id.in_(line_ids))
    )
    grouped = {}
    for check in checks:
        grouped.setdefault(check.work_center_id, []).append(check)
    return {line_id: summarize(grouped.get(line_id, []), rows) for line_id in line_ids}


def operation_names(company_id, ids):
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {
        o.id: o
        for o in db.session.scalars(
            select(BulletinOperation).where(
                BulletinOperation.organization_id == company_id, BulletinOperation.id.in_(ids)
            )
        )
    }


# ---------- Recording ----------


def _defect_rows(company_id, order, values):
    """[(code, operation id, station, count)] from form fields defect_code_N, operation_N…"""
    rows = []
    for index in range(1, MAX_DEFECT_ROWS + 1):
        code = str(values.get(f"defect_code_{index}") or "").strip()
        if not code:
            continue
        if code not in DEFECT_CODES:
            raise DomainError("Choose a listed defect type.")
        count = shopfloor._int(values, f"defect_count_{index}", "Defect count", 1, 10000)
        operation_id = None
        if values.get(f"operation_{index}"):
            try:
                operation_id = uuid.UUID(str(values[f"operation_{index}"]))
            except (TypeError, ValueError) as exc:
                raise DomainError("Choose a valid operation.") from exc
            operation = scoped(BulletinOperation, company_id, operation_id)
            if operation.bulletin_id != order.bulletin_id:
                raise DomainError("That operation is not in this order's bulletin.")
        station = None
        if values.get(f"station_{index}"):
            station = shopfloor._int(values, f"station_{index}", "Station", 1, 200)
        rows.append((code, operation_id, station, count))
    keys = [(code, operation_id) for code, operation_id, _, _ in rows]
    if len(set(keys)) != len(keys):
        raise DomainError("List each defect type once per operation.")
    return rows


def _check_values(company_id, values, today):
    order = shopfloor._released_order(company_id, values.get("production_order_id"))
    stage = str(values.get("stage") or "")
    if stage not in ("inline", "endline"):
        raise DomainError("Choose in-line or end-line.")
    pieces = shopfloor._int(values, "pieces_checked", "Pieces checked", 1, 10000)
    defective = shopfloor._int(values, "defective_pieces", "Pieces with defects", 0, pieces)
    rows = _defect_rows(company_id, order, values)
    defects = sum(count for *_, count in rows)
    if defective and not rows:
        raise DomainError("Say which defects were found.")
    if defects < defective:
        raise DomainError("Each defective piece has at least one defect; add the defects found.")
    return (
        order,
        {
            "production_order_id": order.id,
            "stage": stage,
            "hour": shopfloor._int(values, "hour", "Hour", 1, 24),
            "pieces_checked": pieces,
            "defective_pieces": defective,
            "defects": defects,
            "note": shopfloor._note(values),
        },
        rows,
    )


def _write(company_id, check, rows):
    db.session.add(check)
    db.session.flush()
    for code, operation_id, station, count in rows:
        db.session.add(
            LineCheckDefect(
                organization_id=company_id,
                check_id=check.id,
                defect_code=code,
                bulletin_operation_id=operation_id,
                station_number=station,
                count=count,
            )
        )
    db.session.flush()


def record_check(company_id, line_id, values, today=None):
    from app.policies import require

    require(company_id, shopfloor.PERMISSION)

    def action():
        member_id = shopfloor._start(company_id)
        line = shopfloor._sewing_line(company_id, line_id)
        day = shopfloor._day(values.get("day"), today)
        _, clean, rows = _check_values(company_id, values, today)
        check = LineQualityCheck(
            organization_id=company_id,
            work_center_id=line.id,
            day=day,
            recorded_by_id=member_id,
            **clean,
        )
        _write(company_id, check, rows)
        audit(
            company_id,
            "factory.quality_check",
            "line_quality_checks",
            check.id,
            {"quantity": check.pieces_checked, "count": check.defects},
        )
        return check

    return shopfloor._transaction(action)


def correct_check(company_id, check_id, values, today=None):
    from app.policies import require

    require(company_id, shopfloor.PERMISSION)

    def action():
        member_id = shopfloor._start(company_id)
        row = scoped(LineQualityCheck, company_id, check_id)
        original = scoped(LineQualityCheck, company_id, row.corrects_id) if row.corrects_id else row
        shopfloor._day(original.day, today)
        _, clean, rows = _check_values(company_id, values, today)
        if not clean["note"]:
            raise DomainError("Say why the check is being corrected.")
        check = LineQualityCheck(
            organization_id=company_id,
            work_center_id=original.work_center_id,
            day=original.day,
            corrects_id=original.id,
            recorded_by_id=member_id,
            **clean,
        )
        _write(company_id, check, rows)
        audit(
            company_id,
            "factory.quality_check_corrected",
            "line_quality_checks",
            check.id,
            {"source_id": str(original.id), "count": check.defects},
        )
        return check

    return shopfloor._transaction(action)


def order_operations(company_id, order_id):
    order = scoped(ProductionOrder, company_id, order_id)
    return db.session.scalars(
        select(BulletinOperation)
        .where(
            BulletinOperation.organization_id == company_id,
            BulletinOperation.bulletin_id == order.bulletin_id,
        )
        .order_by(BulletinOperation.sequence)
    ).all()
