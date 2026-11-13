"""Factory Suite step 5: the shop floor (tablet-friendly) and batch cards."""

import math
from datetime import date, timedelta
from decimal import Decimal

import segno
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from markupsafe import Markup
from sqlalchemy import func, select

from app.blueprints.factory import context
from app.extensions import db
from app.forms import ActionForm
from app.models.factory import (
    CutBundle,
    DowntimeEvent,
    DowntimeReason,
    DyeBatch,
    KnitRoll,
    Machine,
    OutputLog,
    ProductionOrder,
    ShiftPattern,
    Style,
    WorkCenter,
)
from app.models.master import Site
from app.policies import allowed, require
from app.services import balancing, shopfloor
from app.services.business import DomainError, scoped

bp = Blueprint("shopfloor", __name__, url_prefix="/companies/<uuid:company_id>/factory")


@bp.app_template_global("day_shift")
def day_shift(day, offset):
    return (day + timedelta(days=offset)).isoformat()


def floor_context(company_id):
    ctx = context(company_id)
    ctx["can_record"] = allowed(company_id, shopfloor.PERMISSION)
    ctx["action_form"] = ActionForm(version="0")
    return ctx


def chosen_day():
    raw = request.args.get("day")
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        abort(404)


def _record_guard(company_id):
    context(company_id)
    require(company_id, shopfloor.PERMISSION)
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    return form


def styles_by_order(company_id, orders):
    ids = {o.style_id for o in orders}
    if not ids:
        return {}
    return {
        s.id: s
        for s in db.session.scalars(
            select(Style).where(Style.organization_id == company_id, Style.id.in_(ids))
        )
    }


def line_targets(company_id, lines):
    """{line id: (balance, style, pieces per hour at plan, planned efficiency, slots)}."""
    current = balancing.current_balances(company_id)
    figures = balancing.summaries(company_id, list(current.values()))
    styles = {}
    if current:
        from app.blueprints.balancing import style_names

        styles = style_names(company_id, {b.bulletin_id for b in current.values()})
    patterns = {
        p.id: p
        for p in db.session.scalars(
            select(ShiftPattern).where(ShiftPattern.organization_id == company_id)
        )
    }
    result = {}
    for line in lines:
        minutes = balancing.productive_minutes(patterns[line.shift_pattern_id])
        slots = max(1, math.ceil(minutes / 60))
        balance = current.get(line.id)
        per_hour = None
        if balance is not None and figures.get(balance.id) and minutes:
            per_hour = figures[balance.id][2] / minutes * 60
        planned = Decimal(balance.target_efficiency if balance else line.target_efficiency)
        if balance is not None and figures.get(balance.id) and figures[balance.id][1]:
            # A line paced by its bottleneck earns target × balance efficiency at best.
            planned = planned * figures[balance.id][1] / 100
        result[line.id] = (
            balance,
            styles.get(balance.bulletin_id) if balance else None,
            per_hour,
            planned,
            slots,
        )
    return result


def expected(day_figures, per_hour):
    """Pieces the plan expected for the minutes actually logged."""
    if per_hour is None:
        return None
    minutes = sum(row.minutes for _, row, _ in day_figures.hours)
    return per_hour * minutes / 60


# ---------- Shop floor ----------


@bp.get("/floor")
@login_required
def floor(company_id):
    ctx = floor_context(company_id)
    day = chosen_day()
    fallback = False
    if not request.args.get("day"):
        latest = db.session.scalar(
            select(func.max(OutputLog.day)).where(
                OutputLog.organization_id == company_id, OutputLog.day <= day
            )
        )
        if latest is not None and latest < day:
            day, fallback = latest, True
    lines = balancing.sewing_lines(company_id)
    days = shopfloor.floor(company_id, day, [line.id for line in lines])
    targets = line_targets(company_id, lines)
    sites = {
        s.id: s for s in db.session.scalars(select(Site).where(Site.organization_id == company_id))
    }
    grouped = {}
    total = shopfloor.Day()
    for line in lines:
        figures = days[line.id]
        target = targets[line.id]
        grouped.setdefault(line.site_id, []).append(
            (line, figures, target, expected(figures, target[2]))
        )
        total.good += figures.good
        total.rejects += figures.rejects
        total.earned += figures.earned
        total.clock += figures.clock
        total.off_standard += figures.off_standard
        total.downtime.extend(figures.downtime)
    reporting = sum(1 for line in lines if days[line.id].hours)
    return render_template(
        "factory/floor.html",
        day=day,
        today=date.today(),
        groups=[(sites.get(site_id), items) for site_id, items in grouped.items()],
        total=total,
        reporting=reporting,
        lines=len(lines),
        fallback=fallback,
        **ctx,
    )


@bp.get("/floor/<uuid:line_id>")
@login_required
def line_day(company_id, line_id):
    ctx = floor_context(company_id)
    line = scoped(WorkCenter, company_id, line_id)
    if line.department != "sewing":
        abort(404)
    day = chosen_day()
    figures = shopfloor.line_day(company_id, line.id, day)
    balance, style, per_hour, planned, slots = line_targets(company_id, [line])[line.id]
    orders = shopfloor.running_orders(company_id)
    styles = styles_by_order(company_id, orders)
    reasons = db.session.scalars(
        select(DowntimeReason)
        .where(DowntimeReason.organization_id == company_id, DowntimeReason.archived_at.is_(None))
        .order_by(DowntimeReason.category, DowntimeReason.code)
    ).all()
    machines = db.session.scalars(
        select(Machine)
        .where(
            Machine.organization_id == company_id,
            Machine.work_center_id == line.id,
            Machine.archived_at.is_(None),
        )
        .order_by(Machine.asset_tag)
    ).all()
    logged = {row.hour for _, row, _ in figures.hours}
    next_hour = next((h for h in range(1, 25) if h not in logged), None)
    last = figures.hours[-1][1] if figures.hours else None
    stations = None
    if balance is not None:
        stations = balancing.summaries(company_id, [balance]).get(balance.id, (None,))[0]
    order_names = (
        {
            o.id: o
            for o in db.session.scalars(
                select(ProductionOrder).where(
                    ProductionOrder.organization_id == company_id,
                    ProductionOrder.id.in_(
                        {row.production_order_id for _, row, _ in figures.hours}
                    ),
                )
            )
        }
        if figures.hours
        else {}
    )
    default_order = (
        last.production_order_id
        if last
        else next((o.id for o in orders if style is not None and o.style_id == style.id), None)
    )
    target_so_far = expected(figures, per_hour)
    return render_template(
        "factory/line_day.html",
        line=line,
        site=db.session.get(Site, line.site_id),
        day=day,
        today=date.today(),
        figures=figures,
        balance=balance,
        style=style,
        per_hour=per_hour,
        planned=planned,
        slots=range(
            1,
            (
                max(next_hour or 1, max(logged, default=0))
                if day == date.today()
                else max(slots, max(logged, default=0))
            )
            + 1,
        ),
        hours={row.hour: (original, row, corrected) for original, row, corrected in figures.hours},
        orders=orders,
        order_styles=styles,
        order_names=order_names,
        default_order=default_order,
        default_operators=last.operators if last else (stations or 20),
        next_hour=next_hour,
        reasons=reasons,
        machines=machines,
        target_so_far=target_so_far,
        hundred=Decimal(100),
        **ctx,
    )


def _back_to_line(company_id, line_id, day):
    return redirect(
        url_for("shopfloor.line_day", company_id=company_id, line_id=line_id, day=day), 303
    )


@bp.post("/floor/<uuid:line_id>/output")
@login_required
def output_new(company_id, line_id):
    _record_guard(company_id)
    values = request.form.to_dict()
    try:
        row = shopfloor.record_output(company_id, line_id, values)
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash(
            f"Hour {row.hour} recorded: {row.good_pieces:,} good, {row.rejects} rejects.", "success"
        )
    return _back_to_line(company_id, line_id, values.get("day") or date.today().isoformat())


@bp.post("/floor/<uuid:line_id>/downtime")
@login_required
def downtime_new(company_id, line_id):
    _record_guard(company_id)
    values = request.form.to_dict()
    try:
        row = shopfloor.record_downtime(company_id, line_id, values)
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash(f"{row.minutes} minutes of downtime recorded.", "success")
    return _back_to_line(company_id, line_id, values.get("day") or date.today().isoformat())


@bp.route("/floor/output/<uuid:log_id>", methods=["GET", "POST"])
@login_required
def output_entry(company_id, log_id):
    ctx = floor_context(company_id)
    row = scoped(OutputLog, company_id, log_id)
    original_id = row.corrects_id or row.id
    if request.method == "POST":
        _record_guard(company_id)
        try:
            shopfloor.correct_output(company_id, original_id, request.form.to_dict())
        except DomainError as exc:
            flash(str(exc), "danger")
            return redirect(request.url, 303)
        flash("Hour corrected. The original entry is kept in its history.", "success")
        return _back_to_line(company_id, row.work_center_id, row.day.isoformat())
    rows = shopfloor.history(company_id, OutputLog, original_id)
    current = shopfloor.effective(rows)[original_id]
    orders = {
        o.id: o
        for o in db.session.scalars(
            select(ProductionOrder).where(
                ProductionOrder.organization_id == company_id,
                ProductionOrder.id.in_({r.production_order_id for r in rows}),
            )
        )
    }
    running = shopfloor.running_orders(company_id)
    return render_template(
        "factory/output_entry.html",
        line=scoped(WorkCenter, company_id, row.work_center_id),
        rows=rows,
        current=current,
        orders=orders,
        running=running,
        **ctx,
    )


@bp.route("/floor/downtime/<uuid:event_id>", methods=["GET", "POST"])
@login_required
def downtime_entry(company_id, event_id):
    ctx = floor_context(company_id)
    row = scoped(DowntimeEvent, company_id, event_id)
    original_id = row.corrects_id or row.id
    if request.method == "POST":
        _record_guard(company_id)
        try:
            shopfloor.correct_downtime(company_id, original_id, request.form.to_dict())
        except DomainError as exc:
            flash(str(exc), "danger")
            return redirect(request.url, 303)
        flash("Stop corrected. The original entry is kept in its history.", "success")
        return _back_to_line(company_id, row.work_center_id, row.day.isoformat())
    rows = shopfloor.history(company_id, DowntimeEvent, original_id)
    reasons = db.session.scalars(
        select(DowntimeReason)
        .where(DowntimeReason.organization_id == company_id)
        .order_by(DowntimeReason.category, DowntimeReason.code)
    ).all()
    machines = db.session.scalars(
        select(Machine)
        .where(Machine.organization_id == company_id, Machine.work_center_id == row.work_center_id)
        .order_by(Machine.asset_tag)
    ).all()
    return render_template(
        "factory/downtime_entry.html",
        line=scoped(WorkCenter, company_id, row.work_center_id),
        rows=rows,
        current=shopfloor.effective(rows)[original_id],
        reasons=reasons,
        reason_names={r.id: r for r in reasons},
        machines=machines,
        machine_names={m.id: m.asset_tag for m in machines},
        **ctx,
    )


# ---------- Knit rolls and dye batches ----------


def machines_in(company_id, department):
    return db.session.scalars(
        select(Machine)
        .join(
            WorkCenter,
            (WorkCenter.id == Machine.work_center_id)
            & (WorkCenter.organization_id == Machine.organization_id),
        )
        .where(
            Machine.organization_id == company_id,
            WorkCenter.department == department,
            Machine.archived_at.is_(None),
            Machine.status != "decommissioned",
        )
        .order_by(Machine.asset_tag)
    ).all()


def open_orders(company_id):
    return db.session.scalars(
        select(ProductionOrder)
        .where(
            ProductionOrder.organization_id == company_id,
            ProductionOrder.status.in_(("planned", "released")),
        )
        .order_by(ProductionOrder.reference)
    ).all()


@bp.route("/rolls", methods=["GET", "POST"])
@login_required
def rolls(company_id):
    ctx = floor_context(company_id)
    if request.method == "POST":
        _record_guard(company_id)
        try:
            row = shopfloor.record_roll(company_id, request.form.to_dict())
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            flash(f"Roll {row.roll_number} recorded ({row.kg.normalize()} kg).", "success")
        return redirect(url_for("shopfloor.rolls", company_id=company_id), 303)
    page = db.paginate(
        select(KnitRoll)
        .where(KnitRoll.organization_id == company_id)
        .order_by(KnitRoll.knitted_on.desc(), KnitRoll.roll_number.desc()),
        per_page=50,
        max_per_page=50,
        error_out=False,
    )
    batches = {
        b.id: b
        for b in db.session.scalars(
            select(DyeBatch).where(
                DyeBatch.organization_id == company_id,
                DyeBatch.id.in_({r.dye_batch_id for r in page.items if r.dye_batch_id}),
            )
        )
    }
    machines = machines_in(company_id, "knitting")
    return render_template(
        "factory/rolls.html",
        page=page,
        batches=batches,
        machines=machines,
        machine_names={m.id: m.asset_tag for m in machines},
        orders=open_orders(company_id),
        order_names={o.id: o.reference for o in open_orders(company_id)},
        today=date.today(),
        waiting=len(shopfloor.loadable_rolls(company_id)),
        **ctx,
    )


@bp.route("/dye-batches", methods=["GET", "POST"])
@login_required
def batches(company_id):
    ctx = floor_context(company_id)
    if request.method == "POST":
        _record_guard(company_id)
        values = request.form.to_dict()
        values["roll_ids"] = request.form.getlist("roll_ids")
        try:
            batch, total, capacity = shopfloor.load_batch(company_id, values)
        except DomainError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("shopfloor.batches", company_id=company_id), 303)
        flash(f"Batch {batch.batch_number} loaded: {total} kg.", "success")
        if total < capacity / 2:
            flash(
                f"The vessel is under half full ({total} of {capacity.normalize()} kg); "
                "water, dyes and steam are spent on the full machine.",
                "warning",
            )
        return redirect(url_for("shopfloor.batch", company_id=company_id, batch_id=batch.id), 303)
    rows = db.session.scalars(
        select(DyeBatch)
        .where(DyeBatch.organization_id == company_id)
        .order_by(DyeBatch.created_at.desc())
        .limit(100)
    ).all()
    vessels = [m for m in machines_in(company_id, "dyeing") if m.status == "active"]
    all_vessels = {m.id: m for m in machines_in(company_id, "dyeing")}
    return render_template(
        "factory/batches.html",
        rows=rows,
        kg=shopfloor.batch_kg(company_id, [r.id for r in rows]),
        vessels=vessels,
        vessel_names={m.id: m.asset_tag for m in all_vessels.values()},
        rolls=shopfloor.loadable_rolls(company_id),
        orders=open_orders(company_id),
        **ctx,
    )


@bp.get("/dye-batches/<uuid:batch_id>")
@login_required
def batch(company_id, batch_id):
    ctx = floor_context(company_id)
    row = scoped(DyeBatch, company_id, batch_id)
    rolls_in = db.session.scalars(
        select(KnitRoll)
        .where(KnitRoll.organization_id == company_id, KnitRoll.dye_batch_id == row.id)
        .order_by(KnitRoll.roll_number)
    ).all()
    vessel = scoped(Machine, company_id, row.machine_id)
    order = (
        scoped(ProductionOrder, company_id, row.production_order_id)
        if row.production_order_id
        else None
    )
    bundles = db.session.scalar(
        select(func.count(CutBundle.id)).where(
            CutBundle.organization_id == company_id, CutBundle.dye_batch_id == row.id
        )
    )
    ctx["action_form"] = ActionForm(version=str(row.version))
    return render_template(
        "factory/batch.html",
        batch=row,
        rolls=rolls_in,
        total=sum((r.kg for r in rolls_in), Decimal(0)),
        vessel=vessel,
        capacity=Decimal(vessel.rated_value),
        order=order,
        bundles=bundles,
        **ctx,
    )


@bp.post("/dye-batches/<uuid:batch_id>/<any(start, passed, re_dye, rejected):step>")
@login_required
def batch_step(company_id, batch_id, step):
    form = _record_guard(company_id)
    try:
        shopfloor.batch_step(company_id, batch_id, step, int(form.version.data))
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash(
            {
                "start": "Batch started.",
                "passed": "Batch passed: its fabric can be cut.",
                "re_dye": "Batch needs re-dyeing: its rolls can be loaded into a new batch.",
                "rejected": "Batch rejected.",
            }[step],
            "success",
        )
    return redirect(url_for("shopfloor.batch", company_id=company_id, batch_id=batch_id), 303)


# ---------- Cut bundles ----------


@bp.route("/bundles", methods=["GET", "POST"])
@login_required
def bundles(company_id):
    ctx = floor_context(company_id)
    if request.method == "POST":
        _record_guard(company_id)
        try:
            made = shopfloor.cut_bundles(company_id, request.form.to_dict())
        except DomainError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("shopfloor.bundles", company_id=company_id), 303)
        flash(
            f"{len(made)} bundles cut: {made[0].bundle_number} to {made[-1].bundle_number}. "
            "Print their tickets from the list.",
            "success",
        )
        return redirect(
            url_for("shopfloor.bundles", company_id=company_id, order=made[0].production_order_id),
            303,
        )
    number = request.args.get("number")
    if number:
        found = shopfloor.find_bundle(company_id, number)
        if found is None:
            flash(f"No bundle {number.strip()[:40]} in this company.", "warning")
        else:
            return redirect(
                url_for("shopfloor.bundle", company_id=company_id, bundle_id=found.id), 303
            )
    query = select(CutBundle).where(CutBundle.organization_id == company_id)
    order_filter = request.args.get("order")
    selected = None
    if order_filter:
        selected = scoped(ProductionOrder, company_id, order_filter)
        query = query.where(CutBundle.production_order_id == selected.id)
    page = db.paginate(
        query.order_by(CutBundle.created_at.desc(), CutBundle.bundle_number.desc()),
        per_page=60,
        max_per_page=60,
        error_out=False,
    )
    released = shopfloor.running_orders(company_id)
    progress = db.session.execute(
        select(
            CutBundle.production_order_id,
            CutBundle.status,
            func.count(CutBundle.id),
            func.sum(CutBundle.pieces),
        )
        .where(CutBundle.organization_id == company_id)
        .group_by(CutBundle.production_order_id, CutBundle.status)
    ).all()
    by_order = {}
    for order_id, status, count, pieces in progress:
        by_order.setdefault(order_id, {})[status] = (count, pieces)
    order_names = (
        {
            o.id: o
            for o in db.session.scalars(
                select(ProductionOrder).where(
                    ProductionOrder.organization_id == company_id,
                    ProductionOrder.id.in_(
                        set(by_order) | {b.production_order_id for b in page.items}
                    ),
                )
            )
        }
        if by_order or page.items
        else {}
    )
    passed = db.session.scalars(
        select(DyeBatch)
        .where(DyeBatch.organization_id == company_id, DyeBatch.status == "passed")
        .order_by(DyeBatch.finished_at.desc())
        .limit(50)
    ).all()
    lines = {line.id: line for line in balancing.sewing_lines(company_id)}
    return render_template(
        "factory/bundles.html",
        page=page,
        selected=selected,
        released=released,
        by_order=by_order,
        order_names=order_names,
        passed=passed,
        lines=lines,
        **ctx,
    )


def ticket_svg(company_id, bundle):
    url = url_for("shopfloor.bundle", company_id=company_id, bundle_id=bundle.id, _external=True)
    code = segno.make(url, error="m")
    return Markup(
        code.svg_inline(
            scale=4, omitsize=True, title=f"Bundle {bundle.bundle_number}", svgclass="qr"
        )
    )


@bp.get("/bundles/<uuid:bundle_id>")
@login_required
def bundle(company_id, bundle_id):
    ctx = floor_context(company_id)
    row = scoped(CutBundle, company_id, bundle_id)
    order = scoped(ProductionOrder, company_id, row.production_order_id)
    ctx["action_form"] = ActionForm(version=str(row.version))
    return render_template(
        "factory/bundle.html",
        bundle=row,
        order=order,
        style=scoped(Style, company_id, order.style_id),
        batch=scoped(DyeBatch, company_id, row.dye_batch_id) if row.dye_batch_id else None,
        line=scoped(WorkCenter, company_id, row.issued_line_id) if row.issued_line_id else None,
        lines=balancing.sewing_lines(company_id),
        qr=ticket_svg(company_id, row),
        **ctx,
    )


@bp.get("/bundles/tickets")
@login_required
def tickets(company_id):
    """Printable tickets for one order's bundles that are still at cutting."""
    ctx = floor_context(company_id)
    order = scoped(ProductionOrder, company_id, request.args.get("order"))
    rows = db.session.scalars(
        select(CutBundle)
        .where(
            CutBundle.organization_id == company_id,
            CutBundle.production_order_id == order.id,
            CutBundle.status == "cut",
        )
        .order_by(CutBundle.bundle_number)
        .limit(shopfloor.MAX_BUNDLES)
    ).all()
    style = scoped(Style, company_id, order.style_id)
    return render_template(
        "factory/tickets.html",
        order=order,
        style=style,
        tickets=[(row, ticket_svg(company_id, row)) for row in rows],
        **ctx,
    )


@bp.post("/bundles/<uuid:bundle_id>/<any(issue, sewn):step>")
@login_required
def bundle_step(company_id, bundle_id, step):
    form = _record_guard(company_id)
    try:
        row = shopfloor.bundle_step(
            company_id, bundle_id, step, int(form.version.data), request.form.get("line_id")
        )
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash(
            f"Bundle {row.bundle_number} "
            + ("issued to the line." if step == "issue" else "marked sewn."),
            "success",
        )
    return redirect(url_for("shopfloor.bundle", company_id=company_id, bundle_id=bundle_id), 303)
