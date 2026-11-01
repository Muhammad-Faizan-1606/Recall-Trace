"""A user can inspect and revoke only their own authentication registry entries."""

from flask import abort, session
from flask_login import current_user
from sqlalchemy import select

from app.extensions import db
from app.models import AuthSession, User, now
from app.services.auth import digest


def own_sessions():
    return db.session.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == current_user.id)
        .order_by(AuthSession.created_at.desc(), AuthSession.id)
        .limit(100)
    ).all()


def revoke(session_id):
    # Same lock order as password recovery: user first, then registry rows.
    db.session.scalar(select(User).where(User.id == current_user.id).with_for_update())
    row = db.session.scalar(
        select(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.user_id == current_user.id,
        )
        .with_for_update()
    )
    if row is None:
        abort(404)
    if row.revoked_at is None:
        row.revoked_at = now()
    is_current = row.token_digest == digest(session.get("auth_ref", ""))
    db.session.commit()
    return is_current
