"""Explicit master-data routes backed by resource-specific, bounded forms."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import select
from wtforms import IntegerField, SelectField, StringField, TextAreaField
from wtforms.fields import SelectChoice
from wtforms.validators import DataRequired, Length, NumberRange, Optional, Regexp

from app.extensions import db
from app.forms import ActionForm, trimmed
from app.models import Organization
from app.policies import allowed, require
from app.services.business import DomainError
from app.services.master import FIELDS, MODELS, OPTIONAL, PARENTS, label, lookup, remove, save

bp = Blueprint("master", __name__)


def text(name, maximum, optional=False):
    return StringField(
        name,
        validators=[Optional() if optional else DataRequired(), Length(max=maximum)],
        filters=[lambda value: str(value).strip() if value is not None else value],
    )


def parent(name, optional=False):
    return SelectField(name, validators=[Optional() if optional else DataRequired()])


def options(values):
    return [SelectChoice(value, value.capitalize()) for value in values]


class SiteForm(ActionForm):
    code = text("Code", 40)
    name = text("Name", 120)
    address_text = TextAreaField(
        "Address", validators=[DataRequired(), Length(max=4000)], filters=[trimmed]
    )
    country_code = StringField(
        "Country code", validators=[DataRequired(), Regexp(r"^[A-Za-z]{2}$")], filters=[trimmed]
    )


class PartnerForm(ActionForm):
    code = text("Code", 40)
    name = text("Name", 160)
    status = SelectField("Status", choices=options(("active", "inactive")))


class PartnerRoleForm(ActionForm):
    partner_id = parent("Partner")
    role_code = SelectField("Role", choices=options(("supplier", "customer", "distributor")))


class ContactForm(ActionForm):
    partner_id = parent("Partner")
    name = text("Name", 120)
    email = text("Email", 254, True)
    phone = text("Phone", 40, True)
    purpose = text("Purpose", 80)


class AddressForm(ActionForm):
    partner_id = parent("Partner")
    label = text("Label", 80)
    address_text = TextAreaField(
        "Address", validators=[DataRequired(), Length(max=4000)], filters=[trimmed]
    )
    country_code = StringField(
        "Country code", validators=[DataRequired(), Regexp(r"^[A-Za-z]{2}$")], filters=[trimmed]
    )


class CategoryForm(ActionForm):
    code = text("Code", 40)
    name = text("Name", 100)
    parent_id = parent("Parent category", True)


class ClassificationForm(ActionForm):
    item_id = parent("Item")
    category_id = parent("Category")


class SupplierItemForm(ActionForm):
    partner_id = parent("Supplier")
    variant_id = parent("Item variant")
    supplier_sku = text("Supplier SKU", 80)
    lead_time_days = IntegerField(
        "Lead time in days", validators=[Optional(), NumberRange(min=0, max=36500)]
    )


class WarehouseForm(ActionForm):
    code = text("Code", 40)
    name = text("Name", 120)
    site_id = parent("Site")


class LocationForm(ActionForm):
    code = text("Code", 40)
    name = text("Name", 100)
    kind = SelectField("Kind", choices=options(("storage", "quarantine", "dispatch", "production")))
    warehouse_id = parent("Warehouse")


class LotForm(ActionForm):
    lot_code = text("Internal lot code", 80)
    supplier_lot_code = text("Supplier lot code", 100, True)
    variant_id = parent("Item variant")
    supplier_id = parent("Supplier", True)
    manufactured_at = text("Manufactured at (UTC, YYYY-MM-DDTHH:MM)", 40, True)
    expires_on = text("Expires on (YYYY-MM-DD)", 10, True)


class CarrierForm(ActionForm):
    code = text("Code", 40)
    name = text("Name", 120)
    tracking_url_template = text("HTTPS tracking URL (optional {tracking} placeholder)", 4000, True)


FORMS = {
    "sites": SiteForm,
    "partners": PartnerForm,
    "partner-roles": PartnerRoleForm,
    "contacts": ContactForm,
    "addresses": AddressForm,
    "categories": CategoryForm,
    "classifications": ClassificationForm,
    "supplier-items": SupplierItemForm,
    "warehouses": WarehouseForm,
    "locations": LocationForm,
    "lots": LotForm,
    "carriers": CarrierForm,
}
TITLES = {
    "sites": "Sites",
    "partners": "Partners",
    "partner-roles": "Partner roles",
    "contacts": "Partner contacts",
    "addresses": "Partner addresses",
    "categories": "Item categories",
    "classifications": "Item classifications",
    "supplier-items": "Supplier items",
    "warehouses": "Warehouses",
    "locations": "Storage locations",
    "lots": "Lots",
    "carriers": "Carriers",
}


def context(company_id, resource=None):
    require(company_id, "catalog.read")
    return {
        "company_id": company_id,
        "company": db.session.get(Organization, company_id),
        "can_manage": allowed(company_id, "catalog.manage"),
        "resource": resource,
        "titles": TITLES,
        "title": TITLES.get(resource, "Master data"),
        "label": label,
    }


@bp.get("/companies/<uuid:company_id>/master")
@login_required
def dashboard(company_id):
    return render_template("master/dashboard.html", **context(company_id))


@login_required
def listing(company_id, resource):
    ctx = context(company_id, resource)
    model = MODELS[resource]
    page = db.paginate(
        select(model)
        .where(model.organization_id == company_id)
        .order_by(model.created_at, model.id),
        per_page=30,
        max_per_page=30,
        error_out=False,
    )
    return render_template("master/listing.html", page=page, **ctx)


@login_required
def detail(company_id, resource, record_id):
    ctx = context(company_id, resource)
    row = lookup(company_id, resource, record_id)
    fields = []
    for field in FIELDS[resource]:
        value = getattr(row, field)
        if value and field in PARENTS:
            model = PARENTS[field]
            related = db.session.scalar(
                select(model).where(model.organization_id == company_id, model.id == value)
            )
            value = label(related) if related else "Unavailable"
        fields.append((field.replace("_", " ").capitalize(), value))
    return render_template(
        "master/detail.html",
        record=row,
        fields=fields,
        action_form=ActionForm(version=str(row.version)),
        **ctx,
    )


def editor(company_id, resource, record_id=None):
    ctx = context(company_id, resource)
    require(company_id, "catalog.manage")
    row = lookup(company_id, resource, record_id) if record_id else None
    form = FORMS[resource](obj=row)
    if request.method == "GET":
        form.version.data = str(row.version if row else 0)
    for field in FIELDS[resource]:
        if field not in PARENTS:
            continue
        model = PARENTS[field]
        query = select(model).where(model.organization_id == company_id)
        if hasattr(model, "archived_at"):
            query = query.where(model.archived_at.is_(None))
        if hasattr(model, "status"):
            query = query.where(model.status == "active")
        if field == "parent_id" and row:
            query = query.where(model.id != row.id)
        choices = [
            SelectChoice(str(parent_row.id), label(parent_row))
            for parent_row in db.session.scalars(query.order_by(model.created_at, model.id)).all()
        ]
        if field in OPTIONAL:
            choices.insert(0, SelectChoice("", "None"))
        getattr(form, field).choices = choices
        if request.method == "GET" and row:
            value = getattr(row, field)
            getattr(form, field).data = str(value) if value else ""
    status = 200
    if form.validate_on_submit():
        try:
            result = save(company_id, resource, form.data, record_id, int(form.version.data))
        except DomainError as exc:
            flash(str(exc), "danger")
            status = 409
        else:
            flash("Record saved.", "success")
            return redirect(
                url_for(
                    "master.detail", company_id=company_id, resource=resource, record_id=result.id
                ),
                code=303,
            )
    elif request.method == "POST":
        status = 422
    return render_template(
        "form.html",
        title=f"{'Edit' if row else 'New'} {ctx.pop('title').lower()}",
        form=form,
        submit="Save",
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
    require(company_id, "catalog.manage")
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        message = remove(company_id, resource, record_id, int(form.version.data))
    except DomainError as exc:
        return render_template("error.html", message=str(exc), **ctx), 409
    flash(message, "success")
    return redirect(url_for("master.listing", company_id=company_id, resource=resource), code=303)


for resource in MODELS:
    base = f"/companies/<uuid:company_id>/master/{resource}"
    for suffix, endpoint, view, methods in [
        ("", "listing", listing, ["GET"]),
        ("/new", "create", create, ["GET", "POST"]),
        ("/<uuid:record_id>", "detail", detail, ["GET"]),
        ("/<uuid:record_id>/edit", "edit", edit, ["GET", "POST"]),
        ("/<uuid:record_id>/delete", "delete", delete, ["POST"]),
    ]:
        bp.add_url_rule(
            base + suffix, endpoint, view, defaults={"resource": resource}, methods=methods
        )
