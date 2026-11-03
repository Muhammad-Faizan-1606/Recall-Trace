"""Database-backed durable outbox runner; claims never depend on live web memory."""

import time
import uuid
from datetime import timedelta

import click
from flask.cli import with_appcontext
from sqlalchemy import select
from werkzeug.exceptions import HTTPException

from app.extensions import db
from app.models import Organization, now
from app.models.evidence import JobOutbox, NoticeDelivery, RecallNotice
from app.services.business import DomainError, actor, company_lock, scoped


def _associated_delivery(job):
    """A malformed intent must neither poison the runner nor alter another delivery."""
    if job.kind != "notice.send" or not isinstance(job.payload, dict):
        return None
    try:
        notice_id = uuid.UUID(str(job.payload["notice_id"]))
        delivery_id = uuid.UUID(str(job.payload["delivery_id"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    notice = db.session.scalar(
        select(RecallNotice).where(
            RecallNotice.organization_id == job.organization_id, RecallNotice.id == notice_id
        )
    )
    if notice is None or job.deduplication_key != f"notice:{notice.id}:{notice.revision}":
        return None
    return db.session.scalar(
        select(NoticeDelivery)
        .where(
            NoticeDelivery.organization_id == job.organization_id,
            NoticeDelivery.id == delivery_id,
            NoticeDelivery.notice_id == notice_id,
        )
        .with_for_update()
    )


def run_one():
    # Commit the claim before invoking external work. An abandoned claim is ambiguous,
    # never automatically repeated: the provider may already have accepted it.
    job = db.session.scalar(
        select(JobOutbox)
        .where(JobOutbox.status == "pending", JobOutbox.available_at <= now())
        .order_by(JobOutbox.available_at, JobOutbox.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        db.session.rollback()
        return None
    job_id, company_id = job.id, job.organization_id
    job.status, job.claimed_at = "processing", now()
    job.attempts += 1
    db.session.commit()
    if company_id is None:
        from app.services.account_delivery import process_claimed

        return process_claimed(job_id)
    try:
        company_lock(company_id)
        job = scoped(JobOutbox, company_id, job_id, lock=True)
        if job.status != "processing":
            raise DomainError("Job claim was changed by another operator.")
        if job.kind != "notice.send":
            raise DomainError("Unsupported outbox job kind.")
        if _associated_delivery(job) is None:
            raise DomainError("Malformed notice delivery intent.")
        from app.services.notices import deliver_job

        deliver_job(job)
        db.session.commit()
        return job.status
    except (DomainError, KeyError, ValueError, HTTPException):
        db.session.rollback()
        db.session.scalar(
            select(Organization).where(Organization.id == company_id).with_for_update()
        )
        job = scoped(JobOutbox, company_id, job_id, lock=True)
        job.status, job.error_code = "failed", "execution_revalidation_failed"
        delivery = _associated_delivery(job)
        if delivery is not None:
            delivery.status, delivery.error_code = "failed", "execution_revalidation_failed"
        db.session.commit()
        return "failed"


def recover_abandoned():
    # Follow the same company -> job row lock order as active workflow mutations.
    candidates = db.session.execute(
        select(JobOutbox.organization_id, JobOutbox.id)
        .where(
            JobOutbox.status == "processing", JobOutbox.claimed_at < now() - timedelta(minutes=5)
        )
        .order_by(JobOutbox.organization_id, JobOutbox.id)
    ).all()
    db.session.rollback()
    count = 0
    for company_id, job_id in candidates:
        if company_id is None:
            job = db.session.scalar(
                select(JobOutbox)
                .where(JobOutbox.id == job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if job and job.status == "processing" and job.claimed_at < now() - timedelta(minutes=5):
                job.status, job.error_code = "ambiguous", "account_worker_interrupted"
                db.session.commit()
                count += 1
            else:
                db.session.rollback()
            continue
        try:
            company_lock(company_id)
        except HTTPException:
            # A worker may update its own failed operational intent for a
            # deactivated workspace; this never authorizes external execution.
            db.session.rollback()
            db.session.scalar(
                select(Organization).where(Organization.id == company_id).with_for_update()
            )
            job = scoped(JobOutbox, company_id, job_id, lock=True)
            if job.status == "processing":
                job.status, job.error_code = "failed", "workspace_unavailable"
                delivery = _associated_delivery(job)
                if delivery is not None:
                    delivery.status, delivery.error_code = "failed", "workspace_unavailable"
                db.session.commit()
                count += 1
            else:
                db.session.rollback()
            continue
        job = scoped(JobOutbox, company_id, job_id, lock=True)
        if job.status != "processing" or job.claimed_at >= now() - timedelta(minutes=5):
            db.session.rollback()
            continue
        job.status, job.error_code = "ambiguous", "worker_interrupted"
        delivery = _associated_delivery(job)
        if delivery is not None:
            notice = scoped(RecallNotice, company_id, delivery.notice_id, lock=True)
            notice.status, delivery.status = "ambiguous", "ambiguous"
            delivery.error_code = "worker_interrupted"
        db.session.commit()
        count += 1
    return count


def retry_failed(company_id, job_id):
    actor(company_id, "notice.prepare")
    company_lock(company_id)
    job = scoped(JobOutbox, company_id, job_id, lock=True)
    if job.status != "failed" or job.attempts >= 3:
        raise DomainError(
            "Only a definitively failed job with fewer than three attempts can retry. Ambiguous attempts require reconciliation."
        )
    if job.kind != "notice.send":
        raise DomainError("Unsupported retry kind.")
    previous = _associated_delivery(job)
    if previous is None:
        raise DomainError("Malformed notice delivery intent cannot be retried.")
    notice = scoped(RecallNotice, company_id, previous.notice_id, lock=True)
    if notice.status != "queued":
        raise DomainError("Notice is no longer queued.")
    from app.services.notices import current_scope

    current_scope(company_id, notice=notice)
    delivery = NoticeDelivery(
        organization_id=company_id,
        notice_id=notice.id,
        idempotency_key=previous.idempotency_key,
        attempt=previous.attempt + 1,
        status="pending",
    )
    db.session.add(delivery)
    db.session.flush()
    job.payload = {"notice_id": str(notice.id), "delivery_id": str(delivery.id)}
    job.status, job.error_code, job.available_at, job.claimed_at = "pending", None, now(), None
    db.session.commit()
    return job


@click.command("outbox-run")
@click.option("--limit", type=click.IntRange(1, 1000), default=20, show_default=True)
@click.option("--watch", is_flag=True, help="Run a foreground worker; Ctrl-C stops safely.")
@with_appcontext
def outbox_run(limit, watch):
    """Process committed intents. Never send without configured delivery and approvals."""
    while True:
        ambiguous = recover_abandoned()
        counts = {}
        for _ in range(limit):
            status = run_one()
            if status is None:
                break
            counts[status] = counts.get(status, 0) + 1
        click.echo(f"Outbox outcomes: {counts}; abandoned marked ambiguous: {ambiguous}.")
        if not watch:
            return
        time.sleep(2)


def register(app):
    app.cli.add_command(outbox_run)
