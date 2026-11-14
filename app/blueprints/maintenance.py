"""Factory Suite step 7: maintenance tickets, the preventive schedule and reliability."""

from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import select

from app.blueprints.factory import context
from app.extensions import db
from app.forms import ActionForm
from app.models import now
from app.models.factory import Machine, MaintenancePlan, MaintenanceTicket, WorkCenter
from app.policies import allowed, require
from app.services import alerts, maintenance
from app.services.business import DomainError, scoped

bp = Blueprint("maintenance", __name__, url_prefix="/companies/<uuid:company_id>/factory")


def page_context(company_id):
    ctx = context(company_id)
    ctx["can_record"] = allowed(company_id, maintenance.PERMISSION)
    ctx["action_form"] = ActionForm(version="0")
    return ctx


def machine_names(company_id, ids):
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {
        m.id: m
        for m in db.session.scalars(
            select(Machine).where(Machine.organization_id == company_id, Machine.id.in_(ids))
        )
    }


def _guard(company_id):
    context(company_id)
    require(company_id, maintenance.PERMISSION)
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    return form


@bp.get("/maintenance")
@login_required
def overview(company_id):
    ctx = page_context(company_id)
    today = date.today()
    moment = now()
    open_tickets = maintenance.unfinished_tickets(company_id)
    due = maintenance.schedule(company_id, today)
    summary = {}
    for item in due:
        row = summary.setdefault(item.plan.id, [item.plan, 0, 0, item.due_on])
        if item.due_on < today:
            row[1] += 1
        else:
            row[2] += 1
        row[3] = min(row[3], item.due_on)
    chosen = request.args.get("plan")
    if chosen:
        shown = [d for d in due if str(d.plan.id) == chosen]
    else:
        shown = [d for d in due if d.due_on < today]
    reliability = maintenance.reliability(company_id, moment)
    worst = sorted(reliability.values(), key=lambda r: (-r.breakdowns, -r.down_hours))[:10]
    closed = [r.mttr for r in reliability.values() if r.mttr is not None]
    machines = machine_names(
        company_id, [t.machine_id for t in open_tickets] + [r.machine.id for r in worst]
    )
    centers = {
        c.id: c.code
        for c in db.session.scalars(
            select(WorkCenter).where(WorkCenter.organization_id == company_id)
        )
    }
    breakdowns = sum(r.breakdowns for r in reliability.values())
    return render_template(
        "factory/maintenance.html",
        open_tickets=open_tickets,
        due=due,
        shown=shown,
        chosen=chosen,
        plan_summary=sorted(summary.values(), key=lambda r: (-r[1], r[3])),
        overdue=[d for d in due if d.due_on < today],
        worst=worst,
        machines=machines,
        centers=centers,
        classes=maintenance.class_names(company_id),
        mttr=(sum(closed) / len(closed)) if closed else None,
        breakdowns=breakdowns,
        down_hours=sum(r.down_hours for r in reliability.values()),
        today=today,
        moment=moment,
        hours=maintenance.hours,
        window=maintenance.WINDOW_DAYS,
        **ctx,
    )


@bp.post("/maintenance/breakdowns")
@login_required
def breakdown(company_id):
    _guard(company_id)
    try:
        ticket = maintenance.report_breakdown(company_id, request.form.to_dict())
    except DomainError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("maintenance.overview", company_id=company_id), 303)
    alerts.scan_quietly(company_id)
    flash(
        f"Breakdown {ticket.number} reported; the machine is out of planned capacity until it is closed.",
        "success",
    )
    return redirect(url_for("maintenance.ticket", company_id=company_id, ticket_id=ticket.id), 303)


@bp.post("/maintenance/jobs")
@login_required
def plan_job(company_id):
    _guard(company_id)
    try:
        ticket = maintenance.plan_job(
            company_id, request.form.get("plan_id"), request.form.get("machine_id")
        )
    except DomainError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("maintenance.overview", company_id=company_id), 303)
    alerts.scan_quietly(company_id)
    flash(
        f"Preventive job {ticket.number} opened. The machine keeps running until work starts.",
        "success",
    )
    return redirect(url_for("maintenance.ticket", company_id=company_id, ticket_id=ticket.id), 303)


@bp.get("/maintenance/tickets/<uuid:ticket_id>")
@login_required
def ticket(company_id, ticket_id):
    ctx = page_context(company_id)
    row = scoped(MaintenanceTicket, company_id, ticket_id)
    machine = scoped(Machine, company_id, row.machine_id)
    ctx["action_form"] = ActionForm(version=str(row.version))
    return render_template(
        "factory/ticket.html",
        t=row,
        machine=machine,
        center=scoped(WorkCenter, company_id, machine.work_center_id),
        plan=scoped(MaintenancePlan, company_id, row.plan_id) if row.plan_id else None,
        moment=now(),
        hours=maintenance.hours,
        **ctx,
    )


@bp.post("/maintenance/tickets/<uuid:ticket_id>/<any(start, close):action>")
@login_required
def ticket_action(company_id, ticket_id, action):
    form = _guard(company_id)
    try:
        if action == "start":
            maintenance.start(company_id, ticket_id, int(form.version.data))
            message = "Work started: the machine is in maintenance."
        else:
            maintenance.close(
                company_id,
                ticket_id,
                int(form.version.data),
                request.form.get("work_done"),
                request.form.get("parts_used"),
            )
            message = "Ticket closed: the machine is back in service and in planned capacity."
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        alerts.scan_quietly(company_id)
        flash(message, "success")
    return redirect(url_for("maintenance.ticket", company_id=company_id, ticket_id=ticket_id), 303)


@bp.get("/maintenance/machines/<uuid:machine_id>")
@login_required
def machine(company_id, machine_id):
    ctx = page_context(company_id)
    row = scoped(Machine, company_id, machine_id)
    tickets = db.session.scalars(
        select(MaintenanceTicket)
        .where(
            MaintenanceTicket.organization_id == company_id,
            MaintenanceTicket.machine_id == row.id,
        )
        .order_by(MaintenanceTicket.reported_at.desc())
    ).all()
    stats = maintenance.reliability(company_id, now(), machine_ids=[row.id]).get(row.id)
    plans = db.session.scalars(
        select(MaintenancePlan).where(
            MaintenancePlan.organization_id == company_id,
            MaintenancePlan.machine_class_id == row.machine_class_id,
            MaintenancePlan.archived_at.is_(None),
        )
    ).all()
    due = [d for d in maintenance.schedule(company_id, horizon_days=3650) if d.machine.id == row.id]
    return render_template(
        "factory/machine_maintenance.html",
        machine=row,
        center=scoped(WorkCenter, company_id, row.work_center_id),
        tickets=tickets,
        stats=stats,
        plans=plans,
        due=due,
        today=date.today(),
        hours=maintenance.hours,
        window=maintenance.WINDOW_DAYS,
        **ctx,
    )
