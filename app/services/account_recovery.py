"""Account recovery and verification with digest-only, single-use challenges."""

import re
import secrets
from datetime import timedelta

from sqlalchemy import select, update

from app.extensions import db
from app.models import AuthSession, User, now
from app.models.account_tokens import EmailVerificationToken, PasswordResetToken
from app.services.auth import digest, password_hash
from app.services.development_mail import (
    deliver_development_message,
    development_mail_configured,
)

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
TOKEN_LIFETIMES = {
    PasswordResetToken: timedelta(minutes=30),
    EmailVerificationToken: timedelta(hours=24),
}


def request_challenge(email, model):
    """Always return the same public outcome; callers never receive the token."""
    if model not in TOKEN_LIFETIMES:
        raise ValueError("Unsupported account challenge")
    if not development_mail_configured():
        return
    user = db.session.scalar(
        select(User)
        .where(db.func.lower(User.email) == email.strip().lower())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not user
        or not user.is_active
        or (model is EmailVerificationToken and user.email_verified_at)
    ):
        db.session.rollback()
        return
    issued = now()
    # User is the common lock for challenge issuance, reset, verification and login.
    db.session.execute(
        update(model)
        .where(model.user_id == user.id, model.used_at.is_(None))
        .values(used_at=issued)
    )
    raw_token = secrets.token_urlsafe(32)
    db.session.add(
        model(
            user_id=user.id,
            token_digest=digest(raw_token),
            expires_at=issued + TOKEN_LIFETIMES[model],
        )
    )
    email = user.email
    db.session.commit()
    purpose = "password recovery" if model is PasswordResetToken else "email verification"
    route = "/account/reset" if model is PasswordResetToken else "/account/verify"
    # Deliver only after the challenge is committed. There is no production transport.
    deliver_development_message(
        email,
        f"RecallTrace {purpose}",
        f"Open {route} in RecallTrace and paste this one-time code:\n{raw_token}\n"
        "If you did not request this message, you can ignore it. A newer request invalidates this code.",
    )


def _lock_eligible_user_and_token(model, raw_token):
    if not TOKEN_PATTERN.fullmatch(raw_token or ""):
        return None, None
    token_digest = digest(raw_token)
    user_id = db.session.scalar(select(model.user_id).where(model.token_digest == token_digest))
    if user_id is None:
        return None, None
    user = db.session.scalar(
        select(User)
        .where(User.id == user_id)
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
