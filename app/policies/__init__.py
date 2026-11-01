"""Live, default-deny company authorization; services use these checks too."""

from flask import abort
from flask_login import current_user
from sqlalchemy import select

from app.extensions import db
from app.models import Membership, MembershipRole, Organization, Permission, Role, RolePermission


def membership_for(company_id):
    if not current_user.is_authenticated:
        abort(401)
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
    )
    if membership is None or membership.partner_id is not None:
        abort(404)
    return membership


def allowed(company_id, action):
    membership = membership_for(company_id)
    return (
        db.session.scalar(
            select(Permission.id)
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
                Permission.code == action,
            )
            .limit(1)
        )
        is not None
    )


def require(company_id, action):
    if not allowed(company_id, action):
        abort(403)
