import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import current_app, session
from flask_login import login_user, logout_user
from sqlalchemy import select

from app.extensions import db
from app.models import AuthSession, User, now

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def password_hash(password):
    if not 15 <= len(password) <= 128 or password.lower() in {
        "passwordpassword",
        "123456789012345",
        "correct horse battery staple",
    }:
        raise ValueError("Use 15–128 characters and avoid common passwords.")
    return hasher.hash(password)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(email, password):
    user = db.session.scalar(select(User).where(db.func.lower(User.email) == email.lower().strip()))
    try:
        valid = hasher.verify(user.password_hash if user else DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid or user is None or not user.is_active:
        return False
    # Verification is expensive; recheck under a lock before creating a session so a
    # simultaneous password reset cannot authenticate a previously valid password.
    checked_hash, checked_version = user.password_hash, user.auth_version
    user = db.session.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not user.is_active
        or user.password_hash != checked_hash
        or user.auth_version != checked_version
    ):
        db.session.rollback()
        return False
    revoke_current(commit=False)
    session.clear()
    session["_rotation"] = secrets.token_hex(16)
    current_app.session_interface.regenerate(session)
    token = secrets.token_urlsafe(32)
    db.session.add(
        AuthSession(
            user_id=user.id,
            token_digest=digest(token),
            expires_at=now() + timedelta(hours=8),
            auth_version=user.auth_version,
        )
    )
    db.session.commit()
    login_user(user, remember=False)
    session["auth_ref"] = token
    return True


def revoke_current(commit=True):
    token = session.get("auth_ref")
    if token:
        row = db.session.scalar(
            select(AuthSession).where(AuthSession.token_digest == digest(token))
        )
        if row:
            row.revoked_at = now()
            if commit:
                db.session.commit()


def signout():
    revoke_current()
    logout_user()
    session.clear()
