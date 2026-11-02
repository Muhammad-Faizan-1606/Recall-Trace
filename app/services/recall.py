"""Independent, revision-aware recall approval and verified resolution workflows."""

from sqlalchemy import func, select

from app.extensions import db
from app.models import ItemVariant, Membership, now
from app.models.master import Lot
from app.models.operations import ShipmentLine
from app.models.quality import Nonconformance, QualityHold
from app.models.recall import (
    CaseAffectedShipment,
    CaseComment,
    CaseDocument,
    CaseSource,
    CaseTask,
    RecallCase,
    RecoveryRecord,
    TraceResult,
    TraceRun,
)
from app.services.business import DomainError, actor, company_lock, quantity, scoped
from app.services.quality import expected, mutation, place_hold_internal, text


def current_trace(company_id, case_id, lock=False):
    from app.models import Organization

    query = (
        select(TraceRun)
        .where(
            TraceRun.organization_id == company_id,
            TraceRun.case_id == case_id,
            TraceRun.direction == "downstream",
        )
        .order_by(TraceRun.created_at.desc(), TraceRun.id.desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    run = db.session.scalar(query)
    company = db.session.get(Organization, company_id)
    if run is None or not run.is_complete or run.status != "complete":
        raise DomainError("Compute a complete downstream trace before this decision.")
    if run.trace_revision != company.trace_revision:
        raise DomainError(
            "Genealogy or dispatched exposure changed. Recompute the trace before proceeding."
        )
    case = db.session.get(RecallCase, case_id)
    if case.status == "approved" and (
        case.approved_at is None or run.completed_at is None or run.completed_at > case.approved_at
    ):
        raise DomainError(
            "This trace was not independently approved. Reopen and submit the revised scope for approval."
        )
    return run


def editable(case):
    if case.status not in {"draft", "rejected"}:
        raise DomainError("Only draft or rejected cases permit scope editing.")


@mutation
def save_case(company_id, reference, title, reason, severity, case_id=None, version=None):
    member = actor(company_id, "case.prepare")
    company_lock(company_id)
    if severity not in {"low", "medium", "high", "critical"}:
        raise DomainError("Choose a supported severity.")
    case = (
        scoped(RecallCase, company_id, case_id, True)
        if case_id
        else RecallCase(organization_id=company_id, owner_id=member.id)
    )
    if case_id:
        expected(case, version)
        editable(case)
    case.reference, case.title, case.reason, case.severity = (
        text(reference, 80),
        text(title, 160),
        text(reason),
        severity,
    )
    if case.status == "rejected":
        case.status = "draft"
    db.session.add(case)
    return case


@mutation
def source(company_id, case_id, lot_id, note, nonconformance_id=None):
    actor(company_id, "case.prepare")
    company = company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    editable(case)
    lot = scoped(Lot, company_id, lot_id)
    issue = scoped(Nonconformance, company_id, nonconformance_id) if nonconformance_id else None
    if issue and issue.lot_id != lot.id:
        raise DomainError("Source quality evidence belongs to another lot.")
    row = CaseSource(
        organization_id=company_id,
        case_id=case.id,
        lot_id=lot.id,
        source_note=text(note),
        nonconformance_id=issue.id if issue else None,
    )
    db.session.add(row)
    company.trace_revision += 1
    return row


@mutation
def remove_source(company_id, source_id, version=None):
    actor(company_id, "case.prepare")
    company = company_lock(company_id)
    row = scoped(CaseSource, company_id, source_id, True)
    editable(scoped(RecallCase, company_id, row.case_id, True))
    expected(row, version)
    db.session.delete(row)
    company.trace_revision += 1


@mutation
def submit(company_id, case_id, version=None):
    member = actor(company_id, "case.prepare")
    company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    expected(case, version)
    editable(case)
    if not db.session.scalar(select(CaseSource.id).where(CaseSource.case_id == case.id).limit(1)):
        raise DomainError("Add a source lot before submission.")
    case.status, case.submitted_at, case.submitted_by_id = "submitted", now(), member.id
    case.approver_id, case.approved_at = None, None
    return case


@mutation
def approve(company_id, case_id, version=None):
    member = actor(company_id, "case.approve")
    from app.services.mfa import require_recent_mfa

    require_recent_mfa(company_id)
    company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    expected(case, version)
    if case.status != "submitted":
        raise DomainError("Only submitted cases can be approved.")
    if case.submitted_by_id == member.id:
        raise DomainError("A different quality reviewer must approve this case.")
    run = current_trace(company_id, case.id, True)
    lot_ids = sorted(
        db.session.scalars(select(TraceResult.lot_id).where(TraceResult.trace_run_id == run.id)),
        key=str,
    )
    if not lot_ids:
        raise DomainError("The trace has no source evidence.")
    for lot_id in lot_ids:
        existing = db.session.scalar(
            select(QualityHold.id)
            .where(
                QualityHold.organization_id == company_id,
                QualityHold.case_id == case.id,
                QualityHold.lot_id == lot_id,
                QualityHold.released_at.is_(None),
            )
            .limit(1)
        )
        if not existing:
            place_hold_internal(
                company_id,
                member.id,
                lot_id,
                f"Approved recall {case.reference}: controlled investigation hold",
                case_id=case.id,
            )
    case.status, case.approver_id, case.approved_at = "approved", member.id, now()
    return case


@mutation
def reject(company_id, case_id, reason, version=None):
    member = actor(company_id, "case.approve")
    company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    expected(case, version)
    if case.status != "submitted" or member.id == case.submitted_by_id:
        raise DomainError("Only an independent reviewer may reject a submitted case.")
    case.status = "rejected"
    db.session.add(
        CaseComment(
            organization_id=company_id,
            case_id=case.id,
            author_id=member.id,
            body="Review rejected: " + text(reason),
        )
    )
    return case


@mutation
def task(
    company_id, case_id, title, description, assignee_id, mandatory=True, task_id=None, version=None
):
    actor(company_id, "case.prepare")
    company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    if case.status in {"closed", "cancelled"}:
        raise DomainError("Reopen this case before assigning work.")
    member = scoped(Membership, company_id, assignee_id)
    if member.status != "active" or member.archived_at or member.partner_id:
        raise DomainError("Choose an active internal member.")
    row = (
        scoped(CaseTask, company_id, task_id, True)
        if task_id
        else CaseTask(organization_id=company_id, case_id=case.id)
    )
    expected(row, version)
    if row.case_id != case.id or row.status not in {None, "open"}:
        raise DomainError("Only open tasks in this case can be edited.")
    if task_id and case.status not in {"draft", "rejected"} and row.mandatory and not mandatory:
        raise DomainError("Mandatory investigation work cannot be waived after submission.")
    row.title, row.description, row.assignee_id, row.mandatory = (
        text(title, 160),
        text(description),
        member.id,
        bool(mandatory),
    )
    db.session.add(row)
    return row


@mutation
def complete_task(company_id, task_id, note, verify=False, version=None):
    member = actor(company_id, "case.approve" if verify else "case.prepare")
    company_lock(company_id)
    row = scoped(CaseTask, company_id, task_id, True)
    case = scoped(RecallCase, company_id, row.case_id, True)
    expected(row, version)
    if case.status == "closed" or row.archived_at:
        raise DomainError("This task is no longer editable.")
    if verify:
        if row.status != "completed" or row.assignee_id == member.id:
            raise DomainError("A different reviewer must verify completed work.")
        row.status, row.verifier_id = "verified", member.id
    else:
        if row.status != "open" or row.assignee_id != member.id:
            raise DomainError("Only the assignee may complete an open task.")
        row.status = "completed"
    row.description = (
        (row.description or "") + "\n" + ("Verified: " if verify else "Completed: ") + text(note)
    )
    return row


@mutation
def comment(company_id, case_id, body, comment_id=None, version=None):
    member = actor(company_id, "case.prepare")
    company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    if case.status in {"closed", "cancelled"}:
        raise DomainError("This case no longer permits discussion.")
    row = (
        scoped(CaseComment, company_id, comment_id, True)
        if comment_id
        else CaseComment(organization_id=company_id, case_id=case.id, author_id=member.id)
    )
    if row.case_id != case.id or row.author_id != member.id:
        raise DomainError("Only the original author may amend this comment.")
    expected(row, version)
    if comment_id:
        # Amendments append a new attributed record; the original remains protected.
        row = CaseComment(
            organization_id=company_id,
            case_id=case.id,
            author_id=member.id,
            body=f"Amendment of comment {row.id}: " + text(body),
        )
    else:
        row.body = text(body)
    db.session.add(row)
    return row


@mutation
def attach_document(company_id, case_id, document_id):
    actor(company_id, "case.prepare")
    actor(company_id, "evidence.read")
    company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    if case.status in {"closed", "cancelled"}:
        raise DomainError("Reopen the case before adding evidence.")
    from app.models.evidence import Document

    document = scoped(Document, company_id, document_id)
    if document.scan_status != "clean" or document.state != "active" or document.archived_at:
        raise DomainError("Only available, scanned documents may be attached.")
    row = CaseDocument(organization_id=company_id, case_id=case.id, document_id=document.id)
    db.session.add(row)
    return row


@mutation
def record_recovery(
    company_id,
    case_id,
    shipment_line_id,
    amount,
    disposition,
    evidence_note,
    evidence_reference,
    notice_id=None,
):
    member = actor(company_id, "recovery.record")
    company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    if case.status != "approved":
        raise DomainError("Recovery requires an approved open case.")
    run = current_trace(company_id, case.id, True)
    line = scoped(ShipmentLine, company_id, shipment_line_id, True)
    affected = db.session.scalar(
        select(CaseAffectedShipment)
        .where(
            CaseAffectedShipment.case_id == case.id,
            CaseAffectedShipment.trace_run_id == run.id,
            CaseAffectedShipment.shipment_line_id == line.id,
        )
        .with_for_update()
    )
    if not affected:
        raise DomainError("This shipment line is outside the approved trace scope.")
    if disposition not in {"returned", "destroyed", "other_resolved"}:
        raise DomainError("Choose a supported verified disposition.")
    lot = scoped(Lot, company_id, line.lot_id)
    variant = scoped(ItemVariant, company_id, lot.variant_id)
    from app.models import UnitsOfMeasure

    unit = scoped(UnitsOfMeasure, company_id, variant.base_unit_id)
    amount = quantity(amount, unit.decimal_places)
    reference = text(evidence_reference, 100)
    note = text(evidence_note)
    old = db.session.scalar(
        select(RecoveryRecord).where(
            RecoveryRecord.organization_id == company_id,
            RecoveryRecord.evidence_reference == reference,
        )
    )
    if old:
        if (
            old.case_id,
            old.shipment_line_id,
            old.quantity,
            old.disposition,
            old.evidence_note,
        ) != (case.id, line.id, amount, disposition, note):
            raise DomainError("This evidence reference already identifies a different recovery.")
        return old
    total = db.session.scalar(
        select(func.coalesce(func.sum(RecoveryRecord.quantity), 0)).where(
            RecoveryRecord.organization_id == company_id, RecoveryRecord.shipment_line_id == line.id
        )
    )
    if total + amount > line.quantity:
        raise DomainError("Cumulative verified dispositions cannot exceed the dispatched quantity.")
    if notice_id:
        from app.models.evidence import RecallNotice

        notice = scoped(RecallNotice, company_id, notice_id)
        if notice.case_id != case.id:
            raise DomainError("The notice belongs to another case.")
    row = RecoveryRecord(
        organization_id=company_id,
        case_id=case.id,
        shipment_line_id=line.id,
        quantity=amount,
        disposition=disposition,
        evidence_note=note,
        evidence_reference=reference,
        verified_by_id=member.id,
        notice_id=notice_id,
    )
    db.session.add(row)
    # Each snapshot projects immutable evidence belonging to the same case and line.
    for exposure in db.session.scalars(
        select(CaseAffectedShipment)
        .where(
            CaseAffectedShipment.case_id == case.id,
            CaseAffectedShipment.shipment_line_id == line.id,
        )
        .with_for_update()
    ):
        exposure.quantity_resolved += amount
        if disposition == "returned":
            exposure.quantity_recovered += amount
    return row


@mutation
def close(company_id, case_id, note, acknowledgement_exception="", version=None):
    member = actor(company_id, "case.close")
    from app.services.mfa import require_recent_mfa

    require_recent_mfa(company_id)
    company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    expected(case, version)
    if case.status != "approved":
        raise DomainError("Only approved cases can close.")
    run = current_trace(company_id, case.id, True)
    tasks = db.session.scalars(
        select(CaseTask).where(CaseTask.case_id == case.id, CaseTask.mandatory.is_(True))
    ).all()
    if any(row.status != "verified" or row.verifier_id is None for row in tasks):
        raise DomainError("Verify every mandatory task before closure.")
    exposures = db.session.scalars(
        select(CaseAffectedShipment).where(CaseAffectedShipment.trace_run_id == run.id)
    ).all()
    if any(row.quantity_resolved != row.quantity_dispatched for row in exposures):
        raise DomainError(
            "Record verified dispositions for all dispatched exposure before closure."
        )
    from app.models.evidence import NoticeAcknowledgement, RecallNotice

    notices = db.session.scalars(
        select(RecallNotice).where(
            RecallNotice.case_id == case.id, RecallNotice.status != "cancelled"
        )
    ).all()
    from flask import current_app

    permitted_states = {"sent"}
    if current_app.config.get("APP_ENV") != "production":
        permitted_states.add("local_written")
    if any(notice.status not in permitted_states for notice in notices):
        raise DomainError("Resolve pending, failed or ambiguous notice delivery before closure.")
    unacknowledged = [
        row
        for row in notices
        if not db.session.scalar(
            select(NoticeAcknowledgement.id)
            .where(NoticeAcknowledgement.notice_id == row.id)
            .limit(1)
        )
    ]
    if (unacknowledged or (exposures and not notices)) and len(
        acknowledgement_exception.strip()
    ) < 20:
        raise DomainError(
            "Review outstanding acknowledgements and record an explicit exception reason (20+ characters)."
        )
    message = "Closure review: " + text(note)
    if acknowledgement_exception.strip():
        message += "\nAcknowledgement exception reviewed: " + text(acknowledgement_exception)
    db.session.add(
        CaseComment(organization_id=company_id, case_id=case.id, author_id=member.id, body=message)
    )
    case.status, case.closed_at = "closed", now()
    return case


@mutation
def reopen(company_id, case_id, reason, version=None):
    member = actor(company_id, "case.prepare")
    from app.services.mfa import require_recent_mfa

    require_recent_mfa(company_id)
    company = company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    expected(case, version)
    if case.status not in {"closed", "approved"}:
        raise DomainError("Only approved or closed cases require reopening for a scope revision.")
    case.status, case.closed_at, case.approved_at, case.approver_id = "draft", None, None, None
    company.trace_revision += 1
    db.session.add(
        CaseComment(
            organization_id=company_id,
            case_id=case.id,
            author_id=member.id,
            body="Reopened for new scope review: " + text(reason),
        )
    )
    return case


@mutation
def cancel_draft(company_id, case_id, reason, version=None):
    member = actor(company_id, "case.prepare")
    company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    editable(case)
    expected(case, version)
    case.status = "cancelled"
    db.session.add(
        CaseComment(
            organization_id=company_id,
            case_id=case.id,
            author_id=member.id,
            body="Cancelled before approval: " + text(reason),
        )
    )
    return case


@mutation
def remove_task(company_id, task_id, version=None):
    actor(company_id, "case.prepare")
    company_lock(company_id)
    row = scoped(CaseTask, company_id, task_id, True)
    case = scoped(RecallCase, company_id, row.case_id, True)
    expected(row, version)
    if case.status in {"closed", "cancelled"}:
        raise DomainError("This case no longer permits task changes.")
    if row.status == "open":
        editable(case)
        db.session.delete(row)
    else:
        # Archiving never removes mandatory verification from the closure gate.
        row.archived_at = now()
    return row


@mutation
def detach_document(company_id, case_id, link_id, version=None):
    actor(company_id, "case.prepare")
    company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    editable(case)
    link = scoped(CaseDocument, company_id, link_id, True)
    expected(link, version)
    if link.case_id != case.id:
        raise DomainError("This document link belongs to another case.")
    db.session.delete(link)
