"""Work content: operation bulletins, Standard Allowed Minutes (SAM) and line previews.

SAM is the currency of sewing capacity:

    operation SAM = basic minutes × (1 + allowance)          (blueprint section 5.3)
    garment SAM   = Σ operation SAM
    target output = operators × minutes × efficiency ÷ garment SAM    (section 5.4)
    pitch time    = garment SAM ÷ operators                            (section 5.5)

A bulletin is edited as a draft and then published. Published revisions are frozen by
database triggers, and a change means starting a new revision (copied from the last).
"""

import csv
import io
import math
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import now
from app.models.factory import BulletinOperation, MachineClass, OperationBulletin, Style
from app.policies import require
from app.services.audit import record as audit
from app.services.business import DomainError, company_lock, scoped

FOUR = Decimal("0.0001")
MAX_IMPORT_ROWS = 300
MAX_IMPORT_BYTES = 64 * 1024
CSV_HEADER = ("sequence", "operation", "machine", "basic_minutes", "allowance")


def operation_sam(basic_minutes, allowance_factor):
    return (Decimal(basic_minutes) * (1 + Decimal(allowance_factor))).quantize(
        FOUR, rounding=ROUND_HALF_UP
    )


@dataclass
class Summary:
    operations: int = 0
    basic: Decimal = Decimal(0)
    sam: Decimal = Decimal(0)
    by_class: dict = field(default_factory=dict)  # name -> SAM

    def target(self, operators, minutes, efficiency_percent):
        """Pieces per shift for a line (blueprint 5.4)."""
        if not self.sam:
            return Decimal(0)
        return Decimal(operators) * Decimal(minutes) * Decimal(efficiency_percent) / 100 / self.sam

    def pitch(self, operators):
        return self.sam / Decimal(operators) if operators else Decimal(0)

    def stations(self, operators):
        """Operators per machine type in proportion to its work content, summing to the line."""
        if not self.sam or not operators:
            return []
        shares = [(name, value / self.sam * operators) for name, value in self.by_class.items()]
        counts = {name: max(1, math.floor(share)) for name, share in shares}
        remaining = operators - sum(counts.values())
        for name, _share in sorted(
            shares, key=lambda pair: pair[1] - math.floor(pair[1]), reverse=True
        ):
            if remaining <= 0:
                break
            counts[name] += 1
            remaining -= 1
        return [(name, self.by_class[name], counts[name]) for name, _ in shares]


def summarize(rows):
    """rows: [(BulletinOperation, MachineClass | None)]."""
    result = Summary()
    for operation, machine_class in rows:
        result.operations += 1
        result.basic += operation.basic_minutes
        result.sam += operation.sam
        name = machine_class.name if machine_class else "Manual work"
        result.by_class[name] = result.by_class.get(name, Decimal(0)) + operation.sam
    return result


def operations(company_id, bulletin_id):
    return db.session.execute(
        select(BulletinOperation, MachineClass)
        .outerjoin(
            MachineClass,
            (MachineClass.id == BulletinOperation.machine_class_id)
            & (MachineClass.organization_id == BulletinOperation.organization_id),
        )
        .where(
            BulletinOperation.organization_id == company_id,
            BulletinOperation.bulletin_id == bulletin_id,
        )
        .order_by(BulletinOperation.sequence)
    ).all()


def current_bulletins(company_id, style_ids=None):
    """{style_id: latest published bulletin}."""
    latest = (
        select(OperationBulletin.style_id, func.max(OperationBulletin.revision).label("revision"))
        .where(
            OperationBulletin.organization_id == company_id,
            OperationBulletin.status == "published",
        )
        .group_by(OperationBulletin.style_id)
    )
    if style_ids is not None:
        latest = latest.where(OperationBulletin.style_id.in_(style_ids))
    latest = latest.subquery()
    rows = db.session.scalars(
        select(OperationBulletin)
        .join(
            latest,
            (latest.c.style_id == OperationBulletin.style_id)
            & (latest.c.revision == OperationBulletin.revision),
        )
        .where(OperationBulletin.organization_id == company_id)
    ).all()
    return {row.style_id: row for row in rows}


def bulletin_sams(company_id, bulletin_ids):
    if not bulletin_ids:
        return {}
    rows = db.session.execute(
        select(BulletinOperation.bulletin_id, func.sum(BulletinOperation.sam))
        .where(
            BulletinOperation.organization_id == company_id,
            BulletinOperation.bulletin_id.in_(bulletin_ids),
        )
        .group_by(BulletinOperation.bulletin_id)
    ).all()
    return dict(rows)


# ---------- Mutations ----------


def _transaction(action):
    try:
        result = action()
        db.session.commit()
        return result
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError(
            "A duplicate sequence number or a concurrent change prevented saving; reload and "
            "try again."
        ) from exc
    except Exception:
        db.session.rollback()
        raise


def _locked_bulletin(company_id, bulletin_id, version=None, draft=True):
    company_lock(company_id)
    require(company_id, "factory.manage")
    bulletin = scoped(OperationBulletin, company_id, bulletin_id, lock=True)
    if version is not None and bulletin.version != version:
        raise DomainError("This bulletin changed; reload before saving.")
    if draft and bulletin.status != "draft":
        raise DomainError(
            "Published bulletins are frozen. Start a new revision to change the work content."
        )
    return bulletin


def start_revision(company_id, style_id):
    """Open a draft revision, copied from the latest revision when there is one."""
    require(company_id, "factory.manage")

    def action():
        company_lock(company_id)
        require(company_id, "factory.manage")
        style = scoped(Style, company_id, style_id, lock=True)
        if style.archived_at:
            raise DomainError("Archived styles cannot get new revisions.")
        latest = db.session.scalar(
            select(OperationBulletin)
            .where(
                OperationBulletin.organization_id == company_id,
                OperationBulletin.style_id == style.id,
            )
            .order_by(OperationBulletin.revision.desc())
            .limit(1)
        )
        if latest is not None and latest.status == "draft":
            return latest
        bulletin = OperationBulletin(
            organization_id=company_id,
            style_id=style.id,
            revision=(latest.revision + 1) if latest else 1,
            allowance_factor=latest.allowance_factor if latest else Decimal("0.250"),
            source=f"Copied from revision {latest.revision}" if latest else "Manual",
        )
        db.session.add(bulletin)
        db.session.flush()
        if latest is not None:
            for operation, _ in operations(company_id, latest.id):
                db.session.add(
                    BulletinOperation(
                        organization_id=company_id,
                        bulletin_id=bulletin.id,
                        sequence=operation.sequence,
                        name=operation.name,
                        machine_class_id=operation.machine_class_id,
                        basic_minutes=operation.basic_minutes,
                        allowance_factor=operation.allowance_factor,
                        sam=operation.sam,
                    )
                )
        db.session.flush()
        audit(
            company_id,
            "factory.bulletin_started",
            "operation_bulletins",
            bulletin.id,
            {"version": bulletin.version},
        )
        return bulletin

    return _transaction(action)


def _sewing_class(company_id, value):
    if value in (None, ""):
        return None
    try:
        class_id = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise DomainError("Choose a valid machine class.") from exc
    machine_class = scoped(MachineClass, company_id, class_id)
    if machine_class.archived_at or machine_class.capacity_basis != "sewing":
        raise DomainError("Operations use an active sewing machine class, or manual work.")
    return machine_class.id


def _clean_operation(company_id, bulletin, values):
    name = str(values.get("name") or "").strip()
    if not name or len(name) > 120 or "\x00" in name:
        raise DomainError("Give the operation a name (up to 120 characters).")
    try:
        sequence = int(values.get("sequence"))
        basic = Decimal(str(values.get("basic_minutes")).strip())
        raw = values.get("allowance_factor")
        allowance = bulletin.allowance_factor if raw in (None, "") else Decimal(str(raw).strip())
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise DomainError("Sequence, basic minutes and allowance must be numbers.") from exc
    if not 1 <= sequence <= 9999:
        raise DomainError("Sequence must be between 1 and 9999.")
    if not (basic.is_finite() and Decimal("0.0001") <= basic <= 120):
        raise DomainError("Basic minutes must be between 0.0001 and 120.")
    if allowance > 1:  # Accept "25" as 25%.
        allowance = allowance / 100
    if not (allowance.is_finite() and 0 <= allowance <= 1):
        raise DomainError("Allowance must be between 0 and 100%.")
    basic = basic.quantize(FOUR, rounding=ROUND_HALF_UP)
    allowance = allowance.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return {
        "sequence": sequence,
        "name": name,
        "machine_class_id": _sewing_class(company_id, values.get("machine_class_id")),
        "basic_minutes": basic,
        "allowance_factor": allowance,
        "sam": operation_sam(basic, allowance),
    }


def save_operation(company_id, bulletin_id, values, operation_id=None, version=None):
    require(company_id, "factory.manage")

    def action():
        bulletin = _locked_bulletin(company_id, bulletin_id)
        if operation_id:
            row = scoped(BulletinOperation, company_id, operation_id, lock=True)
            if row.bulletin_id != bulletin.id:
                raise DomainError("That operation belongs to another bulletin.")
            if version is not None and row.version != version:
                raise DomainError("This operation changed; reload before saving.")
        else:
            row = BulletinOperation(organization_id=company_id, bulletin_id=bulletin.id)
        for name, value in _clean_operation(company_id, bulletin, values).items():
            setattr(row, name, value)
        db.session.add(row)
        db.session.flush()
        audit(
            company_id,
            "factory.operation_saved",
            "bulletin_operations",
            row.id,
            {"version": row.version},
        )
        return row

    return _transaction(action)


def delete_operation(company_id, bulletin_id, operation_id, version):
    require(company_id, "factory.manage")

    def action():
        bulletin = _locked_bulletin(company_id, bulletin_id)
        row = scoped(BulletinOperation, company_id, operation_id, lock=True)
        if row.bulletin_id != bulletin.id or row.version != version:
            raise DomainError("This operation changed; reload before removing it.")
        db.session.delete(row)
        audit(company_id, "factory.operation_deleted", "bulletin_operations", row.id)

    _transaction(action)


def parse_csv(company_id, text_value):
    """Rows from a GSD-style export: sequence, operation, machine, basic_minutes[, allowance].

    The machine column matches a sewing machine class code or name; blank or "manual" means
    manual work. Every row is checked before anything is written.
    """
    if not text_value or not text_value.strip():
        raise DomainError("Paste the rows to import.")
    if len(text_value.encode("utf-8")) > MAX_IMPORT_BYTES or "\x00" in text_value:
        raise DomainError("The pasted text is too large (64 KB at most).")
    classes = db.session.scalars(
        select(MachineClass).where(
            MachineClass.organization_id == company_id,
            MachineClass.capacity_basis == "sewing",
            MachineClass.archived_at.is_(None),
        )
    ).all()
    lookup = {}
    for machine_class in classes:
        lookup[machine_class.code.strip().lower()] = machine_class.id
        lookup[machine_class.name.strip().lower()] = machine_class.id
    reader = csv.reader(io.StringIO(text_value.strip()))
    rows, errors = [], []
    for number, record in enumerate(reader, 1):
        cells = [cell.strip() for cell in record]
        if not any(cells):
            continue
        if number == 1 and cells and cells[0].lower() == "sequence":
            continue
        if len(cells) not in (4, 5):
            errors.append(f"Line {number}: expected 4 or 5 columns, found {len(cells)}.")
            continue
        machine = cells[2].lower()
        if machine in ("", "manual", "hand", "helper"):
            class_id = None
        elif machine in lookup:
            class_id = lookup[machine]
        else:
            errors.append(f"Line {number}: unknown machine “{cells[2]}”.")
            continue
        rows.append(
            {
                "sequence": cells[0],
                "name": cells[1],
                "machine_class_id": class_id,
                "basic_minutes": cells[3],
                "allowance_factor": cells[4] if len(cells) == 5 else "",
                "_line": number,
            }
        )
        if len(rows) > MAX_IMPORT_ROWS:
            raise DomainError(f"Import at most {MAX_IMPORT_ROWS} operations at a time.")
    if errors:
        raise DomainError(" ".join(errors[:5]) + (" …" if len(errors) > 5 else ""))
    if not rows:
        raise DomainError("No operations found in the pasted text.")
    return rows


def import_operations(company_id, bulletin_id, text_value, replace=True):
    """All-or-nothing import into a draft bulletin; returns the number of operations."""
    require(company_id, "factory.manage")
    rows = parse_csv(company_id, text_value)

    def action():
        bulletin = _locked_bulletin(company_id, bulletin_id)
        cleaned = []
        sequences = set()
        for row in rows:
            try:
                clean = _clean_operation(company_id, bulletin, row)
            except DomainError as exc:
                raise DomainError(f"Line {row['_line']}: {exc}") from exc
            if clean["sequence"] in sequences:
                raise DomainError(f"Line {row['_line']}: sequence {clean['sequence']} repeats.")
            sequences.add(clean["sequence"])
            cleaned.append(clean)
        existing = [op for op, _ in operations(company_id, bulletin.id)]
        if replace:
            for operation in existing:
                db.session.delete(operation)
            db.session.flush()
        elif sequences & {op.sequence for op in existing}:
            raise DomainError("Some sequence numbers already exist; choose replace instead.")
        for clean in cleaned:
            db.session.add(
                BulletinOperation(organization_id=company_id, bulletin_id=bulletin.id, **clean)
            )
        bulletin.source = "Imported from pasted CSV"
        db.session.flush()
        audit(
            company_id,
            "factory.bulletin_imported",
            "operation_bulletins",
            bulletin.id,
            {"count": len(cleaned)},
        )
        return len(cleaned)

    return _transaction(action)


def publish(company_id, bulletin_id, version):
    require(company_id, "factory.manage")

    def action():
        bulletin = _locked_bulletin(company_id, bulletin_id, version)
        if not operations(company_id, bulletin.id):
            raise DomainError("Add at least one operation before publishing.")
        bulletin.status = "published"
        bulletin.published_at = now()
        db.session.flush()
        audit(
            company_id,
            "factory.bulletin_published",
            "operation_bulletins",
            bulletin.id,
            {"version": bulletin.version},
        )
        return bulletin

    return _transaction(action)


def discard_draft(company_id, bulletin_id, version):
    require(company_id, "factory.manage")

    def action():
        bulletin = _locked_bulletin(company_id, bulletin_id, version)
        for operation, _ in operations(company_id, bulletin.id):
            db.session.delete(operation)
        db.session.flush()
        db.session.delete(bulletin)
        audit(company_id, "factory.bulletin_discarded", "operation_bulletins", bulletin.id)
        return bulletin.style_id

    return _transaction(action)
