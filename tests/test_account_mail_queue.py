"""Account eligibility and delivery must not run on the public request path."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event, Lock, current_thread

import pytest
from conftest import PASSWORD, post_form, read_mail_token
from cryptography.fernet import Fernet
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import NotFound

from app.extensions import db
from app.models import EmailVerificationToken, PasswordResetToken, User, now
from app.models.evidence import JobOutbox
from app.services import account_delivery as delivery
from app.services import development_mail, jobs
from app.services.account_recovery import request_challenge, reset_password, verify_email
from app.services.auth import authenticate, digest


@pytest.fixture(autouse=True)
def delivery_key(app, monkeypatch):
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setitem(app.config, "MFA_KEY_VERSION", "v1")


def queued():
    return db.session.scalars(select(JobOutbox).order_by(JobOutbox.created_at, JobOutbox.id)).all()


@pytest.mark.parametrize("eligibility", ["active", "absent", "inactive", "verified"])
def test_public_path_never_queries_eligibility_or_calls_transport(
    client, mail_spool, monkeypatch, eligibility
):
    email = "absent@aurora.test" if eligibility == "absent" else "catalog-editor@aurora.test"
    if eligibility in {"inactive", "verified"}:
        user = db.session.scalar(select(User).where(User.email == email))
        if eligibility == "inactive":
            user.active = False
        else:
            user.email_verified_at = now()
        db.session.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("Public request must not contact account transport")

    monkeypatch.setattr(development_mail, "deliver_account_message", forbidden)
    monkeypatch.setattr(development_mail, "deliver_development_message", forbidden)
    statements = []

    def record_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
        if "from users" in statement.lower() or "update users" in statement.lower():
            raise AssertionError("Public request queried account eligibility")

    engine = db.engine
    event.listen(engine, "before_cursor_execute", record_sql)
    try:
        response = post_form(client, "/account/verify/request", {"email": email})
    finally:
        event.remove(engine, "before_cursor_execute", record_sql)
    assert response.status_code == 303
    assert "If this address belongs to an eligible account" in client.get(response.location).text
    rows = queued()
    assert len(rows) == 1 and rows[0].status == "pending"
    assert rows[0].organization_id is None and rows[0].created_by_id is None
    assert rows[0].kind == delivery.KIND
    assert email not in json.dumps(rows[0].payload)
    assert rows[0].payload["request_key"] != digest(email)
    assert sum("insert into job_outbox" in sql for sql in statements) == 1
    assert not list(mail_spool.glob("*.json"))
    assert db.session.query(PasswordResetToken).count() == 0
    assert db.session.query(EmailVerificationToken).count() == 0


@pytest.mark.parametrize(
    "model,purpose,subject",
    [
        (PasswordResetToken, "reset", "password recovery"),
        (EmailVerificationToken, "verify", "email verification"),
    ],
)
def test_worker_delivers_real_digest_only_challenge_and_it_can_be_consumed(
    mail_spool, caplog, model, purpose, subject
):
    request_challenge("catalog-editor@aurora.test", model)
    job = queued()[0]
    job_id = job.id
    assert db.session.query(model).count() == 0
    assert jobs.run_one() == "completed"
    token = read_mail_token(mail_spool, subject)
    row = db.session.scalar(select(model))
    assert row.id == job_id and row.token_digest == digest(token)
    assert token not in json.dumps(queued()[0].payload)
    assert token not in caplog.text
    assert "catalog-editor@aurora.test" not in json.dumps(queued()[0].payload)
    if purpose == "reset":
        assert reset_password(token, "New fictional queued password 829!") is True
        assert reset_password(token, "New fictional queued password 829!") is False
    else:
        assert verify_email(token) is True
        assert verify_email(token) is False
    assert jobs.run_one() is None


@pytest.mark.parametrize("eligibility", ["absent", "inactive", "verified"])
def test_worker_discards_ineligible_requests_without_email_or_token(mail_spool, eligibility):
    email = "absent@aurora.test" if eligibility == "absent" else "catalog-editor@aurora.test"
    if eligibility != "absent":
        user = db.session.scalar(select(User).where(User.email == email))
        if eligibility == "inactive":
            user.active = False
        else:
            user.email_verified_at = now()
        db.session.commit()
    request_challenge(email, EmailVerificationToken)
    assert jobs.run_one() == "completed"
    assert db.session.query(EmailVerificationToken).count() == 0
    assert not list(mail_spool.glob("*.json"))
    assert queued()[0].error_code == "account_no_delivery"


def test_new_queued_request_immediately_invalidates_previously_delivered_code(mail_spool):
    email = "catalog-editor@aurora.test"
    request_challenge(email, PasswordResetToken)
    first_id = queued()[0].id
    assert jobs.run_one() == "completed"
    first = read_mail_token(mail_spool, "password recovery")
    request_challenge(email, PasswordResetToken)
    # The newer worker has not run yet; the old code must already be unusable.
    assert reset_password(first, "New fictional queued password 829!") is False
    assert jobs.run_one() == "completed"
    second = read_mail_token(mail_spool, "password recovery")
    assert first != second
    assert db.session.get(PasswordResetToken, first_id).used_at is not None
    assert reset_password(second, "New fictional queued password 829!") is True


def test_old_unprocessed_request_never_supersedes_newer_queued_work(mail_spool):
    for _ in range(2):
        request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    assert jobs.run_one() == "cancelled"
    assert db.session.query(PasswordResetToken).count() == 0
    assert not list(mail_spool.glob("*.json"))
    assert jobs.run_one() == "completed"
    assert db.session.query(PasswordResetToken).count() == 1
    assert len(list(mail_spool.glob("*.json"))) == 1


def test_expired_request_does_not_issue_delayed_code(mail_spool, monkeypatch):
    requested = now() - delivery.QUEUE_TTL - timedelta(seconds=1)
    real_now = delivery.now
    monkeypatch.setattr(delivery, "now", lambda: requested)
    request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    monkeypatch.setattr(delivery, "now", real_now)
    assert jobs.run_one() == "failed"
    assert db.session.query(PasswordResetToken).count() == 0
    assert not list(mail_spool.glob("*.json"))


@pytest.mark.parametrize("mutation", ["ciphertext", "key_version", "request_key", "wrong_job"])
def test_tampered_or_rebound_request_fails_closed(mail_spool, mutation):
    request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    job = queued()[0]
    payload = dict(job.payload)
    if mutation == "ciphertext":
        payload["ciphertext"] = "invalid"
    elif mutation == "key_version":
        payload["key_version"] = "missing-key-version"
    elif mutation == "request_key":
        payload["request_key"] = "0" * 64
    else:
        request_challenge("absent@aurora.test", PasswordResetToken)
        payload = dict(queued()[1].payload)
    job.payload = payload
    db.session.commit()
    assert jobs.run_one() == "failed"
    assert db.session.query(PasswordResetToken).count() == 0
    assert not list(mail_spool.glob("*.json"))


def test_missing_encryption_never_queues_plaintext(app, monkeypatch):
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", None)
    with pytest.raises(delivery.AccountDeliveryError, match="encryption"):
        request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    assert db.session.query(JobOutbox).count() == 0


@pytest.mark.parametrize("email", ["catalog-editor@aurora.test", "absent@aurora.test"])
def test_missing_request_encryption_is_uniform_safe_503(client, app, monkeypatch, email):
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", None)
    response = post_form(client, "/account/reset/request", {"email": email})
    assert response.status_code == 503
    assert "temporarily unavailable" in response.text
    assert not queued()


def test_rotation_invalidates_linked_tokens_and_new_requests_use_new_key(
    app, mail_spool, monkeypatch
):
    request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    assert jobs.run_one() == "completed"
    old = read_mail_token(mail_spool, "password recovery")
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setitem(app.config, "MFA_KEY_VERSION", "v2")
    # No current-key pseudonym exists yet: the old linked code must not fall
    # through to compatibility handling for historical unlinked challenges.
    assert reset_password(old, "New fictional queued password 829!") is False
    request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    assert jobs.run_one() == "completed"
    new = read_mail_token(mail_spool, "password recovery")
    assert new != old
    assert reset_password(old, "New fictional queued password 829!") is False
    assert reset_password(new, "New fictional queued password 829!") is True


def test_rotation_fails_old_queued_ciphertext_without_issuing_a_token(app, mail_spool, monkeypatch):
    request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setitem(app.config, "MFA_KEY_VERSION", "v2")
    assert jobs.run_one() == "failed"
    assert db.session.query(PasswordResetToken).count() == 0
    assert not list(mail_spool.glob("*.json"))


def test_waiting_request_timestamp_follows_serialized_acceptance(app, mail_spool, monkeypatch):
    waiting, accepted = Event(), Event()
    sequence_guard = Lock()
    sequence = [0]
    base = now()
    original_guard = delivery.request_guard

    def ordered_time():
        with sequence_guard:
            sequence[0] += 1
            return base + timedelta(microseconds=sequence[0])

    def delayed_guard(key):
        if current_thread().name.startswith("delayed-account-request"):
            waiting.set()
            assert accepted.wait(timeout=10)
        original_guard(key)

    monkeypatch.setattr(delivery, "now", ordered_time)
    monkeypatch.setattr(delivery, "request_guard", delayed_guard)

    def enqueue_delayed():
        with app.app_context():
            row = delivery.enqueue("catalog-editor@aurora.test", "reset")
            return row.id, row.created_at

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="delayed-account-request") as pool:
        result = pool.submit(enqueue_delayed)
        assert waiting.wait(timeout=10)
        try:
            first = delivery.enqueue("catalog-editor@aurora.test", "reset")
            first_id, first_time = first.id, first.created_at
        finally:
            accepted.set()
        last_id, last_time = result.result(timeout=10)
    assert first_id != last_id and last_time > first_time
    assert jobs.run_one() == "cancelled"
    assert jobs.run_one() == "completed"
    assert db.session.scalar(select(PasswordResetToken.id)) == last_id


def test_worker_key_unavailability_fails_without_transport(app, mail_spool, monkeypatch):
    request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", None)
    assert jobs.run_one() == "failed"
    assert db.session.query(PasswordResetToken).count() == 0
    assert not list(mail_spool.glob("*.json"))


def test_provider_ambiguity_is_never_retried_and_raw_token_is_not_in_outbox(
    mail_spool, monkeypatch, caplog
):
    captured = []

    def ambiguous(recipient, subject, body, key):
        captured.append(body)
        assert db.session.scalar(select(PasswordResetToken)) is not None
        return "ambiguous", None, "provider_transport_ambiguous"

    monkeypatch.setattr(development_mail, "deliver_account_message", ambiguous)
    request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    assert jobs.run_one() == "ambiguous"
    assert jobs.run_one() is None
    assert len(captured) == 1
    token = captured[0].split("\n")[1]
    assert token not in json.dumps(queued()[0].payload)
    assert token not in caplog.text


def test_interrupted_global_claim_recovers_as_ambiguous_without_transport(mail_spool):
    request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    job = queued()[0]
    job.status, job.claimed_at = "processing", now() - timedelta(minutes=6)
    db.session.commit()
    assert jobs.recover_abandoned() == 1
    assert job.status == "ambiguous"
    assert jobs.run_one() is None
    assert not list(mail_spool.glob("*.json"))


def test_transport_runs_without_user_or_request_guard(mail_spool, monkeypatch):
    from sqlalchemy.orm import Session

    user = db.session.scalar(select(User).where(User.email == "catalog-editor@aurora.test"))
    user_id = user.id
    key = delivery.request_key(user.email, "reset")

    def deliver_without_lock(recipient, subject, body, deduplication_key):
        with Session(db.engine) as independent:
            independent.execute(select(User).where(User.id == user_id).with_for_update(nowait=True))
            independent.execute(
                db.text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": int.from_bytes(bytes.fromhex(key)[:8], "big", signed=True)},
            )
            assert (
                independent.execute(
                    db.text("SELECT pg_try_advisory_xact_lock(:key)"),
                    {"key": int.from_bytes(bytes.fromhex(key)[:8], "big", signed=True)},
                ).scalar()
                is True
            )
            independent.rollback()
        return "local_written", None, None

    monkeypatch.setattr(development_mail, "deliver_account_message", deliver_without_lock)
    request_challenge(user.email, PasswordResetToken)
    assert jobs.run_one() == "completed"


def test_company_operator_cannot_retry_or_read_global_account_job(app, client, owner, records):
    assert (
        app.test_cli_runner().invoke(args=["init-business", "--company", "aurora"]).exit_code == 0
    )
    request_challenge("catalog-editor@aurora.test", PasswordResetToken)
    job = queued()[0]
    job_id = job.id
    with app.test_request_context():
        assert authenticate(owner, PASSWORD)
        with pytest.raises(NotFound):
            jobs.retry_failed(records["companies"]["aurora"], job_id)
        db.session.rollback()


def test_database_rejects_unscoped_business_jobs_and_scoped_account_jobs(records):
    for kind, organization_id in [
        ("notice.send", None),
        (delivery.KIND, records["companies"]["aurora"]),
    ]:
        db.session.add(
            JobOutbox(
                kind=kind,
                organization_id=organization_id,
                payload={},
                deduplication_key=f"invalid:{kind}",
            )
        )
        with pytest.raises(IntegrityError, match="job_scope"):
            db.session.commit()
        db.session.rollback()
