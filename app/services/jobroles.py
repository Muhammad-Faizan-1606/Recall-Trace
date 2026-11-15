"""Job roles: who sees which part of the factory, and the ready-made roles a company starts with.

Every factory screen belongs to an *area*. A person sees an area when they hold one of its
permissions, or `factory.read_all` (look at everything, change nothing). Actions are still
checked by each service, so hiding a screen is never the only protection.

Admins (`access.manage`) can preview the app as any job role. Preview changes only what is
displayed (menu and home tiles); permissions on every request stay the admin's own.
"""

from flask import abort, session
from sqlalchemy import select

from app.extensions import db
from app.models import Permission, Role, RolePermission
from app.policies import allowed, membership_for, permission_codes, require
from app.services.audit import record as audit
from app.services.business import DomainError, company_lock

READ_ALL = "factory.read_all"
AREAS = {
    "dashboard": {"factory.read"},
    "planning": {"factory.plan", "factory.manage"},
    "floor": {"factory.record", "factory.plan", "factory.manage", "quality.inspect"},
    "maintenance": {"factory.maintain", "factory.manage"},
    "machines": {"factory.maintain", "factory.manage", "factory.plan"},
    "engineering": {"factory.manage", "factory.plan"},
    "setup": {"factory.manage"},
}
# A sewing line's visual page serves both planners and the floor.
AREAS["lines"] = AREAS["planning"] | AREAS["floor"]
# Who may acknowledge and resolve factory alerts: anyone with a factory job, not viewers.
ALERT_ACTORS = (
    "factory.record",
    "factory.plan",
    "factory.maintain",
    "factory.manage",
    "quality.inspect",
)

# code, name, who it is for, permissions
JOB_ROLES = [
    (
        "factory-planner",
        "Planner",
        "Production orders, the planning board, line balancing and styles.",
        ("factory.read", "factory.plan"),
    ),
    (
        "factory-supervisor",
        "Floor supervisor",
        "Hourly output, stops, quality checks, batch cards and bundle tickets.",
        ("factory.read", "factory.record", "production.post"),
    ),
    (
        "factory-maintenance",
        "Maintenance technician",
        "Breakdowns, preventive jobs and machine history.",
        ("factory.read", "factory.maintain"),
    ),
    (
        "factory-quality",
        "Quality inspector",
        "Line quality checks, holds and recall investigations.",
        (
            "factory.read",
            "quality.inspect",
            "quality.hold",
            "trace.run",
            "case.prepare",
            "catalog.read",
        ),
    ),
    (
        "factory-viewer",
        "Manager (dashboard only)",
        "The factory dashboard, alerts and the live factory map. Cannot change anything.",
        ("factory.read",),
    ),
]
ROLE_INFO = {code: (name, about, set(codes)) for code, name, about, codes in JOB_ROLES}
OWNER_ABOUT = "Everything, including who can do what."


# ---------- What the current person sees ----------


def preview_role(company_id):
    """The job role an admin is previewing in this company, if any."""
    code = (session.get("role_preview") or {}).get(str(company_id))
    if code in ROLE_INFO and allowed(company_id, "access.manage"):
        return code
    return None


def display_codes(company_id):
    """Permissions that decide what is *shown*: the previewed role's, or the person's own."""
    code = preview_role(company_id)
    if code:
        return frozenset(ROLE_INFO[code][2])
    return permission_codes(company_id)


def sees(company_id, area):
    codes = display_codes(company_id)
    if "factory.read" not in codes:
        return False
    return READ_ALL in codes or bool(AREAS[area] & codes)


def shows(company_id, *codes):
    """Display check for any non-factory permission (menu items, home tiles)."""
    return bool(set(codes) & display_codes(company_id))


def require_area(company_id, area):
    """Server-side check for opening a screen, using the person's real permissions."""
    require(company_id, "factory.read")
    codes = permission_codes(company_id)
    if READ_ALL not in codes and not AREAS[area] & codes:
        abort(403)


def require_any(company_id, *codes):
    if not set(codes) & permission_codes(company_id):
        abort(403)


def is_admin_view(company_id):
    """Admins see the full workspace, unless they are previewing a job role."""
    return allowed(company_id, "access.manage") and preview_role(company_id) is None


def simple_mode(company_id):
    """Factory-only jobs (no catalog access), or an admin previewing one, land on Home."""
    return preview_role(company_id) is not None or not allowed(company_id, "catalog.read")


def set_preview(company_id, code):
    require(company_id, "access.manage")
    previews = dict(session.get("role_preview") or {})
    if code:
        if code not in ROLE_INFO:
            raise DomainError("Choose a job role to preview.")
        previews[str(company_id)] = code
    else:
        previews.pop(str(company_id), None)
    session["role_preview"] = previews


# ---------- Installing the ready-made roles ----------


def install(company_id):
    """Create the job roles a company does not have yet. Idempotent.

    An admin can only create roles from permissions they hold themselves, the same rule the
    role editor enforces, so this never hands out more than its installer has.
    """
    require(company_id, "access.manage")
    company_lock(company_id)
    require(company_id, "access.manage")
    mine = permission_codes(company_id)
    member = membership_for(company_id)
    permissions = {
        p.code: p
        for p in db.session.scalars(
            select(Permission).where(
                Permission.code.in_({c for *_, codes in JOB_ROLES for c in codes})
            )
        )
    }
    created, skipped = [], []
    for code, name, _about, codes in JOB_ROLES:
        if db.session.scalar(
            select(Role.id).where(Role.organization_id == company_id, Role.code == code)
        ):
            continue
        if not set(codes) <= mine or not set(codes) <= set(permissions):
            skipped.append(name)
            continue
        role = Role(organization_id=company_id, code=code, name=name)
        db.session.add(role)
        db.session.flush()
        for permission_code in codes:
            db.session.add(
                RolePermission(
                    organization_id=company_id,
                    role_id=role.id,
                    permission_id=permissions[permission_code].id,
                )
            )
        created.append(name)
    if created:
        audit(company_id, "access.job_roles_installed", "roles", None, {"count": len(created)})
    db.session.commit()
    return created, skipped, member
