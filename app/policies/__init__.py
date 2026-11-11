"""Live, default-deny company authorization; services use these checks too."""

from flask import abort, g, has_request_context
from flask_login import current_user
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.extensions import db
from app.models import Membership, MembershipRole, Organization, Permission, Role, RolePermission


def _request_cache():
    """Authorization results for this request, discarded on lock, commit or rollback."""
    if not has_request_context():
        return None
    return g.setdefault("_authorization_cache", {})


def forget_authorization():
    if has_request_context():
        g.pop("_authorization_cache", None)


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_soft_rollback")
def _transaction_ended(session, *args):
    forget_authorization()


def membership_for(company_id):
    if not current_user.is_authenticated:
        abort(401)
    cache = _request_cache()
    key = ("membership", company_id, current_user.id)
    if cache is not None and key in cache:
        membership = cache[key]
        if membership is None or membership.partner_id is not None:
            abort(404)
        return membership
    membership = db.session.scalar(
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
    if cache is not None:
        cache[key] = membership
    if membership is None or membership.partner_id is not None:
        abort(404)
    return membership


def permission_codes(company_id):
    """Every action the current member may take here, read in one query per request."""
    membership = membership_for(company_id)
    cache = _request_cache()
    key = ("permissions", company_id, membership.id)
    if cache is not None and key in cache:
        return cache[key]
    codes = frozenset(
        db.session.scalars(
            select(Permission.code)
            .join(RolePermission)
            .join(Role, (Role.id == RolePermission.role_id) & (Role.organization_id == company_id))
            .join(
                MembershipRole,
                (MembershipRole.role_id == Role.id)
                & (MembershipRole.organization_id == company_id),
            )
            .where(
                MembershipRole.membership_id == membership.id,
                Role.archived_at.is_(None),
            )
        )
    )
    if cache is not None:
        cache[key] = codes
    return codes


def allowed(company_id, action):
    return action in permission_codes(company_id)


def require(company_id, action):
    if not allowed(company_id, action):
        abort(403)
