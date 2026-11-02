"""Committed intents, safe retry history and ambiguous external outcomes."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from test_evidence import evidence_actor as _evidence_actor_fixture
from test_notices import approved
from test_notices import notice_case as _notice_case_fixture

from app.extensions import db
from app.models import Organization, now
from app.models.evidence import JobOutbox, NoticeDelivery
from app.services import jobs, notices
from app.services.business import DomainError

evidence_actor = _evidence_actor_fixture
notice_case = _notice_case_fixture


def test_queue_is_durable_deduplicated_and_unconfigured_is_failed(notice_case, evidence_actor):
    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        first = notices.enqueue_notice(s["company"], notice.id)
        again = notices.enqueue_notice(s["company"], notice.id)
        assert first.id == again.id
    assert db.session.scalar(select(JobOutbox.id)) == first.id
    assert jobs.run_one() == "failed"
    assert db.session.get(JobOutbox, first.id).error_code == "mail_unconfigured"
    assert db.session.scalar(select(NoticeDelivery.status)) == "failed"
    assert jobs.run_one() is None


def test_safe_retry_preserves_attempt_history_and_provider_key(
    notice_case, evidence_actor, monkeypatch
):
    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        job = notices.enqueue_notice(s["company"], notice.id)
    assert jobs.run_one() == "failed"
    with evidence_actor():
        jobs.retry_failed(s["company"], job.id)
    monkeypatch.setattr(notices, "send_message", lambda *args: ("local_written", None, None))
    assert jobs.run_one() == "completed"
    rows = db.session.scalars(select(NoticeDelivery).order_by(NoticeDelivery.attempt)).all()
    assert [row.status for row in rows] == ["failed", "local_written"]
    assert rows[0].idempotency_key == rows[1].idempotency_key
    assert notice.status == "local_written"
    assert jobs.run_one() is None


def test_ambiguous_provider_result_never_auto_retries(notice_case, evidence_actor, monkeypatch):
    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        job = notices.enqueue_notice(s["company"], notice.id)
    monkeypatch.setattr(
        notices, "send_message", lambda *args: ("ambiguous", None, "provider_transport_ambiguous")
    )
    assert jobs.run_one() == "ambiguous"
    with evidence_actor():
        with pytest.raises(DomainError, match="Ambiguous attempts"):
            jobs.retry_failed(s["company"], job.id)
    assert jobs.run_one() is None
    assert notice.status == "ambiguous"


def test_worker_revalidates_recipient_before_external_send(
    notice_case, evidence_actor, monkeypatch
):
    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        notices.enqueue_notice(s["company"], notice.id)
    s["contact"].email = "changed@customer.test"
    db.session.commit()

    def forbidden_send(*args):
        raise AssertionError("A changed recipient must not reach external delivery")

    monkeypatch.setattr(notices, "send_message", forbidden_send)
    assert jobs.run_one() == "failed"
    assert db.session.scalar(select(JobOutbox.error_code)) == "execution_revalidation_failed"


def test_abandoned_claim_is_ambiguous_not_resubmitted(notice_case, evidence_actor):
    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        job = notices.enqueue_notice(s["company"], notice.id)
    job.status, job.claimed_at = "processing", now() - timedelta(minutes=6)
    db.session.commit()
    assert jobs.recover_abandoned() == 1
    assert job.status == "ambiguous"
    assert notice.status == "ambiguous"
    assert jobs.run_one() is None


def test_inactive_workspace_fails_job_without_poisoning_worker(
    notice_case, evidence_actor, monkeypatch
):
    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        job = notices.enqueue_notice(s["company"], notice.id)
    company = db.session.get(Organization, s["company"])
    company.status = "inactive"
    db.session.commit()

    def forbidden_send(*args):
        raise AssertionError("Inactive company must not send")

    monkeypatch.setattr(notices, "send_message", forbidden_send)
    assert jobs.run_one() == "failed"
    assert db.session.get(JobOutbox, job.id).error_code == "execution_revalidation_failed"
    assert jobs.run_one() is None


def test_reconcile_ambiguity_requires_independent_clean_evidence(
    notice_case, evidence_actor, monkeypatch
):
    import io

    from test_evidence import PDF

    from app.models.recall import CaseDocument
    from app.services import evidence

    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        job = notices.enqueue_notice(s["company"], notice.id)
    monkeypatch.setattr(
        notices, "send_message", lambda *args: ("ambiguous", None, "provider_transport_ambiguous")
    )
    assert jobs.run_one() == "ambiguous"
    delivery = db.session.scalar(
        select(NoticeDelivery).where(NoticeDelivery.notice_id == notice.id)
    )
    with evidence_actor(mfa=True):
        quarantined = evidence.upload(s["company"], "receipt.pdf", io.BytesIO(PDF))
        with pytest.raises(DomainError, match="clean private evidence"):
            notices.reconcile_delivery(s["company"], delivery.id, "not_sent", quarantined.id)
        monkeypatch.setattr(evidence, "scan_bytes", lambda data: "clean")
        evidence.rescan(s["company"], quarantined.id)
        notices.reconcile_delivery(
            s["company"], delivery.id, "sent", quarantined.id, "provider-confirmed-fixture-receipt"
        )
        assert job.status == "completed" and notice.status == "sent"
        assert db.session.scalar(select(CaseDocument.document_id)) == quarantined.id
    assert jobs.run_one() is None
