"""Recipient-scoped, independently approved recall communications."""

import requests
from flask import abort, current_app
from flask_login import current_user
from sqlalchemy import func, select

from app.extensions import db
from app.models import Membership, Organization, now
from app.models.evidence import JobOutbox, NoticeAcknowledgement, NoticeDelivery, RecallNotice
from app.models.master import Partner, PartnerContact
from app.models.operations import SalesOrder, Shipment, ShipmentLine
from app.models.recall import CaseAffectedShipment, RecallCase
from app.policies import allowed
from app.services.audit import record as audit
from app.services.business import DomainError, actor, company_lock, scoped
from app.services.evidence import notify


def _text(value, maximum, label, single_line=False):
    if not isinstance(value, str):
        raise DomainError(f"Enter a valid {label}.")
    value = value.strip()
    permitted = "" if single_line else "\t\r\n"
    if not 1 <= len(value) <= maximum or any(
        ord(character) < 32 and character not in permitted for character in value
    ):
        raise DomainError(f"Enter a bounded {label} without invalid control characters.")
    return value


def viewer(company_id):
    if not current_user.is_authenticated:
        abort(401)
    member = db.session.scalar(
        select(Membership)
        .join(Organization)
        .where(
            Membership.organization_id == company_id,
            Membership.user_id == current_user.id,
            Membership.status == "active",
            Membership.archived_at.is_(None),
            Organization.status == "active",
            Organization.archived_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    if member is None:
        abort(404)
    if member.partner_id:
        from app.services.access import permissions_for

        if "notice.read" not in permissions_for(member, allow_partner=True):
            abort(403)
        partner = scoped(Partner, company_id, member.partner_id)
        if partner.archived_at or partner.status != "active":
            abort(404)
    elif not allowed(company_id, "catalog.read"):
        abort(403)
    return member


def readable(company_id, notice_id):
    member = viewer(company_id)
    notice = scoped(RecallNotice, company_id, notice_id)
    if member.partner_id:
        contact = scoped(PartnerContact, company_id, notice.contact_id)
        if contact.partner_id != member.partner_id or notice.status not in {
            "approved",
            "queued",
            "sent",
            "local_written",
            "ambiguous",
        }:
            abort(404)
    return notice


def current_scope(company_id, notice=None, case_id=None, contact_id=None):
    """Return current approved case, its trace and recipient's affected lines."""
    from app.services.recall import current_trace

    case = scoped(RecallCase, company_id, notice.case_id if notice else case_id)
    if case.status != "approved":
        raise DomainError("Notices require an approved, open recall case.")
    trace = current_trace(company_id, case.id)
    contact = scoped(PartnerContact, company_id, notice.contact_id if notice else contact_id)
    partner = scoped(Partner, company_id, contact.partner_id)
    if (
        contact.archived_at
        or partner.archived_at
        or partner.status != "active"
        or not contact.email
    ):
        raise DomainError("Choose an active recipient contact with an email address.")
    if notice and (
        notice.trace_run_id != trace.id
        or notice.trace_revision != trace.trace_revision
        or notice.recipient_email != contact.email
    ):
        raise DomainError("Notice scope or recipient changed; prepare a reviewed new revision.")
    lines = db.session.execute(
        select(CaseAffectedShipment, ShipmentLine, Shipment)
        .join(ShipmentLine, ShipmentLine.id == CaseAffectedShipment.shipment_line_id)
        .join(Shipment, Shipment.id == ShipmentLine.shipment_id)
        .join(SalesOrder, SalesOrder.id == Shipment.sales_order_id)
        .where(
            CaseAffectedShipment.organization_id == company_id,
            CaseAffectedShipment.trace_run_id == trace.id,
            SalesOrder.customer_id == contact.partner_id,
        )
        .order_by(Shipment.reference, ShipmentLine.id)
    ).all()
    if not lines:
        raise DomainError(
            "Recipient is not a customer of any affected shipment in the current trace."
        )
    return case, trace, contact, lines


def create_notice(company_id, case_id, contact_id, subject=None, body=None):
    member = actor(company_id, "notice.prepare")
    company_lock(company_id)
    case, trace, contact, lines = current_scope(company_id, case_id=case_id, contact_id=contact_id)
    subject = _text(subject or f"Recall {case.reference}: {case.title}", 160, "subject", True)
    if body is None:
        # Do not combine unlike SKUs; each line preserves its own lot/base-unit quantity.
        exposure = "\n".join(
            f"Shipment {shipment.reference}; lot {line.lot_id}; potentially affected quantity {affected.quantity_dispatched} in this SKU's base unit."
            for affected, line, shipment in lines
        )
        body = f"{case.title}\n\n{case.reason}\n\nYour potentially affected shipments:\n{exposure}\n\nStop use and contact the sender. Acknowledgement does not establish physical recovery."
    body = _text(body, 20000, "notice body")
    revision = (
        db.session.scalar(
            select(func.max(RecallNotice.revision)).where(
                RecallNotice.organization_id == company_id,
                RecallNotice.case_id == case.id,
                RecallNotice.contact_id == contact.id,
            )
        )
        or 0
    ) + 1
    notice = RecallNotice(
        organization_id=company_id,
        case_id=case.id,
        contact_id=contact.id,
        trace_run_id=trace.id,
        trace_revision=trace.trace_revision,
        recipient_email=contact.email,
        revision=revision,
        subject=subject,
        body=body,
        status="draft",
        created_by_id=member.id,
    )
    db.session.add(notice)
    db.session.flush()
    audit(
        company_id,
        "notice.prepare",
        "recall_notice",
        notice.id,
        {"case_id": str(case.id), "version": revision},
    )
    db.session.commit()
    return notice


def edit_notice(company_id, notice_id, subject, body, version):
    actor(company_id, "notice.prepare")
    company_lock(company_id)
    notice = scoped(RecallNotice, company_id, notice_id, lock=True)
    if notice.status != "draft" or notice.version != version:
        raise DomainError("Only an unchanged draft notice can be edited.")
    current_scope(company_id, notice=notice)
    clean_subject = _text(subject, 160, "subject", True)
    clean_body = _text(body, 20000, "notice body")
    notice.subject, notice.body = clean_subject, clean_body
    audit(company_id, "notice.edit", "recall_notice", notice.id, {"version": notice.version})
    db.session.commit()
    return notice


def delete_notice(company_id, notice_id, version):
    actor(company_id, "notice.prepare")
    company_lock(company_id)
    notice = scoped(RecallNotice, company_id, notice_id, lock=True)
    if notice.status != "draft" or notice.version != version:
        raise DomainError("Only an unchanged draft notice can be deleted.")
    audit(company_id, "notice.delete_draft", "recall_notice", notice.id)
    db.session.delete(notice)
    db.session.commit()


def approve_notice(company_id, notice_id, version):
    member = actor(company_id, "notice.approve")
    company_lock(company_id)
    notice = scoped(RecallNotice, company_id, notice_id, lock=True)
    if notice.status != "draft" or notice.version != version:
        raise DomainError("Only an unchanged draft notice can be approved.")
    if notice.created_by_id == member.id:
        raise DomainError("A different eligible member must approve this notice.")
    from app.services.mfa import require_recent_mfa

    require_recent_mfa(company_id)
    current_scope(company_id, notice=notice)
    notice.status, notice.approved_by_id, notice.approved_at = "approved", member.id, now()
    audit(
        company_id,
        "notice.approve",
        "recall_notice",
        notice.id,
        {"trace_revision": notice.trace_revision},
    )
    notify(
        company_id,
        notice.created_by_id,
        "notice",
        {"message": "A recall notice was approved.", "notice_id": str(notice.id)},
    )
    db.session.commit()
    return notice


def enqueue_notice(company_id, notice_id):
    member = actor(company_id, "notice.prepare")
    company_lock(company_id)
    notice = scoped(RecallNotice, company_id, notice_id, lock=True)
    current_scope(company_id, notice=notice)
    if notice.status not in {"approved", "queued", "sent", "local_written"}:
        raise DomainError("Only an approved notice may enter delivery.")
    key = f"notice:{notice.id}:{notice.revision}"
    job = db.session.scalar(
        select(JobOutbox).where(
            JobOutbox.organization_id == company_id, JobOutbox.deduplication_key == key
        )
    )
    if job:
        return job
    delivery = NoticeDelivery(
        organization_id=company_id,
        notice_id=notice.id,
        idempotency_key=key,
        attempt=1,
        status="pending",
    )
    db.session.add(delivery)
    db.session.flush()
    job = JobOutbox(
        organization_id=company_id,
        created_by_id=member.id,
        kind="notice.send",
        payload={"notice_id": str(notice.id), "delivery_id": str(delivery.id)},
        deduplication_key=key,
        status="pending",
        attempts=0,
        available_at=now(),
    )
    db.session.add(job)
    notice.status = "queued"
    audit(company_id, "notice.queue", "recall_notice", notice.id, {"delivery_id": str(delivery.id)})
    db.session.commit()
    return job


def acknowledge(company_id, notice_id, method, safe_note=""):
    member = viewer(company_id)
    company_lock(company_id)
    notice = readable(company_id, notice_id)
    if not member.partner_id and not allowed(company_id, "notice.acknowledge"):
        abort(403)
    if (
        method not in {"email", "phone", "written", "portal"}
        or not isinstance(safe_note, str)
        or len(safe_note) > 2000
        or any(ord(c) < 32 and c not in "\t\r\n" for c in safe_note)
    ):
        raise DomainError(
            "Select an acknowledgement method and a note of at most 2,000 characters."
        )
    if member.partner_id and method != "portal":
        raise DomainError("Partner users can acknowledge only their own portal receipt.")
    if member.partner_id:
        from app.services.access import permissions_for

        if "notice.acknowledge" not in permissions_for(member, allow_partner=True):
            abort(403)
    if notice.status not in {"sent", "local_written"}:
        raise DomainError("Acknowledgement requires a delivered notice revision.")
    previous = db.session.scalar(
        select(NoticeAcknowledgement).where(
            NoticeAcknowledgement.organization_id == company_id,
            NoticeAcknowledgement.notice_id == notice.id,
        )
    )
    if previous:
        return previous
    row = NoticeAcknowledgement(
        organization_id=company_id,
        notice_id=notice.id,
        recorded_by_id=member.id,
        method=method,
        safe_note=safe_note,
    )
    db.session.add(row)
    db.session.commit()
    return row


def send_message(recipient, subject, body, idempotency_key):
    """Return safe outcome/reference/error; timeout after sending is ambiguous.

    Local delivery explicitly reports local_written, never external delivery.
    No retry occurs here. A provider idempotency key cannot prove exactly-once mail.
    """
    mode = current_app.config.get("MAIL_MODE", "unconfigured")
    if mode == "local":
        from app.services.development_mail import deliver_development_message

        if deliver_development_message(recipient, subject, body):
            return "local_written", None, None
        return "failed", None, "local_mail_unavailable"
    if mode != "resend":
        return "failed", None, "mail_unconfigured"
    key, sender = current_app.config.get("MAIL_API_KEY"), current_app.config.get("MAIL_FROM")
    if not key or not sender:
        return "failed", None, "mail_unconfigured"
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}", "Idempotency-Key": idempotency_key},
            json={"from": sender, "to": [recipient], "subject": subject, "text": body},
            timeout=(5, 20),
            allow_redirects=False,
        )
    except requests.ConnectTimeout:
        return "failed", None, "provider_connect_timeout"
    except requests.RequestException:
        return "ambiguous", None, "provider_transport_ambiguous"
    if response.status_code == 429:
        return "failed", None, "provider_rate_limited"
    if response.status_code >= 500:
        return "ambiguous", None, "provider_response_ambiguous"
    if 300 <= response.status_code < 400:
        return "ambiguous", None, "provider_unexpected_redirect"
    if not response.ok:
        return "failed", None, "provider_rejected"
    try:
        payload = response.json()
        reference = payload.get("id") if isinstance(payload, dict) else None
        if (
            not isinstance(reference, str)
            or not reference.strip()
            or len(reference) > 160
            or not reference.isprintable()
        ):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return "ambiguous", None, "provider_receipt_missing"
    return "sent", reference, None


def deliver_job(job):
    """Flush-only; called under company/job locks, rechecks current authority."""
    from app.services.access import permissions_for

    requester = scoped(Membership, job.organization_id, job.created_by_id)
    if "notice.prepare" not in permissions_for(requester):
        raise DomainError("Requester no longer has notice preparation permission.")
    notice = scoped(RecallNotice, job.organization_id, job.payload["notice_id"], lock=True)
    delivery = scoped(NoticeDelivery, job.organization_id, job.payload["delivery_id"], lock=True)
    if (
        delivery.notice_id != notice.id
        or notice.status != "queued"
        or delivery.status not in {"pending", "failed"}
    ):
        raise DomainError("Delivery state cannot be executed.")
    approver = scoped(Membership, job.organization_id, notice.approved_by_id)
    creator = scoped(Membership, job.organization_id, notice.created_by_id)
    if "notice.approve" not in permissions_for(approver) or "notice.prepare" not in permissions_for(
        creator
    ):
        raise DomainError("A notice author's or approver's current authority was revoked.")
    current_scope(job.organization_id, notice=notice)
    status, reference, error = send_message(
        notice.recipient_email, notice.subject, notice.body, delivery.idempotency_key
    )
    delivery.status, delivery.provider_reference, delivery.error_code = status, reference, error
    if status in {"sent", "local_written"}:
        delivery.sent_at = now()
        notice.status = status
        job.status = "completed"
        notify(
            job.organization_id,
            creator.id,
            "notice",
            {
                "message": "Notice delivery attempt completed; inspect its delivery outcome.",
                "notice_id": str(notice.id),
            },
        )
    elif status == "ambiguous":
        notice.status = "ambiguous"
        job.status = "ambiguous"
    else:
        job.status = "failed"
    job.error_code = error
    return status


def reconcile_delivery(company_id, delivery_id, outcome, document_id, provider_reference=None):
    """Resolve uncertainty only from independently reviewed private evidence.

    This action records an operator finding; it does not perform a network send.
    A confirmed non-send may subsequently use the ordinary bounded retry path.
    """
    member = actor(company_id, "notice.approve")
    actor(company_id, "evidence.read")
    company_lock(company_id)
    from app.models.evidence import Document
    from app.models.recall import CaseDocument
    from app.services.mfa import require_recent_mfa

    require_recent_mfa(company_id)
    delivery = scoped(NoticeDelivery, company_id, delivery_id, lock=True)
    notice = scoped(RecallNotice, company_id, delivery.notice_id, lock=True)
    job = db.session.scalar(
        select(JobOutbox)
        .where(
            JobOutbox.organization_id == company_id,
            JobOutbox.deduplication_key == f"notice:{notice.id}:{notice.revision}",
        )
        .with_for_update()
    )
    if delivery.status != "ambiguous" or not job or job.status != "ambiguous":
        raise DomainError("Only an ambiguous delivery can be reconciled.")
    if member.id == notice.created_by_id:
        raise DomainError("A different eligible member must reconcile this notice.")
    document = scoped(Document, company_id, document_id)
    if document.state != "active" or document.scan_status != "clean" or document.archived_at:
        raise DomainError("Reconciliation requires clean private evidence.")
    if outcome not in {"sent", "not_sent"}:
        raise DomainError("Record provider-confirmed sent or provider-confirmed not sent.")
    if outcome == "sent" and (
        not isinstance(provider_reference, str) or not 1 <= len(provider_reference) <= 160
    ):
        raise DomainError("A confirmed send requires a provider receipt reference.")
    if outcome == "sent":
        provider_reference = _text(provider_reference, 160, "provider receipt reference", True)
    link = db.session.scalar(
        select(CaseDocument.id).where(
            CaseDocument.organization_id == company_id,
            CaseDocument.case_id == notice.case_id,
            CaseDocument.document_id == document.id,
        )
    )
    if not link:
        db.session.add(
            CaseDocument(
                organization_id=company_id, case_id=notice.case_id, document_id=document.id
            )
        )
    delivery.error_code = f"operator_confirmed_{outcome}"
    if outcome == "sent":
        delivery.status, notice.status, job.status = "sent", "sent", "completed"
        delivery.provider_reference = provider_reference
        delivery.sent_at = now()
    else:
        delivery.status, notice.status, job.status = "failed", "queued", "failed"
    job.error_code = delivery.error_code
    audit(
        company_id,
        "notice.reconcile",
        "notice_delivery",
        delivery.id,
        {"result": outcome, "document_id": str(document.id)},
    )
    db.session.commit()
    return delivery


def withdraw_notice(company_id, notice_id, reason, version):
    """Withdraw a never-delivered revision without rewriting its reviewed content."""
    member = actor(company_id, "notice.approve")
    from app.models.recall import CaseComment
    from app.services.mfa import require_recent_mfa

    require_recent_mfa(company_id)
    notice = scoped(RecallNotice, company_id, notice_id, lock=True)
    if notice.version != version or notice.status not in {"draft", "approved", "queued"}:
        raise DomainError("Only an unchanged, never-delivered notice may be withdrawn.")
    if notice.created_by_id == member.id:
        raise DomainError("A different eligible member must review this withdrawal.")
    reason = _text(reason, 2000, "withdrawal review reason")
    if len(reason) < 20:
        raise DomainError("Record a withdrawal review reason of at least 20 characters.")
    deliveries = db.session.scalars(
        select(NoticeDelivery)
        .where(NoticeDelivery.organization_id == company_id, NoticeDelivery.notice_id == notice.id)
        .order_by(NoticeDelivery.attempt)
        .with_for_update()
    ).all()
    if any(
        row.status not in {"pending", "failed"}
        or row.sent_at is not None
        or row.provider_reference is not None
        for row in deliveries
    ):
        raise DomainError("Reconcile uncertain attempts; delivered notices cannot be withdrawn.")
    job = db.session.scalar(
        select(JobOutbox)
        .where(
            JobOutbox.organization_id == company_id,
            JobOutbox.deduplication_key == f"notice:{notice.id}:{notice.revision}",
        )
        .with_for_update()
    )
    if job and (
        job.status not in {"pending", "failed"}
        or (job.status == "pending" and job.claimed_at is not None)
    ):
        raise DomainError("A claimed or uncertain delivery cannot be withdrawn.")
    if job:
        job.status, job.error_code = "cancelled", "operator_withdrawn_before_delivery"
    for delivery in deliveries:
        if delivery.status == "pending":
            delivery.status, delivery.error_code = "cancelled", "withdrawn_before_delivery"
    notice.status = "cancelled"
    db.session.add(
        CaseComment(
            organization_id=company_id,
            case_id=notice.case_id,
            author_id=member.id,
            body=f"Notice revision {notice.revision} withdrawn before delivery. Review reason: {reason}",
        )
    )
    audit(
        company_id,
        "notice.withdraw",
        "recall_notice",
        notice.id,
        {"status": "cancelled", "reason_code": "reviewed_before_delivery"},
    )
    db.session.commit()
    return notice
