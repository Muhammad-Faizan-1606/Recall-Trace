"""Simple mode: a big-tile home for each job, role preview, and an easy team screen."""

import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import func, select

from app.extensions import db, limiter
from app.models import Membership, MembershipRole, Organization, Role, User
from app.models.factory import FactoryAlert
from app.policies import allowed, membership_for, require
from app.services import access, jobroles
from app.services.business import DomainError

bp = Blueprint("home", __name__, url_prefix="/companies/<uuid:company_id>")


@bp.app_context_processor
def job_helpers():
    return {
        "sees": jobroles.sees,
        "shows": jobroles.shows,
        "admin_view": jobroles.is_admin_view,
        "previewing": lambda company_id: (
            jobroles.ROLE_INFO[code][0] if (code := jobroles.preview_role(company_id)) else None
        ),
    }


def role_names(company_id, member_id):
    return db.session.scalars(
        select(Role.name)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .where(MembershipRole.membership_id == member_id, Role.organization_id == company_id)
        .order_by(Role.name)
    ).all()


# Tiles: (permission codes shown to, title, short help, icon, endpoint, endpoint arguments)
TILES = [
    (
        ("factory.record",),
        "Record hourly output",
        "Good pieces, rejects and stops for your line.",
        "monitor-smartphone",
        "shopfloor.floor",
        {},
    ),
    (
        ("factory.record", "quality.inspect"),
        "Quality check",
        "Pieces checked and defects found.",
        "shield-check",
        "shopfloor.floor",
        {},
    ),
    (
        ("factory.record",),
        "Scan a bundle",
        "Issue a bundle to a line or mark it sewn.",
        "tag",
        "shopfloor.bundles",
        {},
    ),
    (
        ("factory.record",),
        "Rolls and dye batches",
        "Record rolls, load and finish batches.",
        "package",
        "shopfloor.batches",
        {},
    ),
    (
        ("factory.maintain",),
        "Report a breakdown",
        "A machine stopped? Tell maintenance here.",
        "alert-triangle",
        "maintenance.overview",
        {},
    ),
    (
        ("factory.maintain",),
        "Maintenance jobs",
        "Open tickets and preventive work due.",
        "key-round",
        "maintenance.overview",
        {},
    ),
    (
        ("factory.plan",),
        "Planning board",
        "Which department is full, and which orders are late.",
        "calendar",
        "planning.board",
        {},
    ),
    (
        ("factory.plan",),
        "Production orders",
        "Add an order and see when it will finish.",
        "clipboard-check",
        "planning.orders",
        {},
    ),
    (
        ("factory.plan",),
        "Line balancing",
        "Share the work evenly on each sewing line.",
        "ruler",
        "balancing.lines",
        {},
    ),
    (
        ("quality.inspect", "case.prepare"),
        "Investigations",
        "Trace a problem lot to every shipment.",
        "scan-search",
        "recall.dashboard",
        {},
    ),
    (
        ("factory.read",),
        "Factory map",
        "See every department working, live.",
        "activity",
        "insights.map",
        {},
    ),
    (
        ("factory.read",),
        "Dashboard",
        "Capacity, efficiency, downtime and orders at risk.",
        "layout-dashboard",
        "insights.board",
        {},
    ),
    (
        ("factory.read",),
        "Alerts",
        "Problems the factory checks found.",
        "alert-triangle",
        "insights.listing",
        {},
    ),
    (
        ("access.manage",),
        "Team and access",
        "Give each person the right job role.",
        "users",
        "home.team",
        {},
    ),
]


@bp.get("/home")
@login_required
def index(company_id):
    member = membership_for(company_id)
    if member is None:
        abort(404)
    codes = jobroles.display_codes(company_id)
    tiles = [
        (title, about, icon, url_for(endpoint, company_id=company_id, **args))
        for need, title, about, icon, endpoint, args in TILES
        if set(need) & codes
    ]
    alerts = 0
    if "factory.read" in codes:
        alerts = db.session.scalar(
            select(func.count(FactoryAlert.id)).where(
                FactoryAlert.organization_id == company_id, FactoryAlert.status != "resolved"
            )
        )
    preview = jobroles.preview_role(company_id)
    return render_template(
        "home.html",
        company_id=company_id,
        company=db.session.get(Organization, company_id),
        tiles=tiles,
        alerts=alerts,
        roles=[jobroles.ROLE_INFO[preview][0]] if preview else role_names(company_id, member.id),
        job_roles=jobroles.JOB_ROLES,
        can_preview=allowed(company_id, "access.manage"),
        preview=preview,
        form=FlaskForm(),
        first_name=(current_user.display_name or "").split(" ")[0],
    )


@bp.post("/preview")
@login_required
def preview(company_id):
    require(company_id, "access.manage")
    if not FlaskForm().validate_on_submit():
        abort(400)
    try:
        jobroles.set_preview(company_id, request.form.get("role") or None)
    except DomainError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("home.index", company_id=company_id), 303)


# ---------- Team: who does which job ----------


def team_context(company_id):
    require(company_id, "access.manage")
    return {"company_id": company_id, "company": db.session.get(Organization, company_id)}


@bp.get("/team")
@login_required
def team(company_id):
    ctx = team_context(company_id)
    actor = membership_for(company_id)
    rows = db.session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == company_id, Membership.archived_at.is_(None))
        .order_by(Membership.status, User.display_name)
    ).all()
    roles = db.session.scalars(
        select(Role)
        .where(Role.organization_id == company_id, Role.archived_at.is_(None))
        .order_by(Role.name)
    ).all()
    assigned = {
        membership_id: role_id
        for membership_id, role_id in db.session.execute(
            select(MembershipRole.membership_id, MembershipRole.role_id).where(
                MembershipRole.organization_id == company_id
            )
        )
    }
    by_code = {r.code: r for r in roles}
    descriptions = {"owner": jobroles.OWNER_ABOUT} | {
        code: about for code, (_, about, _) in jobroles.ROLE_INFO.items()
    }
    return render_template(
        "team.html",
        rows=rows,
        roles=[r for r in roles if access.grantable(r, actor)],
        role_names={r.id: r for r in roles},
        assigned=assigned,
        descriptions=descriptions,
        missing=[name for code, name, *_ in jobroles.JOB_ROLES if code not in by_code],
        me=actor.id,
        form=FlaskForm(),
        **ctx,
    )


@bp.post("/team/roles")
@login_required
def install_roles(company_id):
    team_context(company_id)
    if not FlaskForm().validate_on_submit():
        abort(400)
    created, skipped, _ = jobroles.install(company_id)
    if created:
        flash("Job roles added: " + ", ".join(created) + ".", "success")
    if skipped:
        flash(
            "Not added (they need permissions you do not hold yourself): "
            + ", ".join(skipped)
            + ".",
            "warning",
        )
    if not created and not skipped:
        flash("All job roles are already set up.", "success")
    return redirect(url_for("home.team", company_id=company_id), 303)


@bp.post("/team/<uuid:membership_id>")
@login_required
def change_role(company_id, membership_id):
    team_context(company_id)
    if not FlaskForm().validate_on_submit():
        abort(400)
    member = access.scoped(Membership, company_id, membership_id)
    try:
        role_id = uuid.UUID(request.form.get("role_id") or "")
        version = int(request.form.get("version") or -1)
    except ValueError:
        abort(400)
    status = "inactive" if request.form.get("status") == "inactive" else "active"
    try:
        access.change_membership(company_id, member.id, role_id, status, version)
    except access.AccessConflict as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    else:
        flash(
            f"{member.user.display_name} now has the new job role. They will be asked to sign "
            "in again.",
            "success",
        )
    return redirect(url_for("home.team", company_id=company_id), 303)


@bp.post("/team/invite")
@login_required
@limiter.limit("20 per hour", methods=["POST"])
def invite(company_id):
    team_context(company_id)
    if not FlaskForm().validate_on_submit():
        abort(400)
    try:
        access.invite(
            company_id,
            request.form.get("email") or "",
            uuid.UUID(request.form.get("role_id") or ""),
        )
    except ValueError:
        flash("Choose a job role for the invitation.", "danger")
    except access.AccessConflict as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    else:
        flash("Invitation sent.", "success")
    return redirect(url_for("home.team", company_id=company_id), 303)
