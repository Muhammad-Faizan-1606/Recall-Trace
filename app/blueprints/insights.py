"""Factory Suite step 6: alerts and the management dashboard."""

from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
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
from app.policies import allowed, require
from app.services import alerts, dashboard
from app.services.business import DomainError

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
    ctx = context(company_id)
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
        can_record=allowed(company_id, "factory.record"),
        last_check=last_check,
        age=alerts.age_text,
        moment=now(),
        action_form=ActionForm(version="0"),
        **ctx,
    )


@bp.post("/alerts/check")
@login_required
def check(company_id):
    context(company_id)
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
    context(company_id)
    require(company_id, "factory.record")
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
    ctx = context(company_id)
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
