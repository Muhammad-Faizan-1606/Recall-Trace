"""Factory Suite step 3: production orders, the planning board and what-if previews."""

import math
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import select
from wtforms import IntegerField, SelectField, StringField
from wtforms.fields import DateField
from wtforms.fields.choices import SelectChoice
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange

from app.blueprints.factory import context
from app.extensions import db
from app.forms import ActionForm, trimmed
from app.models.factory import ProductionOrder, SiteTransitTime, Style, WorkCenter
from app.policies import require
from app.services import engineering, planning
from app.services.business import DomainError, scoped
from app.services.capacity import q as capacity_round

bp = Blueprint("planning", __name__, url_prefix="/companies/<uuid:company_id>/factory")

BOARD_DAYS = 28
PRIORITIES = [
    SelectChoice("1", "1 — most urgent"),
    SelectChoice("2", "2 — high"),
    SelectChoice("3", "3 — normal"),
    SelectChoice("4", "4 — low"),
    SelectChoice("5", "5 — fill-in"),
]


def capacity_q(value):
    return capacity_round(value, "0.1").normalize()


STAGE_NAMES = {
    "knitting": "Knitting",
    "dyeing": "Dyeing",
    "finishing": "Finishing",
    "cutting": "Cutting",
    "embellishment": "Printing",
    "sewing": "Sewing",
    "packing": "Packing",
}


class OrderForm(ActionForm):
    reference = StringField(
        "Order reference",
        validators=[DataRequired(), Length(max=40)],
        filters=[lambda value: trimmed(str(value)) if value is not None else value],
        description="The buyer's PO number or your production order number.",
    )
    style_id = SelectField(
        "Style",
        validators=[DataRequired()],
        description="Only styles with fabric and a published bulletin.",
    )
    quantity = IntegerField("Pieces", validators=[InputRequired(), NumberRange(1, 10_000_000)])
    colour = StringField(
        "Colour",
        validators=[DataRequired(), Length(max=60)],
        filters=[lambda value: trimmed(str(value)) if value is not None else value],
    )
    ex_factory_on = DateField(
        "Ex-factory date",
        validators=[DataRequired()],
        description="The day the goods must leave the factory.",
    )
    priority = SelectField(
        "Priority",
        choices=PRIORITIES,
        default="3",
        description="Orders are planned in priority order, then by date.",
    )
    sewing_lines = IntegerField(
        "Sewing lines",
        default=2,
        validators=[InputRequired(), NumberRange(1, 20)],
        description="How many lines share the sewing; more lines finish sooner.",
    )
    prints_per_piece = IntegerField(
        "Prints per piece",
        default=0,
        validators=[InputRequired(), NumberRange(0, 10)],
        description="Screen-print impressions per garment; 0 skips printing.",
    )


def orderable_styles(company_id):
    current = engineering.current_bulletins(company_id)
    rows = db.session.scalars(
        select(Style)
        .where(Style.organization_id == company_id, Style.archived_at.is_(None))
        .order_by(Style.code)
    ).all()
    return [SelectChoice(str(s.id), f"{s.code} — {s.name}") for s in rows if s.id in current]


def center_names(company_id):
    return {
        row.id: row
        for row in db.session.scalars(
            select(WorkCenter).where(WorkCenter.organization_id == company_id)
        )
    }


def heat(cap, used):
    """Utilisation bucket for a heat-map cell."""
    if cap <= 0:
        return "off", None
    percent = used / cap * 100
    bucket = (
        "u0"
        if used <= 0
        else "u1"
        if percent < 50
        else "u2"
        if percent < 85
        else "u3"
        if percent <= 100.5
        else "u4"
    )
    return bucket, percent


def slack(order):
    if order.planned_finish_on is None:
        return None
    return (order.ex_factory_on - order.planned_finish_on).days


# ---------- Planning board ----------


@bp.get("/planning")
@login_required
def board(company_id):
    ctx = context(company_id)
    try:
        offset = max(0, min(int(request.args.get("week", 0)), 26))
    except ValueError:
        offset = 0
    start = date.today() + timedelta(weeks=offset)
    span, departments, _ = planning.load_board(company_id, start, BOARD_DAYS)
    rows = [
        (
            department,
            planning.DEPARTMENT_UNIT[department],
            [(cap, used, *heat(cap, used)) for cap, used in cells],
        )
        for department, cells in departments
    ]
    orders = planning.open_orders(company_id)
    steps = planning.stored_steps(company_id, [o.id for o in orders])
    styles = {
        s.id: s
        for s in db.session.scalars(select(Style).where(Style.organization_id == company_id))
    }
    end = span[-1]
    gantt = []
    for order in orders:
        bars = []
        for stage, first, last, *_ in steps.get(order.id, []):
            if last < start or first > end:
                continue
            column = (max(first, start) - start).days + 1
            width = (min(last, end) - max(first, start)).days + 1
            bars.append((stage, column, width, first, last))
        marker = (order.ex_factory_on - start).days + 1
        gantt.append(
            (
                order,
                styles.get(order.style_id),
                bars,
                marker if 1 <= marker <= BOARD_DAYS else None,
                slack(order),
            )
        )
    busiest = None
    for department, _unit, cells in rows:
        cap = sum((c for c, *_ in cells[:14]), Decimal(0))
        used = sum((u for _, u, *_ in cells[:14]), Decimal(0))
        if cap and (busiest is None or used / cap > busiest[1]):
            busiest = (department, used / cap * 100)
    late = [o for o in orders if slack(o) is not None and slack(o) < 0]
    return render_template(
        "factory/board.html",
        span=span,
        rows=rows,
        gantt=gantt,
        offset=offset,
        today=date.today(),
        orders=orders,
        late=late,
        busiest=busiest,
        stage_names=STAGE_NAMES,
        released=sum(1 for o in orders if o.status == "released"),
        unplanned=sum(1 for o in orders if o.status == "draft"),
        action_form=ActionForm(version="1"),
        **ctx,
    )


@bp.get("/planning/<department>")
@login_required
def department(company_id, department):
    ctx = context(company_id)
    if department not in planning.DEPARTMENT_UNIT:
        abort(404)
    try:
        offset = max(0, min(int(request.args.get("week", 0)), 26))
    except ValueError:
        offset = 0
    start = date.today() + timedelta(weeks=offset)
    span, departments, centers = planning.load_board(company_id, start, BOARD_DAYS)
    rows = [
        (center, [(cap, used, *heat(cap, used)) for cap, used in cells])
        for center, cells in centers.values()
        if center.department == department
    ]
    return render_template(
        "factory/board_department.html",
        department=department,
        unit=planning.DEPARTMENT_UNIT[department],
        span=span,
        rows=rows,
        offset=offset,
        stage_names=STAGE_NAMES,
        **ctx,
    )


@bp.post("/planning/replan")
@login_required
def replan(company_id):
    context(company_id)
    require(company_id, "factory.manage")
    if not ActionForm().validate_on_submit():
        abort(400)
    try:
        plans = planning.replan(company_id)
        db.session.commit()
    except DomainError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    else:
        flash(f"{len(plans)} open orders re-planned against current capacity.", "success")
    return redirect(url_for("planning.board", company_id=company_id), code=303)


# ---------- Production orders ----------


@bp.get("/orders")
@login_required
def orders(company_id):
    ctx = context(company_id)
    rows = db.session.scalars(
        select(ProductionOrder)
        .where(ProductionOrder.organization_id == company_id)
        .order_by(
            ProductionOrder.status.in_(("completed", "cancelled")),
            ProductionOrder.priority,
            ProductionOrder.ex_factory_on,
        )
    ).all()
    styles = {
        s.id: s
        for s in db.session.scalars(select(Style).where(Style.organization_id == company_id))
    }
    return render_template(
        "factory/orders.html",
        rows=[(o, styles.get(o.style_id), slack(o)) for o in rows],
        **ctx,
    )


def order_editor(company_id, order_id=None):
    ctx = context(company_id)
    require(company_id, "factory.manage")
    order = scoped(ProductionOrder, company_id, order_id) if order_id else None
    if order is not None and order.status not in ("draft", "planned"):
        flash("Released, completed and cancelled orders cannot be edited.", "danger")
        return redirect(url_for("planning.order", company_id=company_id, order_id=order.id))
    form = OrderForm(obj=order)
    form.style_id.choices = orderable_styles(company_id)
    if request.method == "GET":
        form.version.data = str(order.version if order else 0)
        if order is not None:
            form.style_id.data = str(order.style_id)
            form.priority.data = str(order.priority)
        else:
            form.ex_factory_on.data = date.today() + timedelta(days=30)
    status = 200
    if form.validate_on_submit():
        try:
            saved = planning.save_order(
                company_id, form.data, order_id, int(form.version.data) if order_id else None
            )
        except DomainError as exc:
            flash(str(exc), "danger")
            status = 409
        else:
            flash("Order saved and every open order re-planned.", "success")
            return redirect(
                url_for("planning.order", company_id=company_id, order_id=saved.id), code=303
            )
    elif request.method == "POST":
        status = 422
    return render_template(
        "factory/form.html",
        title="Edit production order" if order else "New production order",
        form=form,
        submit="Save and plan",
        back=url_for("planning.orders", company_id=company_id),
        **ctx,
    ), status


@bp.route("/orders/new", methods=["GET", "POST"])
@login_required
def order_new(company_id):
    return order_editor(company_id)


@bp.route("/orders/<uuid:order_id>/edit", methods=["GET", "POST"])
@login_required
def order_edit(company_id, order_id):
    return order_editor(company_id, order_id)


def what_if(company_id, order):
    """Preview a change to lines or priority without saving anything."""
    try:
        lines = int(request.args.get("lines", order.sewing_lines))
        priority = int(request.args.get("priority", order.priority))
    except ValueError:
        return None
    if (lines, priority) == (order.sewing_lines, order.priority) or order.status not in (
        "draft",
        "planned",
    ):
        return None
    lines = max(1, min(lines, 20))
    priority = max(1, min(priority, 5))
    plans, candidates, _ = planning.simulate(
        company_id, overrides={order.id: {"sewing_lines": lines, "priority": priority}}
    )
    plan = plans.get(order.id)
    newly_late = []
    for other in candidates:
        if other.id == order.id:
            continue
        finish = plans[other.id].finish
        before_late = other.planned_finish_on and other.planned_finish_on > other.ex_factory_on
        if finish and finish > other.ex_factory_on and not before_late:
            newly_late.append(other.reference)
    return {
        "lines": lines,
        "priority": priority,
        "finish": plan.finish if plan else None,
        "slack": (order.ex_factory_on - plan.finish).days if plan and plan.finish else None,
        "newly_late": newly_late,
    }


@bp.get("/orders/<uuid:order_id>")
@login_required
def order(company_id, order_id):
    ctx = context(company_id)
    row = scoped(ProductionOrder, company_id, order_id)
    style = scoped(Style, company_id, row.style_id)
    loads, relaxation, sam = planning.loads_for(company_id, row)
    steps = planning.stored_steps(company_id, [row.id]).get(row.id, [])
    centers = center_names(company_id)
    transit = {
        (t.from_site_id, t.to_site_id): t.hours
        for t in db.session.scalars(
            select(SiteTransitTime).where(SiteTransitTime.organization_id == company_id)
        )
    }
    timeline = []
    previous_end = previous_site = None
    for stage, first, last, quantity, unit, center_ids in steps:
        names = [centers[c] for c in center_ids if c in centers]
        site = names[0].site_id if names else None
        if previous_end is not None and (first - previous_end).days > 0:
            waited = (first - previous_end).days
            hours = Decimal(0)
            if previous_site is not None and site != previous_site:
                hours = Decimal(transit.get((previous_site, site), planning.DEFAULT_TRANSIT_HOURS))
            parts = [f"{capacity_q(hours)} h transit"] if hours else []
            if stage == "cutting" and relaxation:
                parts.append(f"{relaxation} h fabric relaxation")
                hours += relaxation
            needed = math.ceil(hours / 24) if hours else 0
            if waited > needed:
                extra = waited - needed
                parts.append(
                    f"then {extra} day{'s' if extra != 1 else ''} waiting for "
                    f"{STAGE_NAMES[stage].lower()} capacity or a shift"
                )
            timeline.append(("wait", waited, ", ".join(parts) or "the next shift"))
        timeline.append(
            (
                "stage",
                stage,
                first,
                last,
                quantity,
                unit,
                names,
                loads.get(stage).working if loads.get(stage) else "",
            )
        )
        previous_end, previous_site = last, site
    problems = []
    if row.status in ("draft", "planned"):
        plans, _, _ = planning.simulate(company_id)
        if row.id in plans:
            problems = plans[row.id].problems
    fabric_kg = loads["dyeing"].quantity / planning.DYE_FACTOR if "dyeing" in loads else Decimal(0)
    return render_template(
        "factory/order.html",
        order=row,
        style=style,
        sam=sam,
        loads=loads,
        relaxation=relaxation,
        timeline=timeline,
        slack=slack(row),
        problems=problems,
        fabric_kg=fabric_kg,
        preview=what_if(company_id, row),
        stage_names=STAGE_NAMES,
        priorities=PRIORITIES,
        action_form=ActionForm(version=str(row.version)),
        **ctx,
    )


@bp.post("/orders/<uuid:order_id>/apply")
@login_required
def order_apply(company_id, order_id):
    """Apply a previewed what-if (sewing lines and priority) and re-plan."""
    context(company_id)
    require(company_id, "factory.manage")
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    row = scoped(ProductionOrder, company_id, order_id)
    values = {c.name: getattr(row, c.name) for c in ProductionOrder.__table__.columns}
    values.update(sewing_lines=request.form.get("lines"), priority=request.form.get("priority"))
    try:
        planning.save_order(company_id, values, row.id, int(form.version.data))
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash("Change applied and every open order re-planned.", "success")
    return redirect(url_for("planning.order", company_id=company_id, order_id=order_id), code=303)


@bp.post("/orders/<uuid:order_id>/<any(release, complete, cancel):action>")
@login_required
def order_action(company_id, order_id, action):
    context(company_id)
    require(company_id, "factory.manage")
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        planning.transition(company_id, order_id, action, int(form.version.data))
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash(
            {
                "release": "Order released: its plan is now fixed and later orders plan around it.",
                "complete": "Order marked complete.",
                "cancel": "Order cancelled and its capacity freed.",
            }[action],
            "success",
        )
    return redirect(url_for("planning.order", company_id=company_id, order_id=order_id), code=303)
