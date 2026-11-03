"""Adversarial private-data/provider/worker regressions; never contact external services."""

import csv
import io
import json
from datetime import timedelta
from pathlib import Path

import pytest
import requests
from conftest import csrf, login
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_evidence import PDF
from test_evidence import evidence_actor as evidence_actor_fixture
from test_notices import approved, draft
from test_notices import notice_case as notice_case_fixture
from test_quality import grant
from werkzeug.exceptions import Forbidden, HTTPException

from app.extensions import db
from app.models import (
    AuthSession,
    Membership,
    MembershipRole,
    Organization,
    Permission,
    RolePermission,
    now,
)
from app.models.evidence import Document, ImportJob, JobOutbox, NoticeDelivery
from app.models.recall import CaseAffectedShipment
from app.models.security import AuditEvent
from app.services import evidence, jobs, notices, recall
from app.services.auth import digest
from app.services.business import DomainError

evidence_actor = evidence_actor_fixture
notice_case = notice_case_fixture


def response(status=200, payload=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    result.headers["Content-Type"] = "application/json"
    result.url = "https://private-provider.example.test/endpoint"
    if 300 <= status < 400:
        result.headers["Location"] = "https://untrusted-redirect.example.test/collect"
    return result


@pytest.mark.parametrize(
    "data",
    [
        b"x" * (csv.field_size_limit() + 1) + b",name,kind\n",
        b'"unterminated,name,kind\n',
        b'code,name,kind\nX,"unterminated,component\n',
        b"code,name,kind\nX,Null\x00name,component\n",
    ],
)
def test_malformed_csv_is_a_domain_rejection(data):
    with pytest.raises(DomainError):
        evidence.parse_items_csv(data)


def test_invalid_csv_header_returns_safe_http_failure_without_import(
    client, records, evidence_actor
):
    company_id = records["companies"]["aurora"]
    login(client, "owner@aurora.test")
    base = f"/companies/{company_id}"
    token = csrf(client.get(base + "/evidence"))
    data = b"x" * (csv.field_size_limit() + 1) + b",name,kind\n"
    result = client.post(
        base + "/imports/items",
        data={
            "csrf_token": token,
            "identifier": "malformed_header_repro_1234",
            "file": (io.BytesIO(data), "items.csv"),
        },
    )
    assert result.status_code == 409
    assert "CSV syntax is invalid" in result.text
    assert db.session.scalar(select(ImportJob.id)) is None


@pytest.mark.parametrize("payload", [None, [], "clean", {"status": "unknown"}])
def test_malformed_scanner_json_fails_closed(app, monkeypatch, payload):
    monkeypatch.setitem(app.config, "SCANNER_ENDPOINT", "https://scanner.example.test/scan")
    monkeypatch.setattr(
        evidence.requests, "post", lambda *args, **kwargs: response(payload=payload)
    )
    assert evidence.scan_bytes(PDF) == "unavailable"


def test_scanner_redirect_never_follows_private_payload(app, monkeypatch):
    monkeypatch.setitem(app.config, "SCANNER_ENDPOINT", "https://scanner.example.test/scan")
    calls = []

    def redirect(*args, **kwargs):
        calls.append(kwargs)
        return response(307, {"status": "clean"})

    monkeypatch.setattr(evidence.requests, "post", redirect)
    assert evidence.scan_bytes(PDF) == "unavailable"
    assert len(calls) == 1 and calls[0]["allow_redirects"] is False


@pytest.mark.parametrize("status,payload", [(302, {"public": False}), (200, None), (200, [])])
def test_bucket_redirect_or_malformed_metadata_never_authorizes_storage(
    app, monkeypatch, status, payload
):
    monkeypatch.setitem(app.config, "SUPABASE_URL", "https://private-provider.example.test")
    monkeypatch.setitem(app.config, "SUPABASE_STORAGE_BUCKET", "private")
    monkeypatch.setitem(app.config, "SUPABASE_SERVICE_KEY", "test-only-placeholder")
    calls = []

    def provider(*args, **kwargs):
        calls.append(kwargs)
        return response(status, payload)

    monkeypatch.setattr(evidence.requests, "get", provider)
    with pytest.raises(DomainError, match="private"):
        evidence._storage_url("private-key")
    assert len(calls) == 1 and calls[0]["allow_redirects"] is False


@pytest.mark.parametrize(
    "payload", [None, [], {"id": None}, {"id": 3}, {"id": ""}, {"id": "bad\x00receipt"}]
)
def test_mail_provider_requires_actual_receipt_string(app, monkeypatch, payload):
    monkeypatch.setitem(app.config, "MAIL_MODE", "resend")
    monkeypatch.setitem(app.config, "MAIL_API_KEY", "not-a-real-secret")
    monkeypatch.setitem(app.config, "MAIL_FROM", "sender@example.test")
    monkeypatch.setattr(notices.requests, "post", lambda *args, **kwargs: response(payload=payload))
    assert notices.send_message("recipient@example.test", "Subject", "Body", "test-key") == (
        "ambiguous",
        None,
        "provider_receipt_missing",
    )


def test_mail_redirect_is_ambiguous_and_never_forwards_body(app, monkeypatch):
    monkeypatch.setitem(app.config, "MAIL_MODE", "resend")
    monkeypatch.setitem(app.config, "MAIL_API_KEY", "not-a-real-secret")
    monkeypatch.setitem(app.config, "MAIL_FROM", "sender@example.test")
    calls = []

    def redirect(*args, **kwargs):
        calls.append(kwargs)
        return response(307, {"id": "unreviewed-redirect-receipt"})

    monkeypatch.setattr(notices.requests, "post", redirect)
    assert notices.send_message("recipient@example.test", "Subject", "Body", "test-key") == (
        "ambiguous",
        None,
        "provider_unexpected_redirect",
    )
    assert len(calls) == 1 and calls[0]["allow_redirects"] is False


@pytest.mark.parametrize("field", ["subject", "body"])
def test_invalid_notice_edit_keeps_all_business_fields_unchanged(
    notice_case, evidence_actor, field
):
    s = notice_case
    notice = draft(s, evidence_actor)
    original = (notice.subject, notice.body)
    values = {"subject": "A changed subject", "body": "Changed instructions"}
    values[field] += "\x00"
    with evidence_actor("catalog-editor@aurora.test"):
        with pytest.raises(DomainError, match="control"):
            notices.edit_notice(
                s["company"], notice.id, values["subject"], values["body"], notice.version
            )
        # Even a caller that subsequently commits cannot persist a partial invalid edit.
        db.session.commit()
        db.session.refresh(notice)
        assert (notice.subject, notice.body) == original


def test_reconciliation_requires_evidence_read_and_hides_filenames(
    notice_case, evidence_actor, client, monkeypatch
):
    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        notices.enqueue_notice(s["company"], notice.id)
    monkeypatch.setattr(notices, "send_message", lambda *args: ("ambiguous", None, "test_timeout"))
    assert jobs.run_one() == "ambiguous"
    delivery = db.session.scalar(
        select(NoticeDelivery).where(NoticeDelivery.notice_id == notice.id)
    )
    monkeypatch.setattr(evidence, "scan_bytes", lambda data: "clean")
    with evidence_actor(mfa=True) as user:
        document = evidence.upload(s["company"], "confidential-review-finding.pdf", io.BytesIO(PDF))
        member_id = db.session.scalar(
            select(Membership.id).where(
                Membership.organization_id == s["company"], Membership.user_id == user.id
            )
        )
        role_id = db.session.scalar(
            select(MembershipRole.role_id).where(
                MembershipRole.organization_id == s["company"],
                MembershipRole.membership_id == member_id,
            )
        )
        permission_id = db.session.scalar(
            select(Permission.id).where(Permission.code == "evidence.read")
        )
        db.session.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.permission_id == permission_id
            )
        )
        db.session.commit()
        with pytest.raises(Forbidden):
            notices.reconcile_delivery(s["company"], delivery.id, "not_sent", document.id)
    login(client, "owner@aurora.test")
    with client.session_transaction() as browser_session:
        token_digest = digest(browser_session["auth_ref"])
    auth = db.session.scalar(select(AuthSession).where(AuthSession.token_digest == token_digest))
    auth.last_mfa_at = now()
    db.session.commit()
    result = client.get(f"/companies/{s['company']}/notices/{notice.id}")
    assert result.status_code == 200
    assert "confidential-review-finding.pdf" not in result.text
    assert "Record independent reconciliation" not in result.text


@pytest.mark.parametrize(
    "payload", [{}, [], {"delivery_id": "not-a-uuid"}, {"notice_id": None, "delivery_id": None}]
)
def test_malformed_outbox_intent_does_not_poison_next_work(
    notice_case, evidence_actor, monkeypatch, payload
):
    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        valid = notices.enqueue_notice(s["company"], notice.id)
        bad = JobOutbox(
            organization_id=s["company"],
            kind="notice.send",
            payload=payload,
            deduplication_key="corrupt-intent-fixture",
            status="pending",
            attempts=0,
            available_at=now() - timedelta(minutes=1),
        )
        db.session.add(bad)
        db.session.commit()
    monkeypatch.setattr(notices, "send_message", lambda *args: ("local_written", None, None))
    assert jobs.run_one() == "failed"
    assert db.session.get(JobOutbox, bad.id).error_code == "execution_revalidation_failed"
    assert jobs.run_one() == "completed"
    assert db.session.get(JobOutbox, valid.id).status == "completed"
    assert notice.status == "local_written"


def test_corrupt_abandoned_intent_is_ambiguous_without_worker_crash(notice_case, evidence_actor):
    s = notice_case
    bad = JobOutbox(
        organization_id=s["company"],
        kind="notice.send",
        payload={},
        deduplication_key="corrupt-abandoned-fixture",
        status="processing",
        attempts=1,
        available_at=now(),
        claimed_at=now() - timedelta(minutes=6),
    )
    db.session.add(bad)
    db.session.commit()
    assert jobs.recover_abandoned() == 1
    assert db.session.get(JobOutbox, bad.id).status == "ambiguous"


@pytest.mark.parametrize("operation", ["upload", "rescan"])
@pytest.mark.parametrize("revoke", [False, True])
def test_evidence_scan_releases_company_guard_and_rechecks_authority(
    app, records, evidence_actor, monkeypatch, operation, revoke
):
    company_id = records["companies"]["aurora"]
    with evidence_actor() as user:
        member_id = db.session.scalar(
            select(Membership.id).where(
                Membership.organization_id == company_id, Membership.user_id == user.id
            )
        )
        role_ids = db.session.scalars(
            select(MembershipRole.role_id).where(MembershipRole.membership_id == member_id)
        ).all()
        permission_id = db.session.scalar(
            select(Permission.id).where(Permission.code == "evidence.upload")
        )
        document = (
            evidence.upload(company_id, "initial.pdf", io.BytesIO(PDF))
            if operation == "rescan"
            else None
        )
        document_id = document.id if document else None
        original_version = document.version if document else None
        scans = []

        def scan(data):
            assert data == PDF
            # A competing stock decision must be able to enter the shared guard
            # immediately while a slow scanner runs, rather than block on I/O.
            with Session(db.engine) as competing:
                assert (
                    competing.scalar(
                        select(Organization)
                        .where(Organization.id == company_id)
                        .with_for_update(nowait=True)
                    )
                    is not None
                )
                if revoke:
                    competing.execute(
                        delete(RolePermission).where(
                            RolePermission.role_id.in_(role_ids),
                            RolePermission.permission_id == permission_id,
                        )
                    )
                competing.commit()
            scans.append(data)
            return "clean"

        monkeypatch.setattr(evidence, "scan_bytes", scan)
        if revoke:
            with pytest.raises(Forbidden):
                if operation == "upload":
                    evidence.upload(company_id, "rejected.pdf", io.BytesIO(PDF))
                else:
                    evidence.rescan(company_id, document_id)
            if operation == "upload":
                assert db.session.scalar(select(Document.id)) is None
                assert not [
                    path for path in Path(app.config["EVIDENCE_ROOT"]).rglob("*") if path.is_file()
                ]
            else:
                db.session.refresh(document)
                assert (document.state, document.scan_status, document.version) == (
                    "quarantined",
                    "unavailable",
                    original_version,
                )
        else:
            result = (
                evidence.upload(company_id, "accepted.pdf", io.BytesIO(PDF))
                if operation == "upload"
                else evidence.rescan(company_id, document_id)
            )
            assert (result.state, result.scan_status) == ("active", "clean")
        assert scans == [PDF]


@pytest.mark.parametrize("operation", ["upload", "rescan"])
def test_private_storage_io_does_not_hold_the_company_guard(
    records, evidence_actor, monkeypatch, operation
):
    company_id = records["companies"]["aurora"]
    with evidence_actor():
        document = (
            evidence.upload(company_id, "initial.pdf", io.BytesIO(PDF))
            if operation == "rescan"
            else None
        )
        storage_calls = []
        adapter_name = "put_bytes" if operation == "upload" else "read_bytes"
        adapter = getattr(evidence, adapter_name)

        def storage(*args):
            with Session(db.engine) as competing:
                assert (
                    competing.scalar(
                        select(Organization)
                        .where(Organization.id == company_id)
                        .with_for_update(nowait=True)
                    )
                    is not None
                )
                competing.commit()
            storage_calls.append(True)
            return adapter(*args)

        monkeypatch.setattr(evidence, adapter_name, storage)
        monkeypatch.setattr(evidence, "scan_bytes", lambda data: "clean")
        if operation == "upload":
            evidence.upload(company_id, "accepted.pdf", io.BytesIO(PDF))
        else:
            evidence.rescan(company_id, document.id)
        assert storage_calls == [True]


def test_rescan_rejects_a_document_changed_during_external_scan(
    records, evidence_actor, monkeypatch
):
    company_id = records["companies"]["aurora"]
    with evidence_actor():
        document = evidence.upload(company_id, "original.pdf", io.BytesIO(PDF))
        document_id = document.id

        def scan(data):
            with Session(db.engine) as competing:
                changed = competing.get(Document, document_id)
                changed.original_name = "concurrent-rename.pdf"
                competing.commit()
            return "clean"

        monkeypatch.setattr(evidence, "scan_bytes", scan)
        with pytest.raises(DomainError, match="changed while scanning"):
            evidence.rescan(company_id, document_id)
        db.session.refresh(document)
        assert (document.original_name, document.state, document.scan_status) == (
            "concurrent-rename.pdf",
            "quarantined",
            "unavailable",
        )


@pytest.mark.parametrize("initial_state", ["draft", "approved"])
def test_independent_reviewer_can_withdraw_unqueued_notice(
    notice_case, evidence_actor, initial_state
):
    s = notice_case
    notice = draft(s, evidence_actor) if initial_state == "draft" else approved(s, evidence_actor)
    with evidence_actor(mfa=True):
        notices.withdraw_notice(
            s["company"],
            notice.id,
            "Obsolete unsent revision independently reviewed.",
            notice.version,
        )
        assert notice.status == "cancelled"
        assert (
            db.session.scalar(
                select(NoticeDelivery.id).where(NoticeDelivery.notice_id == notice.id)
            )
            is None
        )
        assert db.session.scalar(select(JobOutbox.id)) is None


@pytest.mark.parametrize("scope_change", ["recipient", "reopened_case"])
def test_withdrawn_pending_notice_never_executes_after_scope_change(
    notice_case, evidence_actor, monkeypatch, scope_change
):
    s = notice_case
    grant(s["company"], "owner")
    notice = approved(s, evidence_actor)
    with evidence_actor():
        job = notices.enqueue_notice(s["company"], notice.id)
    original_content = (notice.subject, notice.body, notice.recipient_email, notice.revision)
    with evidence_actor(mfa=True):
        if scope_change == "recipient":
            s["contact"].email = "replacement@customer.test"
            db.session.commit()
        else:
            recall.reopen(s["company"], s["case"].id, "New scope requires another review.")
        notices.withdraw_notice(
            s["company"], notice.id, "Stale unsent revision independently reviewed.", notice.version
        )
    calls = []
    monkeypatch.setattr(notices, "send_message", lambda *args: calls.append(args))
    assert jobs.run_one() is None
    db.session.refresh(job)
    db.session.refresh(notice)
    delivery = db.session.scalar(
        select(NoticeDelivery).where(NoticeDelivery.notice_id == notice.id)
    )
    assert calls == []
    assert notice.status == job.status == delivery.status == "cancelled"
    assert job.attempts == 0
    assert (
        notice.subject,
        notice.body,
        notice.recipient_email,
        notice.revision,
    ) == original_content


def test_withdrawal_retains_failed_attempt_and_allows_reviewed_case_closure(
    notice_case, evidence_actor, monkeypatch
):
    s = notice_case
    grant(s["company"], "owner")
    notice = approved(s, evidence_actor)
    with evidence_actor():
        job = notices.enqueue_notice(s["company"], notice.id)
    monkeypatch.setattr(
        notices, "send_message", lambda *args: ("failed", None, "provider_rejected")
    )
    assert jobs.run_one() == "failed"
    with evidence_actor(mfa=True):
        jobs.retry_failed(s["company"], job.id)
        exposure = db.session.scalar(
            select(CaseAffectedShipment).where(CaseAffectedShipment.case_id == s["case"].id)
        )
        recall.record_recovery(
            s["company"],
            s["case"].id,
            exposure.shipment_line_id,
            4,
            "destroyed",
            "Fictional independently verified destruction certificate.",
            "WITHDRAWAL-DISPOSITION-1",
        )
        s["contact"].email = "replacement@customer.test"
        db.session.commit()
        with pytest.raises(DomainError, match="notice delivery"):
            recall.close(s["company"], s["case"].id, "All disposition evidence reviewed.")
        reason = "review-secret-marker: stale recipient requires a reviewed revision."
        notices.withdraw_notice(s["company"], notice.id, reason, notice.version)
        attempts = db.session.scalars(
            select(NoticeDelivery)
            .where(NoticeDelivery.notice_id == notice.id)
            .order_by(NoticeDelivery.attempt)
        ).all()
        assert [(row.attempt, row.status) for row in attempts] == [(1, "failed"), (2, "cancelled")]
        assert attempts[0].error_code == "provider_rejected"
        assert job.attempts == 1 and job.status == "cancelled"
        event = db.session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "notice.withdraw", AuditEvent.entity_id == notice.id
            )
        )
        assert "review-secret-marker" not in json.dumps(event.safe_details)
        case = recall.close(
            s["company"],
            s["case"].id,
            "All independently verified physical dispositions reviewed.",
            "Unsent obsolete communication was withdrawn after independent review.",
        )
        assert case.status == "closed" and case.closed_at is not None


@pytest.mark.parametrize("denial", ["author", "no_mfa", "permission", "version"])
def test_withdrawal_requires_independent_current_authority_and_version(
    notice_case, evidence_actor, denial
):
    s = notice_case
    notice = draft(s, evidence_actor)
    email = "catalog-editor@aurora.test" if denial == "author" else "owner@aurora.test"
    with evidence_actor(email, mfa=denial != "no_mfa") as user:
        if denial == "permission":
            member_id = db.session.scalar(
                select(Membership.id).where(
                    Membership.organization_id == s["company"], Membership.user_id == user.id
                )
            )
            role_ids = select(MembershipRole.role_id).where(
                MembershipRole.membership_id == member_id
            )
            permission_id = db.session.scalar(
                select(Permission.id).where(Permission.code == "notice.approve")
            )
            db.session.execute(
                delete(RolePermission).where(
                    RolePermission.role_id.in_(role_ids),
                    RolePermission.permission_id == permission_id,
                )
            )
            db.session.commit()
        version = notice.version - 1 if denial == "version" else notice.version
        with pytest.raises((DomainError, HTTPException)) as exc:
            notices.withdraw_notice(
                s["company"], notice.id, "Independent review of obsolete unsent revision.", version
            )
        if denial == "author":
            assert isinstance(exc.value, DomainError) and "different eligible" in str(exc.value)
        elif denial == "version":
            assert isinstance(exc.value, DomainError) and "unchanged" in str(exc.value)
        else:
            assert isinstance(exc.value, HTTPException) and exc.value.code in {401, 403}
        db.session.rollback()
        db.session.refresh(notice)
        assert notice.status == "draft"


@pytest.mark.parametrize(
    "delivery_state,job_state,notice_state,claim,acceptance_marker",
    [
        ("sent", "completed", "sent", False, None),
        ("local_written", "completed", "local_written", False, None),
        ("ambiguous", "ambiguous", "ambiguous", False, None),
        ("pending", "processing", "queued", True, None),
        ("processing", "pending", "queued", False, None),
        ("pending", "pending", "queued", True, None),
        ("failed", "failed", "queued", False, "sent_at"),
        ("failed", "failed", "queued", False, "provider_reference"),
    ],
)
def test_withdrawal_refuses_delivery_evidence_or_active_claim(
    notice_case, evidence_actor, delivery_state, job_state, notice_state, claim, acceptance_marker
):
    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        job = notices.enqueue_notice(s["company"], notice.id)
        delivery = db.session.scalar(
            select(NoticeDelivery).where(NoticeDelivery.notice_id == notice.id)
        )
        delivery.status, job.status, notice.status = delivery_state, job_state, notice_state
        if claim:
            job.claimed_at = now()
        if acceptance_marker == "sent_at":
            delivery.sent_at = now()
        elif acceptance_marker == "provider_reference":
            delivery.provider_reference = "provider-accepted-fixture"
        db.session.commit()
    with evidence_actor(mfa=True):
        with pytest.raises(DomainError):
            notices.withdraw_notice(
                s["company"],
                notice.id,
                "Independent review must preserve existing delivery evidence.",
                notice.version,
            )
        db.session.rollback()
        db.session.refresh(notice)
        db.session.refresh(job)
        db.session.refresh(delivery)
        assert (notice.status, job.status, delivery.status) == (
            notice_state,
            job_state,
            delivery_state,
        )


def test_notice_withdrawal_form_requires_csrf_and_redirects_to_retained_revision(
    notice_case, evidence_actor, client
):
    s = notice_case
    notice = approved(s, evidence_actor)
    notice_id, version = notice.id, notice.version
    login(client, "owner@aurora.test")
    with client.session_transaction() as browser_session:
        token_digest = digest(browser_session["auth_ref"])
    auth = db.session.scalar(select(AuthSession).where(AuthSession.token_digest == token_digest))
    auth.last_mfa_at = now()
    db.session.commit()
    path = f"/companies/{s['company']}/notices/{notice_id}"
    page = client.get(path)
    assert page.status_code == 200 and "Record reviewed withdrawal" in page.text
    data = {
        "version": str(version),
        "reason": "Obsolete recipient revision independently reviewed.",
    }
    assert client.post(path + "/withdraw", data=data).status_code == 400
    result = client.post(path + "/withdraw", data={**data, "csrf_token": csrf(page)})
    assert result.status_code == 303 and result.headers["Location"].endswith(path)
    retained = client.get(path)
    assert retained.status_code == 200 and "cancelled" in retained.text
    assert "Record reviewed withdrawal" not in retained.text
