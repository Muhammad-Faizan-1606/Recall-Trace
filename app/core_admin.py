"""Explicit operator bootstrap for the implemented Core permission catalogue."""

import re

import click
from flask import current_app
from flask.cli import with_appcontext
from flask_login import login_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    Membership,
    MembershipRole,
    Organization,
    Permission,
    Role,
    RolePermission,
    User,
)

CORE_PERMISSIONS = {
    "catalog.read": "Read internal master data and operational records",
    "catalog.manage": "Maintain master records and validate item imports",
    "access.manage": "Administer company access",
    "inventory.receive": "Post supplier receipts",
    "inventory.transfer": "Transfer stock between locations",
    "inventory.dispatch": "Dispatch shipments",
    "production.post": "Record production consumption and output",
    "quality.inspect": "Manage inspection templates and observations",
    "quality.hold": "Place quality holds",
    "quality.release": "Independently review hold releases",
    "trace.run": "Compute scoped upstream and downstream traces",
    "case.prepare": "Prepare cases, tasks and investigation notes",
    "case.approve": "Independently approve current recall scopes",
    "case.close": "Verify recall closure",
    "notice.prepare": "Prepare recipient-specific recall notices",
    "notice.read": "Read approved recipient-scoped notices in the partner portal",
    "notice.approve": "Independently approve and queue notices",
    "notice.acknowledge": "Record an acknowledgement",
    "recovery.record": "Verify physical recovery and disposition",
    "evidence.read": "Read authorized private evidence",
    "evidence.upload": "Upload quarantined evidence",
    "reports.export": "Create scoped private exports",
    "audit.read": "Read company audit metadata",
    "factory.read": "Read the factory model, machines and capacity",
    "factory.manage": "Maintain work centres, machines, shifts, calendar and transit times",
    "factory.record": "Record shop-floor output, downtime and batch cards",
}


def initialize(company):
    role = db.session.scalar(
        select(Role).where(
            Role.organization_id == company.id,
            Role.code == "owner",
            Role.protected.is_(True),
            Role.archived_at.is_(None),
        )
    )
    if role is None:
        raise click.ClickException("Bootstrap the first owner using create-owner first.")
    for code, description in CORE_PERMISSIONS.items():
        permission = db.session.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, description=description)
            db.session.add(permission)
            db.session.flush()
        if not db.session.scalar(
            select(RolePermission.id).where(
                RolePermission.role_id == role.id, RolePermission.permission_id == permission.id
            )
        ):
            db.session.add(
                RolePermission(
                    organization_id=company.id, role_id=role.id, permission_id=permission.id
                )
            )
    db.session.commit()


@click.command("init-business")
@click.option(
    "--company", required=True, help="Existing company slug; grants its owner Core actions."
)
@with_appcontext
def init_business(company):
    """Install explicit Core permission definitions and grants, idempotently."""
    row = db.session.scalar(select(Organization).where(Organization.slug == company))
    if not row or row.status != "active" or row.archived_at:
        raise click.ClickException("Choose an existing active company.")
    initialize(row)
    click.echo("Core permissions initialized; passwords and business records preserved.")


def register(app):
    app.cli.add_command(create_company)
    app.cli.add_command(init_business)
    app.cli.add_command(seed_investigation_demo)
    app.cli.add_command(seed_demo_extras)
    app.cli.add_command(seed_factory_demo)


@click.command("create-company")
@click.option("--name", required=True, help="Company display name.")
@click.option("--slug", required=True, help="Unique lowercase identifier.")
@with_appcontext
def create_company(name, slug):
    """Create a real empty company before create-owner; no fictional records."""
    name, slug = name.strip(), slug.strip()
    if (
        not 1 <= len(name) <= 120
        or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)
        or len(slug) > 80
    ):
        raise click.ClickException("Use a bounded name and a lowercase alphanumeric/hyphen slug.")
    row = db.session.scalar(select(Organization).where(Organization.slug == slug))
    if row:
        if row.name == name and row.status == "active" and row.archived_at is None:
            click.echo("Company already exists; preserved unchanged.")
            return
        raise click.ClickException("Company slug is already in use; existing records preserved.")
    db.session.add(Organization(name=name, slug=slug))
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise click.ClickException(
            "Company slug was claimed concurrently; choose another."
        ) from exc
    click.echo("Empty company created. Bootstrap its first owner, then run init-business.")


@click.command("seed-investigation-demo")
@click.option("--company", required=True)
@click.option("--owner-email", required=True, help="Existing active owner; development only.")
@with_appcontext
def seed_investigation_demo(company, owner_email):
    """Create/reuse the fictional C10 demonstration through real posting services."""
    if current_app.config["APP_ENV"] != "development":
        raise click.ClickException("Fictional investigation fixtures require development mode.")
    organization = db.session.scalar(select(Organization).where(Organization.slug == company))
    user = db.session.scalar(select(User).where(db.func.lower(User.email) == owner_email.lower()))
    if organization is None or user is None or not user.is_active:
        raise click.ClickException("Choose an existing active company owner.")
    owner = db.session.scalar(
        select(Membership.id)
        .join(MembershipRole, MembershipRole.membership_id == Membership.id)
        .join(Role, Role.id == MembershipRole.role_id)
        .where(
            Membership.organization_id == organization.id,
            Membership.user_id == user.id,
            Membership.status == "active",
            Membership.archived_at.is_(None),
            Membership.partner_id.is_(None),
            Role.code == "owner",
            Role.protected.is_(True),
            Role.archived_at.is_(None),
        )
    )
    if owner is None:
        raise click.ClickException("The selected account must be an active company owner.")
    initialize(organization)
    from app.services.business import DomainError
    from app.services.recall import current_trace
    from app.services.trace import compute, summary
    from app.services.trace_fixture import seed_c10

    with current_app.test_request_context():
        login_user(user)
        try:
            result = seed_c10(organization.id)
            try:
                run = current_trace(organization.id, result["case_id"])
            except DomainError:
                run = compute(organization.id, result["case_id"])
            totals = summary(organization.id, run.id)
        except DomainError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo("Fictional C10 investigation seeded; no external communications sent.")
        for entry in totals:
            click.echo(str(entry))
        click.echo(
            "Use Investigations to review scope; approval needs a different MFA-enrolled reviewer."
        )


@click.command("seed-demo-extras")
@click.option("--company", required=True)
@click.option(
    "--owner-email",
    default=None,
    help="Active owner who records the work; defaults to the company's existing owner.",
)
@with_appcontext
def seed_demo_extras(company, owner_email):
    """Add clearly named fictional records around the C10 case (idempotent)."""
    if current_app.config["APP_ENV"] != "development":
        raise click.ClickException("Fictional demonstration records require development mode.")
    organization = db.session.scalar(select(Organization).where(Organization.slug == company))
    if organization is None:
        raise click.ClickException("Choose an existing active company.")
    owners = (
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .join(MembershipRole, MembershipRole.membership_id == Membership.id)
        .join(Role, Role.id == MembershipRole.role_id)
        .where(
            Membership.organization_id == organization.id,
            Membership.status == "active",
            Membership.archived_at.is_(None),
            Membership.partner_id.is_(None),
            Role.code == "owner",
            Role.protected.is_(True),
            Role.archived_at.is_(None),
            User.active.is_(True),
        )
        .order_by(Membership.created_at)
    )
    if owner_email:
        owners = owners.where(db.func.lower(User.email) == owner_email.lower())
    found = db.session.execute(owners.limit(1)).first()
    if found is None:
        raise click.ClickException("Choose an existing active company owner.")
    membership, user = found
    from app.services.business import DomainError
    from app.services.demo_extras import seed_extras

    with current_app.test_request_context():
        login_user(user)
        try:
            report = seed_extras(organization.id, membership.id)
        except (DomainError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
    for line in report or ["Nothing to add; demonstration records already present."]:
        click.echo(line)


@click.command("seed-factory-demo")
@click.option("--owner-email", default=None, help="Existing active account to own the demo.")
@click.option(
    "--owner-of",
    default=None,
    help="Or: use the active owner of this existing company (slug) as the demo owner.",
)
@with_appcontext
def seed_factory_demo(owner_email, owner_of):
    """Create the fictional Lahore Knit Mills (demo) factory, owned by an existing account."""
    if current_app.config["APP_ENV"] != "development":
        raise click.ClickException("Fictional factory fixtures require development mode.")
    if bool(owner_email) == bool(owner_of):
        raise click.ClickException("Give exactly one of --owner-email or --owner-of.")
    if owner_email:
        user = db.session.scalar(
            select(User).where(db.func.lower(User.email) == owner_email.strip().lower())
        )
    else:
        user = db.session.scalar(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .join(Organization, Organization.id == Membership.organization_id)
            .join(MembershipRole, MembershipRole.membership_id == Membership.id)
            .join(Role, Role.id == MembershipRole.role_id)
            .where(
                Organization.slug == owner_of.strip(),
                Membership.status == "active",
                Membership.archived_at.is_(None),
                Membership.partner_id.is_(None),
                Role.code == "owner",
                Role.protected.is_(True),
                Role.archived_at.is_(None),
                User.active.is_(True),
                User.archived_at.is_(None),
            )
            .order_by(Membership.created_at)
            .limit(1)
        )
    if user is None or not user.is_active:
        raise click.ClickException("Choose an existing active account.")
    from app.policies import forget_authorization
    from app.services.factory_demo import (
        NAME,
        ensure_company,
        seed,
        seed_balances,
        seed_floor,
        seed_orders,
        seed_styles,
    )

    with current_app.test_request_context():
        login_user(user)
        organization, member, created = ensure_company(user)
        initialize(organization)
        forget_authorization()
        report = seed(organization, member)
        report += seed_styles(organization, member)
        report += seed_orders(organization, member)
        report += seed_balances(organization, member)
        report += seed_floor(organization, member)
        db.session.commit()
    click.echo(f"{NAME}: {'created' if created else 'already present'}; owner access confirmed.")
    for line in report or ["Factory register already present; nothing changed."]:
        click.echo(line)
