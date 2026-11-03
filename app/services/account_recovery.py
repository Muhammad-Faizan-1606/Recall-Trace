"""Account recovery and verification with digest-only, single-use challenges."""

import re
from datetime import timedelta

from sqlalchemy import select, update

from app.extensions import db
from app.models import AuthSession, User, now
from app.models.account_tokens import EmailVerificationToken, PasswordResetToken
from app.services.auth import digest, password_hash

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
TOKEN_LIFETIMES = {
    PasswordResetToken: timedelta(minutes=30),
    EmailVerificationToken: timedelta(hours=24),
}


def request_challenge(email, model):
    """Queue identical encrypted work; never inspect eligibility or send mail here."""
    if model not in TOKEN_LIFETIMES:
        raise ValueError("Unsupported account challenge")
    from app.services.account_delivery import enqueue

    enqueue(email, "reset" if model is PasswordResetToken else "verify")


def _lock_eligible_user_and_token(model, raw_token):
    if not TOKEN_PATTERN.fullmatch(raw_token or ""):
        return None, None
    token_digest = digest(raw_token)
    preview = db.session.execute(
        select(model.user_id, User.email)
        .join(User, User.id == model.user_id)
        .where(model.token_digest == token_digest)
    ).first()
    if preview is None:
        return None, None
    from app.services.account_delivery import (
        AccountDeliveryError,
        challenge_is_current,
        request_guard,
        request_key,
    )

    try:
        # The same short advisory guard orders new requests, worker issuance and
        # consumption before any user row lock. A queued newer request supersedes
        # an old code immediately, even if its worker has not run yet.
        request_guard(
            request_key(preview.email, "reset" if model is PasswordResetToken else "verify")
        )
    except AccountDeliveryError:
        return None, None
    user = db.session.scalar(
        select(User)
        .where(User.id == preview.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    token = db.session.scalar(
        select(model)
        .where(model.token_digest == token_digest)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not user or not user.is_active or not token or token.used_at or token.expires_at <= now():
        return None, None
    if not challenge_is_current(user, model, token):
        return None, None
    return user, token


def reset_password(raw_token, new_password):
    user, token = _lock_eligible_user_and_token(PasswordResetToken, raw_token)
    if user is None:
        db.session.rollback()
        return False
    try:
        hashed = password_hash(new_password)
    except ValueError:
        db.session.rollback()
        raise
    changed = now()
    user.password_hash = hashed
    user.auth_version += 1
    # Consume every outstanding reset challenge and revoke all active sessions atomically.
    db.session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=changed)
    )
    db.session.execute(
        update(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user.id, EmailVerificationToken.used_at.is_(None))
        .values(used_at=changed)
    )
    db.session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=changed)
    )
    db.session.commit()
    return True


def verify_email(raw_token):
    user, token = _lock_eligible_user_and_token(EmailVerificationToken, raw_token)
    if user is None or user.email_verified_at:
        db.session.rollback()
        return False
    user.email_verified_at = now()
    db.session.execute(
        update(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user.id, EmailVerificationToken.used_at.is_(None))
        .values(used_at=now())
    )
    db.session.commit()
    return True
