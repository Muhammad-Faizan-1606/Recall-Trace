import click
from flask.cli import with_appcontext
from sqlalchemy import select

from app.extensions import db
from app.models import (
    Item,
    ItemVariant,
    Membership,
    MembershipRole,
    Organization,
    Permission,
    Role,
    RolePermission,
    UnitsOfMeasure,
    User,
)
from app.services.auth import password_hash


@click.command("seed-demo")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@with_appcontext
def seed_demo(password):
    """Create two fictional companies and local users; never overwrite existing users."""
    try:
        hashed = password_hash(password)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if db.session.scalar(select(Organization.id).where(Organization.slug == "aurora")):
        click.echo("Demo already exists; no passwords or records changed.")
        return
    permissions = {}
    for code in ("catalog.read", "catalog.manage"):
        permission = db.session.scalar(select(Permission).where(Permission.code == code))
        if not permission:
            permission = Permission(code=code, description=code.replace(".", " "))
            db.session.add(permission)
            db.session.flush()
        permissions[code] = permission
    for slug, name in [("aurora", "Aurora Lamps"), ("beacon", "Beacon Components")]:
        company = Organization(slug=slug, name=name)
        db.session.add(company)
        db.session.flush()
        for role_code, codes in [
            ("catalog-editor", ("catalog.read", "catalog.manage")),
            ("auditor", ("catalog.read",)),
        ]:
            role = Role(organization_id=company.id, code=role_code, name=role_code)
            db.session.add(role)
            db.session.flush()
            for code in codes:
                db.session.add(
                    RolePermission(
                        organization_id=company.id,
                        role_id=role.id,
                        permission_id=permissions[code].id,
                    )
                )
            email = f"{role_code}@{slug}.test"
            user = db.session.scalar(select(User).where(User.email == email))
            if not user:
                user = User(email=email, display_name=role_code, password_hash=hashed)
                db.session.add(user)
                db.session.flush()
            member = Membership(organization_id=company.id, user_id=user.id)
            db.session.add(member)
            db.session.flush()
            db.session.add(
                MembershipRole(organization_id=company.id, membership_id=member.id, role_id=role.id)
            )
        unit = UnitsOfMeasure(
            organization_id=company.id, code="EA", name="Each", dimension="count", decimal_places=0
        )
        item = Item(organization_id=company.id, code="LAMP", name="Desk lamp", kind="finished")
        db.session.add_all([unit, item])
        db.session.flush()
        db.session.add(
            ItemVariant(
                organization_id=company.id,
                sku="LAMP-01",
                revision="A",
                description="Fictional catalog fixture",
                item_id=item.id,
                base_unit_id=unit.id,
            )
        )
    db.session.commit()
    click.echo(
        "Seeded Aurora and Beacon. Users: catalog-editor@aurora.test, auditor@aurora.test; equivalent @beacon.test accounts. Password supplied locally."
    )


def register(app):
    app.cli.add_command(seed_demo)
    app.cli.add_command(create_owner)


@click.command("create-owner")
@click.option("--company", required=True, help="Existing company slug.")
@click.option("--email", required=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@with_appcontext
def create_owner(company, email, password):
    """Bootstrap the first owner locally; never overwrite another owner's account."""
    from argon2.exceptions import VerificationError
    from email_validator import EmailNotValidError, validate_email

    from app.services.auth import hasher

    try:
        email = validate_email(
            email, check_deliverability=False, test_environment=True
        ).normalized.lower()
        hashed = password_hash(password)
    except (ValueError, EmailNotValidError) as exc:
        raise click.ClickException(str(exc)) from exc
    organization = db.session.scalar(
        select(Organization).where(Organization.slug == company).with_for_update()
    )
    if not organization or organization.status != "active" or organization.archived_at:
        raise click.ClickException("Choose an existing active company slug.")
    role = db.session.scalar(
        select(Role).where(Role.organization_id == organization.id, Role.code == "owner")
    )
    if role and (not role.protected or role.archived_at):
        raise click.ClickException("Existing owner role needs manual review.")
    if role:
        existing = db.session.scalar(
            select(Membership.id)
            .join(MembershipRole, MembershipRole.membership_id == Membership.id)
            .join(User, User.id == Membership.user_id)
            .where(
                MembershipRole.role_id == role.id,
                Membership.status == "active",
                Membership.archived_at.is_(None),
                Membership.partner_id.is_(None),
                User.active.is_(True),
                User.archived_at.is_(None),
            )
        )
        if existing:
            click.echo(
                "An active owner already exists; use company access to manage additional owners."
            )
            return
    else:
        role = Role(organization_id=organization.id, code="owner", name="Owner", protected=True)
        db.session.add(role)
        db.session.flush()
    for code in ("catalog.read", "catalog.manage", "access.manage"):
        permission = db.session.scalar(select(Permission).where(Permission.code == code))
        if not permission:
            permission = Permission(code=code, description=code.replace(".", " "))
            db.session.add(permission)
            db.session.flush()
        if not db.session.scalar(
            select(RolePermission.id).where(
                RolePermission.role_id == role.id, RolePermission.permission_id == permission.id
            )
        ):
            db.session.add(
                RolePermission(
                    organization_id=organization.id, role_id=role.id, permission_id=permission.id
                )
            )
    user = db.session.scalar(
        select(User).where(db.func.lower(User.email) == email).with_for_update()
    )
    if user:
        try:
            valid = user.is_active and hasher.verify(user.password_hash, password)
        except VerificationError:
            valid = False
        if not valid:
            raise click.ClickException(
                "Existing account must be active and its current password supplied."
            )
    else:
        user = User(email=email, display_name="Company owner", password_hash=hashed)
        db.session.add(user)
        db.session.flush()
    member = db.session.scalar(
        select(Membership).where(
            Membership.organization_id == organization.id, Membership.user_id == user.id
        )
    )
    if member and (member.partner_id or member.archived_at):
        raise click.ClickException("Restricted or archived membership needs manual review.")
    if not member:
        member = Membership(organization_id=organization.id, user_id=user.id)
        db.session.add(member)
        db.session.flush()
    member.status = "active"
    if not db.session.scalar(
        select(MembershipRole.id).where(
            MembershipRole.membership_id == member.id, MembershipRole.role_id == role.id
        )
    ):
        db.session.add(
            MembershipRole(
                organization_id=organization.id, membership_id=member.id, role_id=role.id
            )
        )
    from app.services.access import revoke_users

    revoke_users([user.id])
    db.session.commit()
    click.echo("Initial owner created. Sign in to manage company access.")
