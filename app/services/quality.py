"""Checked quality evidence, frozen inspection versions, and independent hold review."""

from functools import wraps

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import now
from app.models.master import Lot
from app.models.quality import (
    HoldReview,
    Inspection,
    InspectionCheck,
    InspectionResult,
    InspectionTemplate,
    Nonconformance,
    QualityDocument,
    QualityHold,
)
from app.services.business import DomainError, actor, company_lock, quantity, scoped


def mutation(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
            from app.services.audit import record

            record(
                args[0],
                function.__module__.rsplit(".", 1)[-1] + "." + function.__name__,
                function.__name__,
                getattr(result, "id", None),
                {},
            )
            db.session.commit()
            return result
        except (IntegrityError, StaleDataError) as exc:
            db.session.rollback()
            raise DomainError(
                "The record changed or conflicts with existing data. Reload and retry."
            ) from exc
        except Exception:
            db.session.rollback()
            raise

    return checked


def text(value, maximum=4000):
    value = str(value or "").strip()
    if not value or len(value) > maximum:
        raise DomainError(f"Enter text between 1 and {maximum} characters.")
    return value


def expected(row, version):
    if version is not None and row.version != int(version):
        raise DomainError("This record changed. Reload before saving.")


def draft(row):
    if row.status != "draft":
        raise DomainError("Only draft records may be edited or deleted.")


@mutation
def save_template(company_id, code, revision=1, template_id=None, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    row = (
        scoped(InspectionTemplate, company_id, template_id, True)
        if template_id
        else InspectionTemplate(organization_id=company_id)
    )
    if template_id:
        expected(row, version)
        draft(row)
    try:
        revision = int(revision)
    except (ValueError, TypeError) as exc:
        raise DomainError("Revision must be a positive integer.") from exc
    if revision < 1:
        raise DomainError("Revision must be a positive integer.")
    row.code, row.revision = text(code, 60), revision
    db.session.add(row)
    return row


@mutation
def save_check(
    company_id, template_id, sequence, label, value_type, rule, check_id=None, version=None
):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    template = scoped(InspectionTemplate, company_id, template_id, True)
    draft(template)
    if value_type not in {"number", "text", "boolean"}:
        raise DomainError("Choose a supported observation type.")
    if not isinstance(rule, dict) or set(rule) - {"min", "max", "equals"}:
        raise DomainError("Rules permit only min, max and equals values.")
    validated = {}
    for key, value in rule.items():
        if value_type == "number":
            validated[key] = str(quantity(value, positive=False))
        elif key != "equals":
            raise DomainError("Text and boolean checks accept an equals rule only.")
        else:
            validated[key] = text(value, 1000)
    if (
        "min" in validated
        and "max" in validated
        and quantity(validated["min"], positive=False) > quantity(validated["max"], positive=False)
    ):
        raise DomainError("Minimum cannot exceed maximum.")
    try:
        sequence = int(sequence)
    except (ValueError, TypeError) as exc:
        raise DomainError("Sequence must be a positive integer.") from exc
    if sequence < 1:
        raise DomainError("Sequence must be a positive integer.")
    row = (
        scoped(InspectionCheck, company_id, check_id, True)
        if check_id
        else InspectionCheck(organization_id=company_id, template_id=template.id)
    )
    if row.template_id != template.id:
        raise DomainError("Check does not belong to this template.")
    expected(row, version)
    row.sequence, row.label, row.value_type, row.rule_definition = (
        sequence,
        text(label, 160),
        value_type,
        validated,
    )
    db.session.add(row)
    # Touch the parent so concurrent editors cannot silently publish stale definitions.
    template.updated_at = now()
    return row


@mutation
def publish_template(company_id, template_id, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    row = scoped(InspectionTemplate, company_id, template_id, True)
    expected(row, version)
    draft(row)
    if not db.session.scalar(
        select(InspectionCheck.id).where(InspectionCheck.template_id == row.id).limit(1)
    ):
        raise DomainError("Add at least one inspection check before publishing.")
    row.status = "published"
    return row


@mutation
def delete_template(company_id, template_id, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    row = scoped(InspectionTemplate, company_id, template_id, True)
    expected(row, version)
    draft(row)
    for check in db.session.scalars(
        select(InspectionCheck).where(InspectionCheck.template_id == row.id)
    ):
        db.session.delete(check)
    db.session.flush()
    db.session.delete(row)


@mutation
def delete_check(company_id, check_id, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    row = scoped(InspectionCheck, company_id, check_id, True)
    draft(scoped(InspectionTemplate, company_id, row.template_id, True))
    expected(row, version)
    db.session.delete(row)


@mutation
def create_inspection(company_id, reference, lot_id, template_id):
    member = actor(company_id, "quality.inspect")
    company_lock(company_id)
    lot = scoped(Lot, company_id, lot_id, True)
    if lot.archived_at:
        raise DomainError("Choose an active lot.")
    template = scoped(InspectionTemplate, company_id, template_id, True)
    if template.status != "published":
        raise DomainError("Inspection requires a published template revision.")
    row = Inspection(
        organization_id=company_id,
        reference=text(reference, 80),
        lot_id=lot.id,
        template_id=template.id,
        inspector_id=member.id,
    )
    db.session.add(row)
    return row


@mutation
def observe(company_id, inspection_id, check_id, value, comment="", version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    inspection = scoped(Inspection, company_id, inspection_id, True)
    expected(inspection, version)
    draft(inspection)
    check = scoped(InspectionCheck, company_id, check_id)
    if check.template_id != inspection.template_id:
        raise DomainError("The check belongs to another template revision.")
    numeric, rendered = None, str(value or "").strip()
    rule = check.rule_definition
    if check.value_type == "number":
        numeric = quantity(value, positive=False)
        passed = all(
            (key != "min" or numeric >= quantity(limit, positive=False))
            and (key != "max" or numeric <= quantity(limit, positive=False))
            and (key != "equals" or numeric == quantity(limit, positive=False))
            for key, limit in rule.items()
        )
        rendered = None
    else:
        rendered = text(rendered, 1000)
        if check.value_type == "boolean" and rendered not in {"true", "false"}:
            raise DomainError("Boolean observations use true or false.")
        passed = "equals" not in rule or rendered == rule["equals"]
    if len(comment) > 4000:
        raise DomainError("Observation comment is too long.")
    row = db.session.scalar(
        select(InspectionResult).where(
            InspectionResult.inspection_id == inspection.id, InspectionResult.check_id == check.id
        )
    )
    if row is None:
        row = InspectionResult(
            organization_id=company_id, inspection_id=inspection.id, check_id=check.id
        )
        db.session.add(row)
    row.numeric_value, row.text_value, row.outcome, row.comment = (
        numeric,
        rendered,
        "pass" if passed else "fail",
        comment,
    )
    inspection.updated_at = now()
    return row


@mutation
def complete_inspection(company_id, inspection_id, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    row = scoped(Inspection, company_id, inspection_id, True)
    expected(row, version)
    draft(row)
    checks = set(
        db.session.scalars(
            select(InspectionCheck.id).where(InspectionCheck.template_id == row.template_id)
        )
    )
    results = set(
        db.session.scalars(
            select(InspectionResult.check_id).where(InspectionResult.inspection_id == row.id)
        )
    )
    if not checks or checks != results:
        raise DomainError("Record an observation for every check before completing.")
    row.status, row.inspected_at = "completed", now()
    return row


@mutation
def delete_inspection(company_id, inspection_id, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    row = scoped(Inspection, company_id, inspection_id, True)
    expected(row, version)
    draft(row)
    for observation in db.session.scalars(
        select(InspectionResult).where(InspectionResult.inspection_id == row.id)
    ):
        db.session.delete(observation)
    db.session.flush()
    db.session.delete(row)


@mutation
def save_nonconformance(
    company_id,
    reference,
    lot_id,
    description,
    severity,
    inspection_id=None,
    record_id=None,
    version=None,
):
    member = actor(company_id, "quality.inspect")
    company_lock(company_id)
    lot = scoped(Lot, company_id, lot_id)
    if severity not in {"low", "medium", "high", "critical"}:
        raise DomainError("Choose a supported severity.")
    inspection = scoped(Inspection, company_id, inspection_id) if inspection_id else None
    if inspection and inspection.lot_id != lot.id:
        raise DomainError("Inspection evidence belongs to another lot.")
    row = (
        scoped(Nonconformance, company_id, record_id, True)
        if record_id
        else Nonconformance(organization_id=company_id, owner_id=member.id)
    )
    expected(row, version)
    if record_id and (row.archived_at or row.status != "open"):
        raise DomainError("Resolved or archived quality issues cannot be edited.")
    row.reference, row.lot_id, row.description, row.severity = (
        text(reference, 80),
        lot.id,
        text(description),
        severity,
    )
    row.inspection_id = inspection.id if inspection else None
    db.session.add(row)
    return row


@mutation
def resolve_nonconformance(company_id, record_id, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    row = scoped(Nonconformance, company_id, record_id, True)
    expected(row, version)
    if db.session.scalar(
        select(QualityHold.id)
        .where(QualityHold.nonconformance_id == row.id, QualityHold.released_at.is_(None))
        .limit(1)
    ):
        raise DomainError("Independently review active holds before resolving this issue.")
    row.status = "resolved"
    return row


def place_hold_internal(
    company_id, member_id, lot_id, reason, case_id=None, nonconformance_id=None
):
    """Caller holds company guard and owns the transaction; used by case approval."""
    lot = scoped(Lot, company_id, lot_id, True)
    if nonconformance_id:
        issue = scoped(Nonconformance, company_id, nonconformance_id)
        if issue.lot_id != lot.id:
            raise DomainError("The quality issue concerns another lot.")
    row = QualityHold(
        organization_id=company_id,
        lot_id=lot.id,
        placed_by_id=member_id,
        reason=text(reason),
        case_id=case_id,
        nonconformance_id=nonconformance_id,
    )
    db.session.add(row)
    return row


@mutation
def place_hold(company_id, lot_id, reason, nonconformance_id=None):
    member = actor(company_id, "quality.hold")
    company_lock(company_id)
    return place_hold_internal(
        company_id, member.id, lot_id, reason, nonconformance_id=nonconformance_id
    )


@mutation
def review_hold(company_id, hold_id, decision, reason, version=None):
    member = actor(company_id, "quality.release")
    from app.services.mfa import require_recent_mfa

    require_recent_mfa(company_id)
    company_lock(company_id)
    hold = scoped(QualityHold, company_id, hold_id, True)
    scoped(Lot, company_id, hold.lot_id, True)
    expected(hold, version)
    if hold.released_at:
        raise DomainError("This hold has already been released.")
    if member.id == hold.placed_by_id:
        raise DomainError("A different reviewer must decide hold release.")
    if decision not in {"release", "retain"}:
        raise DomainError("Choose release or retain.")
    row = HoldReview(
        organization_id=company_id,
        hold_id=hold.id,
        reviewer_id=member.id,
        decision=decision,
        reason=text(reason),
    )
    db.session.add(row)
    if decision == "release":
        hold.released_at = now()
    return row


@mutation
def attach_document(company_id, document_id, inspection_id=None, nonconformance_id=None):
    actor(company_id, "quality.inspect")
    actor(company_id, "evidence.read")
    company_lock(company_id)
    if bool(inspection_id) == bool(nonconformance_id):
        raise DomainError("Choose exactly one quality evidence parent.")
    from app.models.evidence import Document

    document = scoped(Document, company_id, document_id)
    if document.scan_status != "clean" or document.state != "active" or document.archived_at:
        raise DomainError("Only available, scanned evidence can be attached.")
    if inspection_id:
        parent = scoped(Inspection, company_id, inspection_id, True)
        draft(parent)
        inspection_id = parent.id
    if nonconformance_id:
        parent = scoped(Nonconformance, company_id, nonconformance_id, True)
        if parent.status != "open" or parent.archived_at:
            raise DomainError("Only open quality issues accept evidence.")
        nonconformance_id = parent.id
    row = QualityDocument(
        organization_id=company_id,
        inspection_id=inspection_id,
        nonconformance_id=nonconformance_id,
        document_id=document.id,
    )
    db.session.add(row)
    return row


@mutation
def edit_inspection(company_id, inspection_id, reference, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    row = scoped(Inspection, company_id, inspection_id, True)
    expected(row, version)
    draft(row)
    row.reference = text(reference, 80)
    return row


@mutation
def remove_observation(company_id, inspection_id, result_id, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    inspection = scoped(Inspection, company_id, inspection_id, True)
    draft(inspection)
    row = scoped(InspectionResult, company_id, result_id, True)
    if row.inspection_id != inspection.id:
        raise DomainError("This observation belongs to another inspection.")
    expected(row, version)
    db.session.delete(row)
    inspection.updated_at = now()


@mutation
def remove_nonconformance(company_id, record_id, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    row = scoped(Nonconformance, company_id, record_id, True)
    expected(row, version)
    from app.models.recall import CaseSource

    referenced = (
        db.session.scalar(
            select(QualityHold.id).where(QualityHold.nonconformance_id == row.id).limit(1)
        )
        or db.session.scalar(
            select(CaseSource.id).where(CaseSource.nonconformance_id == row.id).limit(1)
        )
        or db.session.scalar(
            select(QualityDocument.id).where(QualityDocument.nonconformance_id == row.id).limit(1)
        )
    )
    if referenced:
        row.archived_at = now()
    else:
        db.session.delete(row)
    return row


@mutation
def detach_document(company_id, link_id, version=None):
    actor(company_id, "quality.inspect")
    company_lock(company_id)
    link = scoped(QualityDocument, company_id, link_id, True)
    expected(link, version)
    if link.inspection_id:
        draft(scoped(Inspection, company_id, link.inspection_id, True))
    else:
        parent = scoped(Nonconformance, company_id, link.nonconformance_id, True)
        if parent.status != "open" or parent.archived_at:
            raise DomainError("Only an open quality issue permits evidence changes.")
    db.session.delete(link)
