"""Factory Suite step 4: sewing lines and line balancing screens."""

from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import select
from wtforms import DecimalField, IntegerField, SelectField, StringField
from wtforms.fields.choices import SelectChoice
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional

from app.blueprints.factory import context
from app.extensions import db
from app.forms import ActionForm, trimmed
from app.models.factory import LineBalance, OperationBulletin, Style, WorkCenter
from app.models.master import Site
from app.policies import require
from app.services import balancing, engineering
from app.services.business import DomainError, scoped
from app.services.capacity import AVAILABLE_STATUSES

bp = Blueprint("balancing", __name__, url_prefix="/companies/<uuid:company_id>/factory")


class BalanceForm(ActionForm):
    bulletin_id = SelectField(
        "Style",
        validators=[DataRequired()],
        description="The style's latest published operation bulletin is balanced.",
    )
    operators = IntegerField(
        "Operators",
        validators=[InputRequired(), NumberRange(1, balancing.MAX_STATIONS)],
        description="People available on the line, including helpers for manual work.",
    )
    target_efficiency = DecimalField(
        "Planned efficiency %",
        places=2,
        validators=[InputRequired(), NumberRange(1, 100)],
        description="How close to standard time the line works on this style.",
    )
    note = StringField(
        "Note",
        validators=[Optional(), Length(max=200)],
        filters=[lambda value: trimmed(str(value)) if value is not None else value],
    )


def bulletin_choices(company_id):
    current = engineering.current_bulletins(company_id)
    styles = {
        s.id: s
        for s in db.session.scalars(
            select(Style).where(Style.organization_id == company_id, Style.archived_at.is_(None))
        )
    }
    return [
        SelectChoice(str(bulletin.id), f"{styles[style_id].code} — {styles[style_id].name}")
        for style_id, bulletin in sorted(
            current.items(), key=lambda pair: styles[pair[0]].code if pair[0] in styles else ""
        )
        if style_id in styles
    ]


def style_names(company_id, bulletin_ids):
    if not bulletin_ids:
        return {}
    rows = db.session.execute(
        select(OperationBulletin.id, Style)
        .join(
            Style,
            (Style.id == OperationBulletin.style_id)
            & (Style.organization_id == OperationBulletin.organization_id),
        )
        .where(
            OperationBulletin.organization_id == company_id,
            OperationBulletin.id.in_(list(bulletin_ids)),
        )
    ).all()
    return dict(rows)


@bp.get("/lines")
@login_required
def lines(company_id):
    ctx = context(company_id)
    rows = balancing.sewing_lines(company_id)
    current = balancing.current_balances(company_id)
    drafts = {
        b.work_center_id: b
        for b in db.session.scalars(
            select(LineBalance).where(
                LineBalance.organization_id == company_id, LineBalance.status == "draft"
            )
        )
    }
    figures = balancing.summaries(company_id, list(current.values()))
    styles = style_names(company_id, {b.bulletin_id for b in current.values()})
    sites = {
        s.id: s for s in db.session.scalars(select(Site).where(Site.organization_id == company_id))
    }
    grouped = {}
    for line in rows:
        balance = current.get(line.id)
        grouped.setdefault(line.site_id, []).append(
            (
                line,
                balance,
                styles.get(balance.bulletin_id) if balance else None,
                figures.get(balance.id) if balance else None,
                drafts.get(line.id),
            )
        )
    running = [f for f in figures.values() if f[0]]
    return render_template(
        "factory/lines.html",
        groups=[(sites.get(site_id), items) for site_id, items in grouped.items()],
        total=len(rows),
        running=len(running),
        average=(sum(f[1] for f in running) / len(running)) if running else None,
        pieces=sum(f[2] for f in running),
        weakest=min(
            ((f[1], balance_id) for balance_id, f in figures.items() if f[0]), default=None
        ),
        **ctx,
    )


@bp.get("/lines/<uuid:line_id>")
@login_required
def line(company_id, line_id):
    from app.services.factory import machines_by_center

    ctx = context(company_id)
    row = scoped(WorkCenter, company_id, line_id)
    if row.department != "sewing":
        abort(404)
    history = db.session.scalars(
        select(LineBalance)
        .where(LineBalance.organization_id == company_id, LineBalance.work_center_id == row.id)
        .order_by(LineBalance.revision.desc())
    ).all()
    styles = style_names(company_id, {b.bulletin_id for b in history})
    figures = balancing.summaries(company_id, [b for b in history if b.status == "published"])
    machines = machines_by_center(company_id, [row.id]).get(row.id, [])
    mix = {}
    for machine, machine_class in machines:
        usable, total = mix.get(machine_class.name, (0, 0))
        mix[machine_class.name] = (
            usable + (machine.status in AVAILABLE_STATUSES),
            total + 1,
        )
    form = None
    has_draft = any(b.status == "draft" for b in history)
    if ctx["can_manage"] and not has_draft:
        form = BalanceForm()
        form.bulletin_id.choices = bulletin_choices(company_id)
        form.operators.data = sum(usable for usable, _ in mix.values()) or 20
        form.target_efficiency.data = row.target_efficiency
        form.version.data = "0"
    site = db.session.get(Site, row.site_id)
    return render_template(
        "factory/line.html",
        line=row,
        site=site,
        history=history,
        styles=styles,
        figures=figures,
        current=next((b for b in history if b.status == "published"), None),
        mix=sorted(mix.items()),
        form=form,
        **ctx,
    )


@bp.post("/lines/<uuid:line_id>/balances")
@login_required
def balance_new(company_id, line_id):
    context(company_id)
    require(company_id, "factory.manage")
    form = BalanceForm()
    form.bulletin_id.choices = bulletin_choices(company_id)
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for error in errors:
                flash(error, "danger")
        return redirect(url_for("balancing.line", company_id=company_id, line_id=line_id), 303)
    try:
        balance, short = balancing.create_balance(
            company_id,
            line_id,
            form.bulletin_id.data,
            form.operators.data,
            form.target_efficiency.data,
            form.note.data,
        )
    except DomainError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("balancing.line", company_id=company_id, line_id=line_id), 303)
    flash_short(short, "Draft balance laid out automatically. Adjust it, then publish.")
    return redirect(url_for("balancing.balance", company_id=company_id, balance_id=balance.id), 303)


def flash_short(short, message):
    flash(message, "success")
    if short:
        flash(
            "Not enough working machines on this line for: "
            + ", ".join(f"{count} × {name}" for name, count in sorted(short.items()))
            + ". Those stations have no machine yet.",
            "warning",
        )


@bp.get("/balances/<uuid:balance_id>")
@login_required
def balance(company_id, balance_id):
    ctx = context(company_id)
    row = scoped(LineBalance, company_id, balance_id)
    view = balancing.layout(company_id, row)
    site = db.session.get(Site, view.line.site_id)
    current = balancing.current_balances(company_id).get(row.work_center_id)
    return render_template(
        "factory/balance.html",
        view=view,
        balance=row,
        site=site,
        m=view.metrics,
        is_current=current is not None and current.id == row.id,
        action_form=ActionForm(version=str(row.version)),
        hundred=Decimal(100),
        **ctx,
    )


def _guarded(company_id):
    context(company_id)
    require(company_id, "factory.manage")
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    return int(form.version.data)


def _back(company_id, balance_id):
    return redirect(url_for("balancing.balance", company_id=company_id, balance_id=balance_id), 303)


@bp.post("/balances/<uuid:balance_id>/rebalance")
@login_required
def balance_rebalance(company_id, balance_id):
    version = _guarded(company_id)
    try:
        short = balancing.rebalance(company_id, balance_id, request.form.get("operators"), version)
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash_short(short, "Laid out again automatically.")
    return _back(company_id, balance_id)


@bp.post("/balances/<uuid:balance_id>/move")
@login_required
def balance_move(company_id, balance_id):
    version = _guarded(company_id)
    source, operation = request.form.get("from_station"), request.form.get("operation_id")
    if request.form.get("work"):
        source, _, operation = request.form["work"].partition(":")
    try:
        short = balancing.move(
            company_id,
            balance_id,
            source,
            operation,
            request.form.get("to_station"),
            request.form.get("percent"),
            version,
        )
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash_short(short, "Work moved. Loads and output are recalculated below.")
    return _back(company_id, balance_id)


@bp.post("/balances/<uuid:balance_id>/publish")
@login_required
def balance_publish(company_id, balance_id):
    version = _guarded(company_id)
    try:
        balancing.publish(company_id, balance_id, version)
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash("Balance published: this is now what the line runs.", "success")
    return _back(company_id, balance_id)


@bp.post("/balances/<uuid:balance_id>/revise")
@login_required
def balance_revise(company_id, balance_id):
    _guarded(company_id)
    try:
        draft = balancing.start_revision(company_id, balance_id)
    except DomainError as exc:
        flash(str(exc), "danger")
        return _back(company_id, balance_id)
    flash("Draft revision opened from the published balance.", "success")
    return _back(company_id, draft.id)


@bp.post("/balances/<uuid:balance_id>/discard")
@login_required
def balance_discard(company_id, balance_id):
    version = _guarded(company_id)
    try:
        line_id = balancing.discard(company_id, balance_id, version)
    except DomainError as exc:
        flash(str(exc), "danger")
        return _back(company_id, balance_id)
    flash("Draft balance discarded.", "success")
    return redirect(url_for("balancing.line", company_id=company_id, line_id=line_id), 303)
