"""Company administration serializes on the company row, then locks affected users."""

import secrets
from datetime import timedelta
from functools import wraps

from flask import abort, current_app
from flask_login import current_user
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.core_admin import CORE_PERMISSIONS
from app.extensions import db
from app.models import (
    AuthSession,
    Membership,
    MembershipRole,
    Organization,
    Permission,
    Role,
    RolePermission,
    User,
    now,
)
from app.models.invitations import Invitation
from app.models.master import Partner
from app.policies import membership_for, require
from app.services.account_recovery import TOKEN_PATTERN
from app.services.audit import record as audit
from app.services.auth import digest, password_hash
from app.services.development_mail import deliver_development_message, development_mail_configured

ACTIONS = set(CORE_PERMISSIONS)
PARTNER_ACTIONS = {"notice.read", "notice.acknowledge"}
_UNCHANGED = object()


class AccessConflict(Exception):
    pass


def mutation(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
            if result is False:
                db.session.rollback()
            return result
        except (IntegrityError, StaleDataError) as exc:
            db.session.rollback()
            raise AccessConflict(
                "The record changed or conflicts with existing data. Reload before retrying."
            ) from exc
        except Exception:
            db.session.rollback()
            raise

    return checked


def lock_company(company_id):
    # Resolve session validation before taking any transaction guard; its heartbeat commits.
    if not current_user.is_authenticated:
        abort(401)
    db.session.scalar(
        select(Organization)
        .where(Organization.id == company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    require(company_id, "access.manage")
    if current_app.config.get("APP_ENV") == "production":
        from app.services.mfa import require_recent_mfa

        require_recent_mfa(company_id)


def permissions_for(member, allow_partner=False):
    if member.status != "active" or member.archived_at or (member.partner_id and not allow_partner):
        return set()
    user = db.session.get(User, member.user_id)
    if not user or not user.is_active:
        return set()
    codes = set(
        db.session.scalars(
            select(Permission.code)
            .join(RolePermission)
            .join(Role, Role.id == RolePermission.role_id)
            .join(MembershipRole, MembershipRole.role_id == Role.id)
            .where(
                MembershipRole.organization_id == member.organization_id,
                MembershipRole.membership_id == member.id,
                Role.organization_id == member.organization_id,
                Role.archived_at.is_(None),
            )
        )
    )
    return codes & PARTNER_ACTIONS if member.partner_id else codes


def role_permissions(role):
    return set(
        db.session.scalars(
            select(Permission.code)
            .join(RolePermission)
            .where(
                RolePermission.role_id == role.id,
                RolePermission.organization_id == role.organization_id,
            )
        )
    )


def scoped(model, company_id, record_id):
    row = db.session.scalar(
        select(model)
        .where(model.organization_id == company_id, model.id == record_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        abort(404)
    return row


def grantable(role, member):
    return role.archived_at is None and role_permissions(role) <= permissions_for(member)


def validate_partner_role(company_id, role, partner_id):
    if not partner_id:
        return None
    partner = scoped(Partner, company_id, partner_id)
    if partner.archived_at or partner.status != "active":
        raise AccessConflict("Choose an active partner in this company.")
    codes = role_permissions(role)
    if role.protected or "notice.read" not in codes or not codes <= PARTNER_ACTIONS:
        raise AccessConflict("Partner accounts require a portal-only role with notice.read.")
    return partner.id


def revoke_users(user_ids):
    for user_id in sorted(set(user_ids), key=str):
        user = db.session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        user.auth_version += 1
        db.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now())
        )


@mutation
def save_role(company_id, code, name, codes, role_id=None, version=None):
    lock_company(company_id)
    actor = membership_for(company_id)
    codes = set(codes)
    if not codes or not codes <= ACTIONS or not codes <= permissions_for(actor):
        raise AccessConflict("Choose permissions you currently hold.")
    if not code or len(code) > 50 or not name or len(name) > 80:
        raise AccessConflict("A bounded role code and name are required.")
    if code == "owner":
        raise AccessConflict("The owner role is managed by the owner bootstrap workflow.")
    role = (
        scoped(Role, company_id, role_id)
        if role_id
        else Role(organization_id=company_id, code=code, name=name)
    )
    if role_id and (
        role.protected or role.archived_at or role.version != version or not grantable(role, actor)
    ):
        raise AccessConflict(
            "This role is protected, changed, archived, or exceeds your authority."
        )
    if role_id and ("notice.read" not in codes or not codes <= PARTNER_ACTIONS):
        partner_use = db.session.scalar(
            select(Membership.id)
            .join(MembershipRole, MembershipRole.membership_id == Membership.id)
            .where(MembershipRole.role_id == role_id, Membership.partner_id.is_not(None))
            .limit(1)
        )
        pending_partner_invite = db.session.scalar(
            select(Invitation.id)
            .where(
                Invitation.role_id == role_id,
                Invitation.partner_id.is_not(None),
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > now(),
            )
            .limit(1)
        )
        if partner_use or pending_partner_invite:
            raise AccessConflict(
                "A role used by partners must remain limited to portal permissions."
            )
    try:
        role.code, role.name = code, name
        # Force a version change even when only association rows change.
        if role_id:
            role.version += 1
        db.session.add(role)
        db.session.flush()
        db.session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        for permission in db.session.scalars(select(Permission).where(Permission.code.in_(codes))):
            db.session.add(
                RolePermission(
                    organization_id=company_id, role_id=role.id, permission_id=permission.id
                )
            )
        user_ids = db.session.scalars(
            select(Membership.user_id)
            .join(MembershipRole, MembershipRole.membership_id == Membership.id)
            .where(MembershipRole.role_id == role.id)
        ).all()
        revoke_users(user_ids)
        audit(
            company_id,
            "access.role.updated" if role_id else "access.role.created",
            "roles",
            role.id,
            {"count": len(codes), "version": role.version},
        )
        db.session.commit()
        return role
    except IntegrityError as exc:
        db.session.rollback()
        raise AccessConflict("Role code already exists.") from exc


@mutation
def change_membership(company_id, membership_id, role_id, status, version, partner_id=_UNCHANGED):
    lock_company(company_id)
    actor = membership_for(company_id)
    member = scoped(Membership, company_id, membership_id)
    role = scoped(Role, company_id, role_id)
    if status not in {"active", "inactive"} or member.version != version or member.archived_at:
        raise AccessConflict("Membership changed or is archived; reload before editing.")
    binding = member.partner_id if partner_id is _UNCHANGED else partner_id
    binding = validate_partner_role(company_id, role, binding)
    if not grantable(role, actor) or not permissions_for(
        member, allow_partner=True
    ) <= permissions_for(actor):
        raise AccessConflict("The requested membership exceeds your authority.")
    # Count under the company lock so two administrators cannot remove both owners.
    owners = db.session.scalars(
        select(Membership.id)
        .join(MembershipRole, MembershipRole.membership_id == Membership.id)
        .join(Role, Role.id == MembershipRole.role_id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == company_id,
            Membership.status == "active",
            Membership.archived_at.is_(None),
            Membership.partner_id.is_(None),
            Role.code == "owner",
            Role.protected.is_(True),
            Role.archived_at.is_(None),
            User.active.is_(True),
            User.archived_at.is_(None),
        )
    ).all()
    if (
        member.id in owners
        and len(owners) == 1
        and (status != "active" or role.code != "owner" or binding)
    ):
        raise AccessConflict("The company must retain an active owner.")
    # Capture the currently authorized actor before a legitimate self-step-down.
    audit(company_id, "access.membership.updated", "memberships", member.id, {"status": status})
    member.status = status
    member.partner_id = binding
    member.version += 1
    db.session.execute(delete(MembershipRole).where(MembershipRole.membership_id == member.id))
    db.session.add(
        MembershipRole(organization_id=company_id, membership_id=member.id, role_id=role.id)
    )
    revoke_users([member.user_id])
    db.session.commit()


@mutation
def invite(company_id, email, role_id, partner_id=None):
    lock_company(company_id)
    actor = membership_for(company_id)
    role = scoped(Role, company_id, role_id)
    if not grantable(role, actor):
        raise AccessConflict("You cannot invite with that role.")
    binding = validate_partner_role(company_id, role, partner_id)
    if not development_mail_configured():
        raise AccessConflict("Account delivery must be configured before inviting users.")
    email = email.strip().lower()
    db.session.execute(
        update(Invitation)
        .where(
            Invitation.organization_id == company_id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    )
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        organization_id=company_id,
        email=email,
        role_id=role.id,
        partner_id=binding,
        invited_by_id=actor.id,
        token_digest=digest(token),
        expires_at=now() + timedelta(days=2),
    )
    db.session.add(invitation)
    db.session.flush()
    audit(company_id, "access.invitation.created", "invitations", invitation.id)
    db.session.commit()
    if not deliver_development_message(
        email,
        "RecallTrace company invitation",
        f"Open /invitations/accept and paste this one-time code:\n{token}\nSign in first if you already have an account.",
    ):
        raise AccessConflict(
            "Invitation saved but delivery was not confirmed. Revoke or resend it."
        )


@mutation
def revoke_invitation(company_id, invitation_id):
    lock_company(company_id)
    invitation = scoped(Invitation, company_id, invitation_id)
    if invitation.accepted_at:
        raise AccessConflict("Accepted invitations are retained as history.")
    invitation.revoked_at = now()
    audit(company_id, "access.invitation.revoked", "invitations", invitation.id)
    db.session.commit()


@mutation
def accept_invitation(token, display_name, password):
    signed_in = current_user.is_authenticated
    signed_in_id = current_user.id if signed_in else None
    if not TOKEN_PATTERN.fullmatch(token or ""):
        return False
    preview = db.session.scalar(select(Invitation).where(Invitation.token_digest == digest(token)))
    if preview is None:
        return False
    company = db.session.scalar(
        select(Organization)
        .where(Organization.id == preview.organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if company.status != "active" or company.archived_at:
        return False
    user = db.session.scalar(
        select(User)
        .where(db.func.lower(User.email) == preview.email)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    invitation = db.session.scalar(
        select(Invitation)
        .where(Invitation.id == preview.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if invitation.accepted_at or invitation.revoked_at or invitation.expires_at <= now():
        return False
    issuer = scoped(Membership, company.id, invitation.invited_by_id)
    role = scoped(Role, company.id, invitation.role_id)
    if "access.manage" not in permissions_for(issuer) or not grantable(role, issuer):
        return False
    try:
        binding = validate_partner_role(company.id, role, invitation.partner_id)
    except AccessConflict:
        return False
    if user:
        if not signed_in or signed_in_id != user.id or not user.is_active:
            raise AccessConflict("Sign in to the invited account before accepting this invitation.")
        existing = db.session.scalar(
            select(Membership).where(
                Membership.organization_id == company.id, Membership.user_id == user.id
            )
        )
        if existing:
            raise AccessConflict(
                "This account already has a membership; ask the owner to manage it."
            )
    else:
        if signed_in:
            raise AccessConflict("Sign out before creating the invited account.")
        if not display_name or len(display_name) > 120:
            raise AccessConflict("Enter a display name of at most 120 characters.")
        try:
            hashed = password_hash(password or "")
        except ValueError as exc:
            raise AccessConflict(str(exc)) from exc
        user = User(email=invitation.email, display_name=display_name, password_hash=hashed)
        db.session.add(user)
        db.session.flush()
    user.email_verified_at = now()
    member = Membership(organization_id=company.id, user_id=user.id, partner_id=binding)
    db.session.add(member)
    db.session.flush()
    db.session.add(
        MembershipRole(organization_id=company.id, membership_id=member.id, role_id=role.id)
    )
    invitation.accepted_at = now()
    revoke_users([user.id])
    db.session.commit()
    return True


@mutation
def remove_role(company_id, role_id, version):
    lock_company(company_id)
    role = scoped(Role, company_id, role_id)
    if (
        role.protected
        or role.archived_at
        or role.version != version
        or not grantable(role, membership_for(company_id))
    ):
        raise AccessConflict(
            "This role is protected, changed, archived, or exceeds your authority."
        )
    users = db.session.scalars(
        select(Membership.user_id)
        .join(MembershipRole, MembershipRole.membership_id == Membership.id)
        .where(MembershipRole.role_id == role.id)
    ).all()
    referenced = (
        bool(users)
        or db.session.scalar(select(Invitation.id).where(Invitation.role_id == role.id).limit(1))
        is not None
    )
    if referenced:
        role.archived_at = now()
        revoke_users(users)
        result = "Referenced role archived. Affected users must sign in again."
    else:
        db.session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        db.session.delete(role)
        result = "Unused role deleted."
    audit(
        company_id,
        "access.role.archived" if referenced else "access.role.deleted",
        "roles",
        role.id,
    )
    db.session.commit()
    return result
