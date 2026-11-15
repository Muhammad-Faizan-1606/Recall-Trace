"""Factory Suite step 6: alerts and the management dashboard."""

from datetime import date

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import func, select

from app.blueprints.factory import context
from app.extensions import db
from app.forms import ActionForm
from app.models import Membership, User, now
from app.models.factory import (
    DyeBatch,
    FactoryAlert,
    Machine,
    OutputLog,
    ProductionOrder,
    WorkCenter,
)
from app.policies import allowed
from app.services import alerts, dashboard, factorymap
from app.services.business import DomainError
from app.services.jobroles import ALERT_ACTORS, require_any

bp = Blueprint("insights", __name__, url_prefix="/companies/<uuid:company_id>/factory")

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@bp.app_template_global("factory_alert_count")
def factory_alert_count(company_id):
    """Unresolved alerts for the sidebar badge (one indexed count)."""
    if not allowed(company_id, "factory.read"):
        return 0
    return db.session.scalar(
        select(func.count(FactoryAlert.id)).where(
            FactoryAlert.organization_id == company_id, FactoryAlert.status != "resolved"
        )
    )


def names(company_id, model, ids, attribute):
    ids = {value for value in ids if value}
    if not ids:
        return {}
    return {
        row.id: getattr(row, attribute)
        for row in db.session.scalars(
            select(model).where(model.organization_id == company_id, model.id.in_(ids))
        )
    }


def members(company_id):
    return db.session.execute(
        select(Membership.id, User.display_name)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == company_id,
            Membership.status == "active",
            Membership.archived_at.is_(None),
        )
        .order_by(User.display_name)
    ).all()


@bp.get("/alerts")
@login_required
def listing(company_id):
    ctx = context(company_id, area="dashboard")
    show = request.args.get("show", "open")
    if show not in ("open", "resolved"):
        abort(404)
    query = select(FactoryAlert).where(FactoryAlert.organization_id == company_id)
    if show == "open":
        rows = db.session.scalars(query.where(FactoryAlert.status != "resolved")).all()
        rows.sort(
            key=lambda a: (
                SEVERITY_ORDER[a.severity],
                a.cleared_at is not None,
                -a.first_seen_at.timestamp(),
            )
        )
    else:
        rows = db.session.scalars(
            query.where(FactoryAlert.status == "resolved")
            .order_by(FactoryAlert.resolved_at.desc())
            .limit(100)
        ).all()
    people = dict(members(company_id))
    last_check = db.session.scalar(
        select(func.max(FactoryAlert.last_seen_at)).where(
            FactoryAlert.organization_id == company_id
        )
    )
    return render_template(
        "factory/alerts.html",
        rows=rows,
        show=show,
        counts=alerts.open_counts(company_id),
        lines=names(company_id, WorkCenter, [a.work_center_id for a in rows], "code"),
        machines=names(company_id, Machine, [a.machine_id for a in rows], "asset_tag"),
        orders=names(
            company_id, ProductionOrder, [a.production_order_id for a in rows], "reference"
        ),
        batches=names(company_id, DyeBatch, [a.dye_batch_id for a in rows], "batch_number"),
        people=people,
        member_choices=list(people.items()),
        can_record=any(allowed(company_id, code) for code in ALERT_ACTORS),
        last_check=last_check,
        age=alerts.age_text,
        moment=now(),
        action_form=ActionForm(version="0"),
        **ctx,
    )


@bp.post("/alerts/check")
@login_required
def check(company_id):
    context(company_id, area="dashboard")
    if not ActionForm().validate_on_submit():
        abort(400)
    try:
        raised, cleared, active = alerts.scan(company_id)
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash(
            f"Checks run: {active} condition{'s' if active != 1 else ''} found, {raised} new, "
            f"{cleared} cleared since the last check.",
            "success",
        )
    return redirect(url_for("insights.listing", company_id=company_id), 303)


@bp.post("/alerts/<uuid:alert_id>/<any(acknowledge, resolve):action>")
@login_required
def act(company_id, alert_id, action):
    context(company_id, area="dashboard")
    require_any(company_id, *ALERT_ACTORS)
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        if action == "acknowledge":
            alerts.acknowledge(
                company_id, alert_id, int(form.version.data), request.form.get("owner_id") or None
            )
            message = "Alert acknowledged."
        else:
            alerts.resolve(company_id, alert_id, int(form.version.data), request.form.get("note"))
            message = "Alert resolved."
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash(message, "success")
    return redirect(url_for("insights.listing", company_id=company_id), 303)


@bp.get("/dashboard")
@login_required
def board(company_id):
    ctx = context(company_id, area="dashboard")
    today = date.today()
    latest = db.session.scalar(
        select(func.max(OutputLog.day)).where(
            OutputLog.organization_id == company_id, OutputLog.day <= today
        )
    )
    figures = dashboard.build(company_id, today, latest or today)
    open_alerts = db.session.scalars(
        select(FactoryAlert).where(
            FactoryAlert.organization_id == company_id, FactoryAlert.status != "resolved"
        )
    ).all()
    open_alerts.sort(key=lambda a: (SEVERITY_ORDER[a.severity], -a.first_seen_at.timestamp()))
    return render_template(
        "factory/dashboard.html",
        b=figures,
        today=today,
        latest=latest,
        alerts=open_alerts[:6],
        counts=alerts.open_counts(company_id),
        **ctx,
    )


# ---------- The live factory map ----------


@bp.get("/map")
@login_required
def map(company_id):  # noqa: A001 - the page is the factory map
    ctx = context(company_id, area="dashboard")
    stations, flows, latest = factorymap.build(company_id)
    links = {
        key: url_for("insights.station", company_id=company_id, key=key)
        for key, _, departments in factorymap.STATIONS
        if departments
    }
    return render_template(
        "factory/map.html",
        stations=stations,
        flows={f.source: f for f in flows},
        links=links,
        latest=latest,
        **ctx,
    )


@bp.get("/map.json")
@login_required
def map_data(company_id):
    context(company_id, area="dashboard")
    stations, flows, _ = factorymap.build(company_id)
    response = jsonify(factorymap.as_json(stations, flows))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/map/<key>")
@login_required
def station(company_id, key):
    ctx = context(company_id, area="dashboard")
    found = next((s for s in factorymap.STATIONS if s[0] == key and s[2]), None)
    if found is None:
        abort(404)
    _, title, departments = found
    centers = factorymap.department_machines(company_id, departments)
    counts = {"active": 0, "idle": 0, "maintenance": 0, "decommissioned": 0}
    for _, machines in centers:
        for machine, _ in machines:
            counts[machine.status] = counts.get(machine.status, 0) + 1
    return render_template(
        "factory/station.html",
        title=title,
        key=key,
        centers=centers,
        counts=counts,
        **ctx,
    )
