import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms.fields import SelectChoice

from app.extensions import db
from app.forms import ActionForm, ItemForm, UnitForm, VariantForm
from app.models import Item, Membership, Organization, UnitsOfMeasure
from app.policies import allowed, require
from app.services.catalog import MODELS, CatalogConflict, lookup, remove, save
from app.services.master import lot_name

bp = Blueprint("catalog", __name__)
FORMS = {"items": ItemForm, "units": UnitForm, "variants": VariantForm}


@bp.get("/")
@login_required
def companies():
    companies = db.session.scalars(
        select(Organization)
        .join(Membership)
        .where(
            Membership.user_id == current_user.id,
            Membership.status == "active",
            Membership.archived_at.is_(None),
            Membership.partner_id.is_(None),
            Organization.status == "active",
            Organization.archived_at.is_(None),
        )
        .order_by(Organization.name)
    ).all()
    partner_companies = db.session.scalars(
        select(Organization)
        .join(Membership)
        .where(
            Membership.user_id == current_user.id,
            Membership.status == "active",
            Membership.archived_at.is_(None),
            Membership.partner_id.is_not(None),
            Organization.status == "active",
            Organization.archived_at.is_(None),
        )
        .order_by(Organization.name)
    ).all()
    return render_template(
        "companies.html", companies=companies, partner_companies=partner_companies
    )


def context(company_id, kind):
    if kind not in MODELS:
        abort(404)
    require(company_id, "catalog.read")
    return {
        "company_id": company_id,
        "kind": kind,
        "company": db.session.get(Organization, company_id),
        "can_manage": allowed(company_id, "catalog.manage"),
    }


@login_required
def listing(company_id, kind):
    ctx = context(company_id, kind)
    model = MODELS[kind]
    page = db.paginate(
        select(model)
        .where(model.organization_id == company_id)
        .order_by(model.created_at, model.id),
        per_page=30,
        max_per_page=30,
        error_out=False,
    )
    return render_template("listing.html", page=page, **ctx)


@login_required
def detail(company_id, kind, record_id):
    ctx = context(company_id, kind)
    row = lookup(company_id, kind, record_id)
    return render_template(
        "detail.html", record=row, action_form=ActionForm(version=str(row.version)), **ctx
    )


def editor(company_id, kind, record_id=None):
    ctx = context(company_id, kind)
    require(company_id, "catalog.manage")
    row = lookup(company_id, kind, record_id) if record_id else None
    form = FORMS[kind](obj=row)
    if request.method == "GET":
        form.version.data = str(row.version if row else 0)
    if kind == "variants":
        for name, model in [("item_id", Item), ("base_unit_id", UnitsOfMeasure)]:
            parents = db.session.scalars(
                select(model)
                .where(model.organization_id == company_id, model.archived_at.is_(None))
                .order_by(model.code)
            ).all()
            getattr(form, name).choices = [
                SelectChoice(str(parent.id), f"{parent.code} — {parent.name}") for parent in parents
            ]
    status = 200
    if form.validate_on_submit():
        values = dict(form.data)
        if kind == "variants":
            values["item_id"] = uuid.UUID(values["item_id"])
            values["base_unit_id"] = uuid.UUID(values["base_unit_id"])
        try:
            result = save(company_id, kind, values, record_id, int(form.version.data))
        except CatalogConflict as exc:
            flash(str(exc), "danger")
            status = 409
        else:
            flash("Record saved.", "success")
            return redirect(
                url_for("catalog.detail", company_id=company_id, kind=kind, record_id=result.id),
                code=303,
            )
    elif request.method == "POST":
        status = 422
    return render_template(
        "form.html", title=f"{'Edit' if row else 'New'} {kind}", form=form, submit="Save", **ctx
    ), status


@login_required
def create(company_id, kind):
    return editor(company_id, kind)


@login_required
def edit(company_id, kind, record_id):
    return editor(company_id, kind, record_id)


@login_required
def delete(company_id, kind, record_id):
    context(company_id, kind)
    require(company_id, "catalog.manage")
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        flash(remove(company_id, kind, record_id, int(form.version.data)), "success")
    except CatalogConflict as exc:
        flash(str(exc), "danger")
        return render_template("error.html", message=str(exc)), 409
    return redirect(url_for("catalog.listing", company_id=company_id, kind=kind), code=303)


@bp.app_context_processor
def shared_forms():
    return {
        "logout_form": FlaskForm(),
        "can_access_company": lambda company_id: allowed(company_id, "access.manage"),
        "lot_name": lot_name,
    }


# Explicit, finite resource routes share the catalog plumbing and never expose arbitrary models.
for resource in ("items", "variants", "units"):
    base = f"/companies/<uuid:company_id>/catalog/{resource}"
    for suffix, endpoint, view, methods in [
        ("", "listing", listing, ["GET"]),
        ("/new", "create", create, ["GET", "POST"]),
        ("/<uuid:record_id>", "detail", detail, ["GET"]),
        ("/<uuid:record_id>/edit", "edit", edit, ["GET", "POST"]),
        ("/<uuid:record_id>/delete", "delete", delete, ["POST"]),
    ]:
        bp.add_url_rule(base + suffix, endpoint, view, defaults={"kind": resource}, methods=methods)
