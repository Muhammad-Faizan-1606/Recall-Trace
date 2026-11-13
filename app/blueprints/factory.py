"""Factory Suite step 1: factory model, machine register and live capacity."""

from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import func, select
from wtforms import DecimalField, IntegerField, SelectField, SelectMultipleField, StringField
from wtforms.fields import DateField
from wtforms.fields.choices import SelectChoice
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional
from wtforms.widgets import CheckboxInput, ListWidget

from app.extensions import db
from app.forms import ActionForm, trimmed
from app.models import Organization
from app.models.factory import (
    DEPARTMENTS,
    MACHINE_STATUSES,
    Machine,
    MachineClass,
    MachineStatusEvent,
    ShiftPattern,
    WorkCenter,
)
from app.models.master import Site
from app.policies import allowed, require
from app.presentation import quantity_text, status_tag
from app.services import capacity
from app.services.business import DomainError
from app.services.factory import (
    DAY_NAMES,
    RESOURCES,
    change_status,
    exceptions_by_site,
    label,
    lookup,
    machines_by_center,
    remove,
    save,
    spec,
)

bp = Blueprint("factory", __name__, url_prefix="/companies/<uuid:company_id>/factory")

HORIZON_DAYS = 14
# Illustration only until styles carry their own SAM (Factory Suite step 2).
REFERENCE_SAM = Decimal(12)


@bp.app_template_filter("cap")
def capacity_text(value):
    """34520.4 -> '34,520'; 12.34 -> '12.3'. Planning figures, not stock quantities."""
    if value is None:
        return "—"
    value = Decimal(value)
    if value == 0:
        return "0"
    places = "1" if abs(value) >= 100 else "0.1"
    return f"{capacity.q(value, places):,}"


@bp.app_template_filter("caps")
def capacities_text(per_unit):
    """{'kg': 34520, 'm': 8640} -> '34,520 kg · 8,640 m'."""
    if not per_unit:
        return "—"
    return " · ".join(f"{capacity_text(value)} {unit}" for unit, value in sorted(per_unit.items()))


def human(value):
    return str(value).replace("_", " ").replace("-", " ").capitalize()


def days_text(mask):
    names = [name for name, flag in zip(DAY_NAMES, mask, strict=True) if flag == "1"]
    if mask == "1111110":
        return "Mon–Sat"
    if mask == "1111100":
        return "Mon–Fri"
    if mask == "1111111":
        return "Every day"
    return ", ".join(names)


def context(company_id, resource=None):
    require(company_id, "factory.read")
    return {
        "company_id": company_id,
        "company": db.session.get(Organization, company_id),
        "can_manage": allowed(company_id, "factory.manage"),
        "resource": resource,
        "resources": {key: value[1] for key, value in RESOURCES.items()},
        "label": label,
        "human": human,
    }


# ---------- Forms built from the resource specification ----------


def build_form(resource):
    _, _, fields = spec(resource)

    class Form(ActionForm):
        pass

    for item in fields:
        check = [DataRequired() if item.required else Optional()]
        if item.kind == "text":
            field = StringField(
                item.label,
                validators=[*check, Length(max=200 if item.name == "note" else 120)],
                filters=[lambda value: trimmed(str(value)) if value is not None else value],
                description=item.help,
            )
        elif item.kind == "int":
            field = IntegerField(
                item.label,
                validators=[
                    Optional() if not item.required else InputRequired(),
                    NumberRange(min=item.minimum, max=item.maximum),
                ],
                description=item.help,
            )
        elif item.kind == "decimal":
            field = DecimalField(
                item.label,
                places=None,
                validators=[
                    Optional() if not item.required else InputRequired(),
                    NumberRange(min=item.minimum, max=item.maximum),
                ],
                description=item.help,
            )
        elif item.kind == "choice":
            field = SelectField(
                item.label,
                choices=[SelectChoice(value, human(value)) for value in item.choices],
                description=item.help,
            )
        elif item.kind == "parent":
            field = SelectField(item.label, validators=check, description=item.help)
        elif item.kind == "date":
            field = DateField(item.label, validators=check, description=item.help)
        else:  # working days
            field = SelectMultipleField(
                item.label,
                choices=[SelectChoice(str(index), name) for index, name in enumerate(DAY_NAMES)],
                option_widget=CheckboxInput(),
                widget=ListWidget(prefix_label=False),
                validate_choice=True,
                description=item.help,
            )
        setattr(Form, item.name, field)
    return Form


def parent_choices(company_id, item, required):
    model = item.parent
    query = select(model).where(model.organization_id == company_id)
    if hasattr(model, "archived_at"):
        query = query.where(model.archived_at.is_(None))
    for name in ("code", "asset_tag", "name"):
        if hasattr(model, name):
            order = getattr(model, name)
            break
    else:
        order = model.created_at
    rows = db.session.scalars(query.order_by(order)).all()
    choices = [SelectChoice(str(row.id), label(row)) for row in rows]
    if not required:
        choices.insert(0, SelectChoice("", "None"))
    return choices


# ---------- Display helpers ----------

COLUMNS = {
    "shift-patterns": (
        ("Pattern", lambda r, x: label(r)),
        ("Shifts", lambda r, x: r.shifts_per_day),
        ("Hours each", lambda r, x: r.hours_per_shift),
        ("Days", lambda r, x: days_text(r.working_days)),
    ),
    "work-centers": (
        ("Work centre", lambda r, x: label(r)),
        ("Department", lambda r, x: human(r.department)),
        ("Site", lambda r, x: x["sites"].get(r.site_id, "—")),
        ("Target", lambda r, x: f"{capacity.q(r.target_efficiency, '1')}%"),
    ),
    "machine-classes": (
        ("Class", lambda r, x: label(r)),
        ("Department", lambda r, x: human(r.department)),
        ("Formula", lambda r, x: human(r.capacity_basis)),
        ("Output", lambda r, x: capacity.unit_for(r)),
    ),
    "machines": (
        ("Machine", lambda r, x: label(r)),
        ("Class", lambda r, x: x["classes"].get(r.machine_class_id, "—")),
        ("Work centre", lambda r, x: x["centers"].get(r.work_center_id, "—")),
        ("Status", lambda r, x: x["tag"](r.status)),
    ),
    "calendar": (
        ("Day", lambda r, x: f"{r.day:%a %d %b %Y}"),
        ("Site", lambda r, x: x["sites"].get(r.site_id, "—")),
        ("Kind", lambda r, x: human(r.kind)),
        ("Hours per shift", lambda r, x: r.hours_per_shift),
        ("Note", lambda r, x: r.note),
    ),
    "transit": (
        ("Route", lambda r, x: label(r)),
        ("Hours", lambda r, x: r.hours),
        ("Note", lambda r, x: r.note or ""),
    ),
}


def names(company_id, model):
    rows = db.session.scalars(select(model).where(model.organization_id == company_id)).all()
    return {row.id: (row.name if isinstance(row, Site) else label(row)) for row in rows}


def display(company_id, resource, row):
    """(label, value) pairs for a detail page, with related records named."""
    pairs = []
    for item in spec(resource)[2]:
        value = getattr(row, item.name)
        if item.kind == "parent" and value:
            related = db.session.get(item.parent, value)
            value = related.name if isinstance(related, Site) else label(related)
        elif item.kind == "choice" and value:
            value = human(value)
        elif item.kind == "days":
            value = days_text(value)
        elif item.kind == "date" and value:
            value = f"{value:%d %b %Y}"
        elif isinstance(value, Decimal):
            value = quantity_text(value)
        if value in (None, ""):
            continue
        pairs.append((item.label, value))
    return pairs


# ---------- Overview ----------


@bp.get("")
@login_required
def overview(company_id):
    ctx = context(company_id)
    today = date.today()
    sites = db.session.scalars(
        select(Site)
        .where(Site.organization_id == company_id, Site.archived_at.is_(None))
        .order_by(Site.created_at, Site.code)
    ).all()
    centers = db.session.scalars(
        select(WorkCenter)
        .where(WorkCenter.organization_id == company_id, WorkCenter.archived_at.is_(None))
        .order_by(WorkCenter.code)
    ).all()
    patterns = {
        row.id: row
        for row in db.session.scalars(
            select(ShiftPattern).where(ShiftPattern.organization_id == company_id)
        )
    }
    grouped = machines_by_center(company_id)
    exceptions = exceptions_by_site(company_id, today, today)
    by_site, departments = {}, {}
    totals = {"machines": 0, "available": 0, "maintenance": 0}
    for center in centers:
        machines = grouped.get(center.id, [])
        result = capacity.center_capacity(center, machines)
        hours, reason = capacity.shift_hours(
            patterns[center.shift_pattern_id], today, exceptions.get(center.site_id, {})
        )
        per_day = result.per_day(hours)
        totals["machines"] += result.total
        totals["available"] += result.available
        totals["maintenance"] += sum(1 for m, _ in machines if m.status == "maintenance")
        rows = by_site.setdefault(center.site_id, [])
        if center.department == "sewing":
            # Sewing lines are many and alike: show one combined row per site.
            line = next((row for row in rows if row["lines"]), None)
            if line is None:
                line = {
                    "center": None,
                    "name": "Sewing lines",
                    "code": "",
                    "lines": 0,
                    "department": "sewing",
                    "available": 0,
                    "total": 0,
                    "hours": hours,
                    "reason": reason,
                    "per_day": {},
                }
                rows.append(line)
            line["lines"] += 1
            line["name"] = f"Sewing lines ({line['lines']})"
            line["available"] += result.available
            line["total"] += result.total
            line["hours"] = max(line["hours"], hours)
            for unit, value in per_day.items():
                line["per_day"][unit] = line["per_day"].get(unit, Decimal(0)) + value
        else:
            rows.append(
                {
                    "center": center,
                    "name": center.name,
                    "code": center.code,
                    "lines": 0,
                    "department": center.department,
                    "available": result.available,
                    "total": result.total,
                    "hours": hours,
                    "reason": reason,
                    "per_day": per_day,
                }
            )
        bucket = departments.setdefault(center.department, {})
        for unit, value in per_day.items():
            bucket[unit] = bucket.get(unit, Decimal(0)) + value
    order = {name: index for index, name in enumerate(DEPARTMENTS)}
    return render_template(
        "factory/overview.html",
        sites=[(site, by_site.get(site.id, [])) for site in sites],
        departments=sorted(departments.items(), key=lambda pair: order.get(pair[0], 99)),
        totals=totals,
        center_count=len(centers),
        reference_sam=REFERENCE_SAM,
        today=today,
        **ctx,
    )


@bp.get("/setup")
@login_required
def setup(company_id):
    ctx = context(company_id)
    counts = {}
    for key, (model, _, _) in RESOURCES.items():
        query = select(func.count()).select_from(model).where(model.organization_id == company_id)
        if hasattr(model, "archived_at"):
            query = query.where(model.archived_at.is_(None))
        counts[key] = db.session.scalar(query)
    sites = db.session.scalar(
        select(func.count())
        .select_from(Site)
        .where(Site.organization_id == company_id, Site.archived_at.is_(None))
    )
    return render_template("factory/setup.html", counts=counts, site_count=sites, **ctx)


# ---------- Generic register pages ----------


@login_required
def listing(company_id, resource):
    ctx = context(company_id, resource)
    model, title, _ = spec(resource)
    query = select(model).where(model.organization_id == company_id)
    if hasattr(model, "archived_at"):
        query = query.order_by(model.archived_at.is_not(None))
    sort = {"calendar": "day", "transit": "created_at", "machines": "asset_tag"}
    order = (getattr(model, sort.get(resource, "code")),)
    page = db.paginate(query.order_by(*order), per_page=50, max_per_page=50, error_out=False)
    extra = {
        "sites": names(company_id, Site),
        "classes": names(company_id, MachineClass),
        "centers": names(company_id, WorkCenter),
        "tag": render_tag,
    }
    rows = [(row, [render(row, extra) for _, render in COLUMNS[resource]]) for row in page.items]
    return render_template(
        "factory/listing.html",
        title=title,
        headers=[header for header, _ in COLUMNS[resource]],
        rows=rows,
        page=page,
        **ctx,
    )


def render_tag(value):
    return status_tag(value)


@login_required
def detail(company_id, resource, record_id):
    ctx = context(company_id, resource)
    row = lookup(company_id, resource, record_id)
    extra = {}
    if resource == "machines":
        extra = machine_extra(company_id, row)
    elif resource == "work-centers":
        extra = center_extra(company_id, row)
    elif resource == "machine-classes":
        extra["machine_count"] = db.session.scalar(
            select(func.count())
            .select_from(Machine)
            .where(
                Machine.organization_id == company_id,
                Machine.machine_class_id == row.id,
                Machine.archived_at.is_(None),
            )
        )
    return render_template(
        "factory/detail.html",
        record=row,
        title=spec(resource)[1],
        fields=display(company_id, resource, row),
        action_form=ActionForm(version=str(row.version)),
        **extra,
        **ctx,
    )


def machine_extra(company_id, machine):
    machine_class = db.session.get(MachineClass, machine.machine_class_id)
    center = db.session.get(WorkCenter, machine.work_center_id)
    rate = capacity.machine_rate(machine, machine_class, center)
    history = db.session.scalars(
        select(MachineStatusEvent)
        .where(
            MachineStatusEvent.organization_id == company_id,
            MachineStatusEvent.machine_id == machine.id,
        )
        .order_by(MachineStatusEvent.occurred_at.desc())
        .limit(50)
    ).all()
    return {
        "rate": rate,
        "machine_class": machine_class,
        "center": center,
        "history": history,
        "statuses": [s for s in MACHINE_STATUSES if s != machine.status],
        "available": machine.status in capacity.AVAILABLE_STATUSES,
    }


def center_extra(company_id, center):
    pattern = db.session.get(ShiftPattern, center.shift_pattern_id)
    site = db.session.get(Site, center.site_id)
    machines = machines_by_center(company_id, [center.id]).get(center.id, [])
    result = capacity.center_capacity(center, machines)
    today = date.today()
    exceptions = exceptions_by_site(company_id, today, today + timedelta(days=HORIZON_DAYS)).get(
        center.site_id, {}
    )
    days = [
        (day, hours, reason, result.per_day(hours))
        for day, hours, reason in capacity.calendar(pattern, today, HORIZON_DAYS, exceptions)
    ]
    rates = [(m, c, capacity.machine_rate(m, c, center)) for m, c in machines]
    return {
        "pattern": pattern,
        "site": site,
        "result": result,
        "days": days,
        "rates": rates,
        "units": sorted(result.per_hour),
        "week_total": {
            unit: sum((per_day.get(unit, Decimal(0)) for *_, per_day in days[:7]), Decimal(0))
            for unit in result.per_hour
        },
    }


def editor(company_id, resource, record_id=None):
    ctx = context(company_id, resource)
    require(company_id, "factory.manage")
    row = lookup(company_id, resource, record_id) if record_id else None
    form = build_form(resource)(obj=row)
    _, title, fields = spec(resource)
    for item in fields:
        if item.kind == "parent":
            getattr(form, item.name).choices = parent_choices(company_id, item, item.required)
            if request.method == "GET" and row is not None:
                value = getattr(row, item.name)
                getattr(form, item.name).data = str(value) if value else ""
        if item.kind == "days" and request.method == "GET":
            mask = row.working_days if row is not None else "1111110"
            getattr(form, item.name).data = [str(i) for i, flag in enumerate(mask) if flag == "1"]
    if request.method == "GET":
        form.version.data = str(row.version if row else 0)
    status = 200
    if form.validate_on_submit():
        try:
            result = save(company_id, resource, form.data, record_id, int(form.version.data))
        except DomainError as exc:
            flash(str(exc), "danger")
            status = 409
        else:
            flash("Saved.", "success")
            return redirect(
                url_for(
                    "factory.detail", company_id=company_id, resource=resource, record_id=result.id
                ),
                code=303,
            )
    elif request.method == "POST":
        status = 422
    noun = title[:-1].lower() if title.endswith("s") else title.lower()
    return render_template(
        "factory/form.html",
        title=f"{'Edit' if row else 'New'} {noun}",
        form=form,
        submit="Save",
        back=url_for("factory.listing", company_id=company_id, resource=resource),
        **ctx,
    ), status


@login_required
def create(company_id, resource):
    return editor(company_id, resource)


@login_required
def edit(company_id, resource, record_id):
    return editor(company_id, resource, record_id)


@login_required
def delete(company_id, resource, record_id):
    ctx = context(company_id, resource)
    require(company_id, "factory.manage")
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        message = remove(company_id, resource, record_id, int(form.version.data))
    except DomainError as exc:
        return render_template("error.html", message=str(exc), **ctx), 409
    flash(message, "success")
    return redirect(url_for("factory.listing", company_id=company_id, resource=resource), code=303)


@bp.post("/machines/<uuid:record_id>/status")
@login_required
def machine_status(company_id, record_id):
    context(company_id, "machines")
    require(company_id, "factory.manage")
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        change_status(
            company_id,
            record_id,
            request.form.get("to_status", ""),
            request.form.get("reason", ""),
            int(form.version.data),
        )
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash("Machine status updated; capacity recalculated.", "success")
    return redirect(
        url_for("factory.detail", company_id=company_id, resource="machines", record_id=record_id),
        code=303,
    )


for resource_name in RESOURCES:
    base = f"/{resource_name}"
    for suffix, endpoint, view, methods in [
        ("", "listing", listing, ["GET"]),
        ("/new", "create", create, ["GET", "POST"]),
        ("/<uuid:record_id>", "detail", detail, ["GET"]),
        ("/<uuid:record_id>/edit", "edit", edit, ["GET", "POST"]),
        ("/<uuid:record_id>/delete", "delete", delete, ["POST"]),
    ]:
        bp.add_url_rule(
            base + suffix,
            endpoint,
            view,
            defaults={"resource": resource_name},
            methods=methods,
        )
