"""Encrypted global account requests; eligibility and delivery run only in workers.

The HTTP path never queries users. Raw one-time tokens are created in worker
memory, stored only as digests, committed, and then passed to the mail transport.
They are never persisted in an outbox payload, including encrypted payloads.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import current_app
from sqlalchemy import select, text, update

from app.extensions import db
from app.models import User, now
from app.models.account_tokens import EmailVerificationToken, PasswordResetToken
from app.models.evidence import JobOutbox
from app.services.auth import digest

KIND = "account.challenge"
QUEUE_TTL = timedelta(minutes=15)
PURPOSES = {
    "reset": (PasswordResetToken, timedelta(minutes=30), "password recovery", "/account/reset"),
    "verify": (
        EmailVerificationToken,
        timedelta(hours=24),
        "email verification",
        "/account/verify",
    ),
}


class AccountDeliveryError(ValueError):
    """A safe account delivery/configuration failure with no secret detail."""


def _keys():
    version = current_app.config.get("MFA_KEY_VERSION", "v1")
    configured = current_app.config.get("MFA_ENCRYPTION_KEY")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,20}", version):
        raise AccountDeliveryError("Account delivery key version is not configured.")
    try:
        raw = base64.urlsafe_b64decode(configured.encode("ascii"))
        if len(raw) != 32:
            raise ValueError
    except (ValueError, TypeError, AttributeError, UnicodeError) as exc:
        raise AccountDeliveryError("Account delivery encryption is not configured.") from exc
    material = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=None,
        info=b"RecallTrace/account-delivery/v1/" + version.encode("ascii"),
    ).derive(raw)
    return version, Fernet(base64.urlsafe_b64encode(material[:32])), material[32:]


def normalize_email(email):
    if not isinstance(email, str):
        raise AccountDeliveryError("Enter a valid bounded account email address.")
    email = email.strip().lower()
    if not 1 <= len(email) <= 254 or any(ord(c) < 32 for c in email):
        raise AccountDeliveryError("Enter a valid bounded account email address.")
    return email


def request_key(email, purpose):
    if purpose not in PURPOSES:
        raise AccountDeliveryError("Unsupported account challenge purpose.")
    _, _, secret = _keys()
    value = json.dumps([normalize_email(email), purpose], ensure_ascii=False).encode()
    return hmac.new(secret, value, hashlib.sha256).hexdigest()


def request_guard(key):
    """Serialize enqueue/issuance/consumption, never external transport I/O."""
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
        raise AccountDeliveryError("Invalid account request identity.")
    lock_id = int.from_bytes(bytes.fromhex(key)[:8], "big", signed=True)
    db.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})


def enqueue(email, purpose):
    """The identical public path for every syntactically valid submitted address."""
    email = normalize_email(email)
    key = request_key(email, purpose)
    version, cipher, _ = _keys()
    job_id = uuid.uuid4()
    try:
        request_guard(key)
        # Order by accepted requests, not when a transaction started waiting for
        # the guard. A delayed waiter accepted last must supersede earlier work.
        requested = now()
        plaintext = json.dumps(
            {
                "v": 1,
                "job_id": str(job_id),
                "email": email,
                "purpose": purpose,
                "requested_at": requested.isoformat(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        ciphertext = cipher.encrypt_at_time(plaintext, int(requested.timestamp())).decode("ascii")
        job = JobOutbox(
            id=job_id,
            organization_id=None,
            created_by_id=None,
            kind=KIND,
            payload={"v": 1, "key_version": version, "request_key": key, "ciphertext": ciphertext},
            deduplication_key=f"account:{job_id}",
            status="pending",
            attempts=0,
            created_at=requested,
            available_at=requested,
        )
        db.session.add(job)
        db.session.commit()
        return job
    except Exception:
        db.session.rollback()
        raise


def _latest(key):
    return db.session.scalar(
        select(JobOutbox)
        .where(
            JobOutbox.organization_id.is_(None),
            JobOutbox.kind == KIND,
            JobOutbox.payload["request_key"].astext == key,
        )
        .order_by(JobOutbox.created_at.desc(), JobOutbox.id.desc())
        .limit(1)
    )


def challenge_is_current(user, model, token):
    """Called under the request/user locks, including for pre-queue legacy tokens."""
    purpose = next((p for p, values in PURPOSES.items() if values[0] is model), None)
    if purpose is None:
        return False
    key = request_key(user.email, purpose)
    version, _, _ = _keys()
    # A linked encrypted request must never fall through the legacy path after
    # key rotation merely because its old pseudonym has no current-key match.
    linked = db.session.get(JobOutbox, token.id)
    latest = _latest(key)
    if linked is not None:
        return (
            linked.organization_id is None
            and linked.kind == KIND
            and isinstance(linked.payload, dict)
            and linked.payload.get("key_version") == version
            and linked.payload.get("request_key") == key
            and linked.status != "cancelled"
            and latest is not None
            and latest.id == linked.id
        )
    if latest is None:
        return True  # Legacy challenge, with no newer queued request.
    return latest.created_at <= token.created_at


def _decode(job):
    version, cipher, _ = _keys()
    payload = job.payload
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or payload.get("key_version") != version
        or not isinstance(payload.get("ciphertext"), str)
        or not 1 <= len(payload["ciphertext"]) <= 2048
    ):
        raise AccountDeliveryError("Invalid encrypted account request.")
    try:
        data = json.loads(
            cipher.decrypt_at_time(
                payload["ciphertext"].encode("ascii"),
                ttl=int(QUEUE_TTL.total_seconds()),
                current_time=int(now().timestamp()),
            )
        )
        if not isinstance(data, dict) or data.get("v") != 1:
            raise ValueError
        requested = datetime.fromisoformat(data["requested_at"])
        email = normalize_email(data["email"])
        purpose = data["purpose"]
        expected = request_key(email, purpose)
        if (
            data["job_id"] != str(job.id)
            or requested.tzinfo is None
            or requested != job.created_at
            or now() - requested > QUEUE_TTL
            or requested > now() + timedelta(seconds=30)
            or not isinstance(payload.get("request_key"), str)
            or not hmac.compare_digest(payload["request_key"], expected)
        ):
            raise ValueError
    except (InvalidToken, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise AccountDeliveryError("Invalid or expired encrypted account request.") from exc
    return email, purpose, expected


def _finish(job_id, status, error_code=None):
    job = db.session.scalar(
        select(JobOutbox)
        .where(JobOutbox.id == job_id, JobOutbox.organization_id.is_(None), JobOutbox.kind == KIND)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        db.session.rollback()
        return "failed"
    if job.status != "processing":
        db.session.rollback()
        return job.status
    job.status, job.error_code = status, error_code
    db.session.commit()
    return status


def process_claimed(job_id):
    """Process one committed global claim; release every DB lock before transport."""
    try:
        preview = db.session.get(JobOutbox, job_id)
        if preview is None or preview.organization_id is not None or preview.kind != KIND:
            raise AccountDeliveryError("Invalid account claim.")
        email, purpose, key = _decode(preview)
        request_guard(key)
        job = db.session.scalar(
            select(JobOutbox)
            .where(JobOutbox.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None or job.status != "processing":
            db.session.rollback()
            return job.status if job else "failed"
        if job.organization_id is not None or job.kind != KIND or job.attempts != 1:
            raise AccountDeliveryError("Invalid or repeated account claim.")
        if _decode(job) != (email, purpose, key):
            raise AccountDeliveryError("Account claim changed.")
        latest = _latest(key)
        if latest is None or latest.id != job.id:
            job.status, job.error_code = "cancelled", "account_request_superseded"
            db.session.commit()
            return "cancelled"
        from app.services.development_mail import development_mail_configured

        if not development_mail_configured():
            job.status, job.error_code = "failed", "account_mail_unconfigured"
            db.session.commit()
            return "failed"
        user = db.session.scalar(
            select(User)
            .where(db.func.lower(User.email) == email)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        model, lifetime, label, route = PURPOSES[purpose]
        if not user or not user.is_active or (purpose == "verify" and user.email_verified_at):
            job.status, job.error_code = "completed", "account_no_delivery"
            db.session.commit()
            return "completed"
        issued = now()
        db.session.execute(
            update(model)
            .where(model.user_id == user.id, model.used_at.is_(None))
            .values(used_at=issued)
        )
        raw_token = secrets.token_urlsafe(32)
        db.session.add(
            model(
                id=job.id,
                user_id=user.id,
                token_digest=digest(raw_token),
                expires_at=issued + lifetime,
            )
        )
        recipient = user.email
        # No provider call is made before the token is committed, or while a
        # user/advisory/job lock can leak transport latency into public requests.
        db.session.commit()
    except (AccountDeliveryError, TypeError, ValueError, KeyError):
        db.session.rollback()
        return _finish(job_id, "failed", "account_request_invalid")
    from app.services.development_mail import deliver_account_message

    body = (
        f"Open {route} in RecallTrace and paste this one-time code:\n{raw_token}\n"
        "If you did not request this message, you can ignore it. A newer request invalidates this code."
    )
    # A claim can be interrupted after the token committed. Do not repeat it:
    # ambiguous jobs remain for the operator; a fresh public request supersedes it.
    outcome, _reference, error = deliver_account_message(
        recipient, f"RecallTrace {label}", body, f"account:{job_id}"
    )
    if outcome in {"sent", "local_written"}:
        return _finish(job_id, "completed")
    if outcome == "failed":
        return _finish(job_id, "failed", error or "account_delivery_failed")
    return _finish(job_id, "ambiguous", error or "account_delivery_ambiguous")
