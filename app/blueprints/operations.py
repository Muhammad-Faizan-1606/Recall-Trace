"""Explicit operational document routes with bounded, server-validated forms."""

import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import DateField, HiddenField, SelectField, StringField, TextAreaField
from wtforms.fields import SelectChoice
from wtforms.validators import DataRequired, Length, Optional

from app.extensions import db
from app.forms import ActionForm
from app.models import ItemVariant, Organization
from app.models.master import (
    Carrier,
    Lot,
    Partner,
    PartnerAddress,
    Site,
    StorageLocation,
    Warehouse,
)
from app.models.operations import (
    PurchaseOrderLine,
    ReceiptDocument,
    SalesOrder,
    SalesOrderLine,
    ShipmentEvent,
    StockBalance,
    StockTransaction,
    StockTransactionLine,
)
from app.policies import allowed, require
from app.services import operations as service
from app.services.business import DomainError, scoped

bp = Blueprint("operations", __name__)


class ReferenceForm(ActionForm):
    reference = StringField("Reference", validators=[DataRequired(), Length(max=80)])


class PurchaseForm(ReferenceForm):
    supplier_id = SelectField("Supplier", validators=[DataRequired()])
    delivery_site_id = SelectField("Delivery site", validators=[DataRequired()])
    ordered_on = DateField("Order date", validators=[Optional()])


class ReceiptForm(ReferenceForm):
    supplier_id = SelectField("Supplier", validators=[DataRequired()])
    warehouse_id = SelectField("Receiving warehouse", validators=[DataRequired()])


class ProductionForm(ReferenceForm):
    site_id = SelectField("Production site", validators=[DataRequired()])


class SalesForm(ReferenceForm):
    customer_id = SelectField("Customer", validators=[DataRequired()])
    address_id = SelectField("Customer address (optional)", validators=[Optional()])
    destination = TextAreaField("Destination", validators=[Length(max=4000)])


class ShipmentForm(ReferenceForm):
    sales_order_id = SelectField("Confirmed sales order", validators=[DataRequired()])
    warehouse_id = SelectField("Dispatch warehouse", validators=[DataRequired()])
    carrier_id = SelectField("Carrier (optional)", validators=[Optional()])
    tracking_reference = StringField("Tracking reference", validators=[Length(max=120)])


class TransferForm(ReferenceForm):
    source_warehouse_id = SelectField("Source warehouse", validators=[DataRequired()])
    destination_warehouse_id = SelectField("Destination warehouse", validators=[DataRequired()])


class QuantityForm(ActionForm):
    quantity = StringField("Quantity in SKU base unit", validators=[DataRequired(), Length(max=30)])


class OrderLineForm(QuantityForm):
    variant_id = SelectField("SKU", validators=[DataRequired()])


class ReceiptLineForm(QuantityForm):
    purchase_order_line_id = SelectField(
        "Confirmed purchase order line", validators=[DataRequired()]
    )
    lot_id = SelectField("Lot", validators=[DataRequired()])
    location_id = SelectField("Receiving location", validators=[DataRequired()])


class InputForm(QuantityForm):
    lot_id = SelectField("Input lot", validators=[DataRequired()])
    source_location_id = SelectField("Source location", validators=[DataRequired()])


class OutputForm(QuantityForm):
    lot_id = SelectField("New output lot", validators=[DataRequired()])
    destination_location_id = SelectField("Destination location", validators=[DataRequired()])


class ShipmentLineForm(QuantityForm):
    sales_order_line_id = SelectField("Customer order line", validators=[DataRequired()])
    lot_id = SelectField("Lot", validators=[DataRequired()])
    source_location_id = SelectField("Dispatch location", validators=[DataRequired()])


class TransferLineForm(QuantityForm):
    lot_id = SelectField("Lot", validators=[DataRequired()])
    source_location_id = SelectField("Source location", validators=[DataRequired()])
    destination_location_id = SelectField("Destination location", validators=[DataRequired()])


class PostForm(ActionForm):
    idempotency_key = HiddenField(validators=[DataRequired(), Length(max=100)])


class EventForm(FlaskForm):
    event_type = SelectField(
        "Event",
        choices=[
            SelectChoice(k, k.replace("_", " ").title())
            for k in ("in_transit", "delivered", "exception", "correction")
        ],
    )
    note = TextAreaField("Note", validators=[Length(max=4000)])


class EvidenceForm(ActionForm):
    document_id = SelectField("Accepted private document", validators=[DataRequired()])


class ReverseForm(FlaskForm):
    idempotency_key = HiddenField(validators=[DataRequired(), Length(max=100)])
    reason = TextAreaField("Correction reason", validators=[DataRequired(), Length(max=1000)])


FORMS = {
    "purchase-orders": PurchaseForm,
    "receipts": ReceiptForm,
    "production": ProductionForm,
    "sales-orders": SalesForm,
    "shipments": ShipmentForm,
    "transfers": TransferForm,
}
LINE_FORMS = {
    "purchase-orders": OrderLineForm,
    "receipts": ReceiptLineForm,
    "production-inputs": InputForm,
    "production-outputs": OutputForm,
    "sales-orders": OrderLineForm,
    "shipments": ShipmentLineForm,
    "transfers": TransferLineForm,
}
CHOICES = {
    "supplier_id": Partner,
    "customer_id": Partner,
    "delivery_site_id": Site,
    "site_id": Site,
    "warehouse_id": Warehouse,
    "source_warehouse_id": Warehouse,
    "destination_warehouse_id": Warehouse,
    "address_id": PartnerAddress,
    "carrier_id": Carrier,
    "sales_order_id": SalesOrder,
    "variant_id": ItemVariant,
    "lot_id": Lot,
    "location_id": StorageLocation,
    "source_location_id": StorageLocation,
    "destination_location_id": StorageLocation,
    "purchase_order_line_id": PurchaseOrderLine,
    "sales_order_line_id": SalesOrderLine,
}


def label(row):
    if isinstance(row, (PurchaseOrderLine, SalesOrderLine)):
        parent_id = (
            row.purchase_order_id if isinstance(row, PurchaseOrderLine) else row.sales_order_id
        )
        parent_kind = "purchase-orders" if isinstance(row, PurchaseOrderLine) else "sales-orders"
        parent = db.session.get(service.DOCUMENTS[parent_kind][0], parent_id)
        sku = db.session.get(ItemVariant, row.variant_id)
        return f"{parent.reference} / {sku.sku} / ordered {row.quantity}"
    return str(
        getattr(row, "lot_code", None)
        or getattr(row, "sku", None)
        or getattr(row, "reference", None)
        or getattr(row, "name", None)
        or getattr(row, "label", None)
        or row.id
    )


def fill_choices(form, company_id, record=None):
    for field_name, model in CHOICES.items():
        if field_name not in form:
            continue
        query = select(model).where(model.organization_id == company_id)
        if hasattr(model, "archived_at"):
            query = query.where(model.archived_at.is_(None))
        if model == SalesOrder:
            query = query.where(model.status == "posted")
        choices = []
        for row in db.session.scalars(query.order_by(model.created_at, model.id)):
            if model in (PurchaseOrderLine, SalesOrderLine):
                parent_kind = "purchase-orders" if model == PurchaseOrderLine else "sales-orders"
                parent_id = (
                    row.purchase_order_id if model == PurchaseOrderLine else row.sales_order_id
                )
                parent = db.session.get(service.DOCUMENTS[parent_kind][0], parent_id)
                if parent.status != "posted":
                    continue
                if record and model == SalesOrderLine and parent.id != record.sales_order_id:
                    continue
                if (
                    record
                    and model == PurchaseOrderLine
                    and parent.supplier_id != record.supplier_id
                ):
                    continue
            choices.append(SelectChoice(str(row.id), label(row)))
        if field_name in ("address_id", "carrier_id"):
            choices.insert(0, SelectChoice("", "None"))
        form[field_name].choices = choices


def display_value(field, value):
    if field in CHOICES and value:
        row = db.session.get(CHOICES[field], value)
        return label(row) if row else "Unavailable related record"
    return value


def context(company_id):
    require(company_id, "catalog.read")
    return {
        "company_id": company_id,
        "company": db.session.get(Organization, company_id),
        "kinds": service.DOCUMENTS,
        "label": label,
        "line_columns": {k: v[2] for k, v in service.LINES.items()},
        "display_value": display_value,
    }


def error(exc):
    flash(str(exc), "danger")
    return render_template("error.html", message=str(exc)), 409


@bp.get("/companies/<uuid:company_id>/operations")
@login_required
def dashboard(company_id):
    ctx = context(company_id)
    balances = list(
        db.session.scalars(
            select(StockBalance)
            .where(StockBalance.organization_id == company_id)
            .order_by(StockBalance.lot_id, StockBalance.location_id)
            .limit(200)
        )
    )
    lots = {
        row.id: row
        for row in db.session.scalars(select(Lot).where(Lot.organization_id == company_id))
    }
    locations = {
        row.id: row
        for row in db.session.scalars(
            select(StorageLocation).where(StorageLocation.organization_id == company_id)
        )
    }
    return render_template(
        "operations/dashboard.html",
        balances=balances,
        lots=lots,
        locations=locations,
        mismatches=service.reconciliation(company_id),
        **ctx,
    )


@login_required
def listing(company_id, kind):
    ctx = context(company_id)
    model, action = service.DOCUMENTS[kind]
    page = db.paginate(
        select(model)
        .where(model.organization_id == company_id)
        .order_by(model.created_at.desc(), model.id),
        per_page=30,
        max_per_page=30,
        error_out=False,
    )
    return render_template(
        "operations/listing.html",
        page=page,
        kind=kind,
        can_manage=allowed(company_id, action),
        **ctx,
    )


@login_required
def detail(company_id, kind, record_id):
    ctx = context(company_id)
    row = service.document(company_id, kind, record_id)
    groups = [
        (k, service.lines_for(company_id, k, row.id))
        for k in (["production-inputs", "production-outputs"] if kind == "production" else [kind])
    ]
    line_forms = {}
    for line_kind, _ in groups:
        form = LINE_FORMS[line_kind](version=str(row.version), prefix=line_kind)
        fill_choices(form, company_id, row)
        line_forms[line_kind] = form
    events = (
        list(
            db.session.scalars(
                select(ShipmentEvent)
                .where(
                    ShipmentEvent.organization_id == company_id, ShipmentEvent.shipment_id == row.id
                )
                .order_by(ShipmentEvent.occurred_at)
            )
        )
        if kind == "shipments"
        else []
    )
    attachments = (
        list(
            db.session.scalars(
                select(ReceiptDocument).where(
                    ReceiptDocument.organization_id == company_id,
                    ReceiptDocument.receipt_id == row.id,
                )
            )
        )
        if kind == "receipts"
        else []
    )
    evidence_form = EvidenceForm(version=str(row.version))
    if kind == "receipts" and allowed(company_id, "evidence.read"):
        from app.models.evidence import Document

        evidence_form.document_id.choices = [
            SelectChoice(str(doc.id), doc.original_name)
            for doc in db.session.scalars(
                select(Document).where(
                    Document.organization_id == company_id,
                    Document.scan_status == "clean",
                    Document.state == "active",
                    Document.archived_at.is_(None),
                )
            )
        ]
    return render_template(
        "operations/detail.html",
        kind=kind,
        record=row,
        groups=groups,
        line_forms=line_forms,
        action_form=ActionForm(version=str(row.version)),
        post_form=PostForm(version=str(row.version), idempotency_key=secrets.token_urlsafe(24)),
        can_manage=allowed(company_id, service.DOCUMENTS[kind][1]),
        events=events,
        event_form=EventForm(),
        attachments=attachments,
        can_attach_evidence=allowed(company_id, "evidence.read"),
        evidence_form=evidence_form,
        **ctx,
    )


@login_required
def editor(company_id, kind, record_id=None):
    ctx = context(company_id)
    require(company_id, service.DOCUMENTS[kind][1])
    row = service.document(company_id, kind, record_id) if record_id else None
    if row and row.status != "draft":
        abort(409)
    has_lines = row and any(
        service.lines_for(company_id, k, row.id)
        for k in (["production-inputs", "production-outputs"] if kind == "production" else [kind])
    )
    form = ReferenceForm(obj=row) if has_lines else FORMS[kind](obj=row)
    fill_choices(form, company_id, row)
    if request.method == "GET":
        form.version.data = str(row.version if row else 0)
        if row and kind == "sales-orders" and not has_lines:
            form.destination.data = row.destination_snapshot.get("address", "")
    status = 200
    if form.validate_on_submit():
        try:
            result = (
                service.update_draft(company_id, kind, row.id, form.data, int(form.version.data))
                if row
                else service.create_document(company_id, kind, form.data)
            )
            flash("Draft saved.", "success")
            return redirect(
                url_for("operations.detail", company_id=company_id, kind=kind, record_id=result.id),
                code=303,
            )
        except DomainError as exc:
            flash(str(exc), "danger")
            status = 409
    elif request.method == "POST":
        status = 422
    return render_template(
        "operations/editor.html", kind=kind, record=row, form=form, has_lines=has_lines, **ctx
    ), status


@login_required
def create(company_id, kind):
    return editor(company_id, kind)


@login_required
def edit(company_id, kind, record_id):
    return editor(company_id, kind, record_id)


@login_required
def post(company_id, kind, record_id):
    form = PostForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        service.post_document(
            company_id, kind, record_id, form.idempotency_key.data, int(form.version.data)
        )
    except DomainError as exc:
        return error(exc)
    flash("Document posted. History is preserved.", "success")
    return redirect(
        url_for("operations.detail", company_id=company_id, kind=kind, record_id=record_id),
        code=303,
    )


@login_required
def delete(company_id, kind, record_id):
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        service.delete_draft(company_id, kind, record_id, int(form.version.data))
    except DomainError as exc:
        return error(exc)
    flash("Draft deleted.", "success")
    return redirect(url_for("operations.listing", company_id=company_id, kind=kind), code=303)


@login_required
def line_add(company_id, kind, record_id, line_kind):
    context(company_id)
    record = service.document(company_id, kind, record_id)
    form = LINE_FORMS[line_kind](prefix=line_kind)
    fill_choices(form, company_id, record)
    if not form.validate_on_submit():
        return render_template(
            "operations/editor.html",
            kind=line_kind,
            record=record,
            form=form,
            has_lines=False,
            **context(company_id),
        ), 422
    try:
        service.add_line(company_id, line_kind, record_id, form.data, int(form.version.data))
    except DomainError as exc:
        return error(exc)
    return redirect(
        url_for("operations.detail", company_id=company_id, kind=kind, record_id=record_id),
        code=303,
    )


@login_required
def line_delete(company_id, kind, record_id, line_id, line_kind):
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        service.delete_line(company_id, line_kind, record_id, line_id, int(form.version.data))
    except DomainError as exc:
        return error(exc)
    return redirect(
        url_for("operations.detail", company_id=company_id, kind=kind, record_id=record_id),
        code=303,
    )


@login_required
def line_edit(company_id, kind, record_id, line_id, line_kind):
    ctx = context(company_id)
    require(company_id, service.DOCUMENTS[kind][1])
    parent = service.document(company_id, kind, record_id)
    model, parent_field, _ = service.LINES[line_kind]
    row = scoped(model, company_id, line_id)
    if getattr(row, parent_field) != parent.id:
        abort(404)
    if parent.status != "draft":
        abort(409)
    form = LINE_FORMS[line_kind](obj=row, prefix=line_kind)
    fill_choices(form, company_id, parent)
    if request.method == "GET":
        form.version.data = str(parent.version)
    status = 200
    if form.validate_on_submit():
        try:
            service.add_line(
                company_id, line_kind, record_id, form.data, int(form.version.data), line_id=line_id
            )
        except DomainError as exc:
            return error(exc)
        return redirect(
            url_for("operations.detail", company_id=company_id, kind=kind, record_id=record_id),
            code=303,
        )
    elif request.method == "POST":
        status = 422
    return render_template(
        "operations/editor.html", kind=line_kind, record=row, form=form, has_lines=False, **ctx
    ), status


@bp.post(
    "/companies/<uuid:company_id>/operations/receipts/<uuid:record_id>/evidence/<uuid:attachment_id>/remove"
)
@login_required
def receipt_evidence_remove(company_id, record_id, attachment_id):
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        service.detach_receipt_document(
            company_id, record_id, attachment_id, int(form.version.data)
        )
    except DomainError as exc:
        return error(exc)
    return redirect(
        url_for("operations.detail", company_id=company_id, kind="receipts", record_id=record_id),
        code=303,
    )


@bp.post("/companies/<uuid:company_id>/operations/receipts/<uuid:record_id>/evidence")
@login_required
def receipt_evidence(company_id, record_id):
    require(company_id, "inventory.receive")
    require(company_id, "evidence.read")
    form = EvidenceForm()
    from app.models.evidence import Document

    form.document_id.choices = [
        SelectChoice(str(row.id), row.original_name)
        for row in db.session.scalars(
            select(Document).where(
                Document.organization_id == company_id,
                Document.scan_status == "clean",
                Document.state == "active",
                Document.archived_at.is_(None),
            )
        )
    ]
    if not form.validate_on_submit():
        abort(400)
    try:
        service.attach_receipt_document(
            company_id, record_id, form.document_id.data, int(form.version.data)
        )
    except DomainError as exc:
        return error(exc)
    return redirect(
        url_for("operations.detail", company_id=company_id, kind="receipts", record_id=record_id),
        code=303,
    )


@bp.post("/companies/<uuid:company_id>/operations/shipments/<uuid:record_id>/events")
@login_required
def shipment_event(company_id, record_id):
    form = EventForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        service.add_shipment_event(company_id, record_id, form.event_type.data, form.note.data)
    except DomainError as exc:
        return error(exc)
    return redirect(
        url_for("operations.detail", company_id=company_id, kind="shipments", record_id=record_id),
        code=303,
    )


@bp.get("/companies/<uuid:company_id>/operations/journal")
@login_required
def journal(company_id):
    ctx = context(company_id)
    page = db.paginate(
        select(StockTransaction)
        .where(StockTransaction.organization_id == company_id)
        .order_by(StockTransaction.created_at.desc(), StockTransaction.id),
        per_page=30,
        max_per_page=30,
        error_out=False,
    )
    return render_template("operations/journal.html", page=page, **ctx)


@bp.route(
    "/companies/<uuid:company_id>/operations/journal/<uuid:record_id>", methods=["GET", "POST"]
)
@login_required
def posting(company_id, record_id):
    ctx = context(company_id)
    row = scoped(StockTransaction, company_id, record_id)
    form = ReverseForm(idempotency_key=secrets.token_urlsafe(24))
    if form.validate_on_submit():
        try:
            service.reverse_stock(
                company_id, record_id, form.idempotency_key.data, form.reason.data
            )
        except DomainError as exc:
            return error(exc)
        flash("Compensating reversal posted; original history preserved.", "success")
        return redirect(
            url_for("operations.posting", company_id=company_id, record_id=record_id), code=303
        )
    lines = list(
        db.session.scalars(
            select(StockTransactionLine).where(
                StockTransactionLine.organization_id == company_id,
                StockTransactionLine.transaction_id == row.id,
            )
        )
    )
    lots = {
        r.id: r for r in db.session.scalars(select(Lot).where(Lot.organization_id == company_id))
    }
    locations = {
        r.id: r
        for r in db.session.scalars(
            select(StorageLocation).where(StorageLocation.organization_id == company_id)
        )
    }
    return render_template(
        "operations/posting.html",
        record=row,
        lines=lines,
        lots=lots,
        locations=locations,
        form=form,
        can_reverse=allowed(company_id, "inventory.transfer")
        and row.kind in ("receipts", "transfers"),
        **ctx,
    ), (422 if request.method == "POST" else 200)


for resource in service.DOCUMENTS:
    base = f"/companies/<uuid:company_id>/operations/{resource}"
    for suffix, endpoint, view, methods in [
        ("", "listing", listing, ["GET"]),
        ("/new", "create", create, ["GET", "POST"]),
        ("/<uuid:record_id>", "detail", detail, ["GET"]),
        ("/<uuid:record_id>/edit", "edit", edit, ["GET", "POST"]),
        ("/<uuid:record_id>/post", "post", post, ["POST"]),
        ("/<uuid:record_id>/delete", "delete", delete, ["POST"]),
    ]:
        bp.add_url_rule(base + suffix, endpoint, view, defaults={"kind": resource}, methods=methods)
    for line_resource in (
        ["production-inputs", "production-outputs"] if resource == "production" else [resource]
    ):
        bp.add_url_rule(
            base + f"/<uuid:record_id>/lines/{line_resource}",
            "line_add",
            line_add,
            defaults={"kind": resource, "line_kind": line_resource},
            methods=["POST"],
        )
        bp.add_url_rule(
            base + f"/<uuid:record_id>/lines/{line_resource}/<uuid:line_id>/delete",
            "line_delete",
            line_delete,
            defaults={"kind": resource, "line_kind": line_resource},
            methods=["POST"],
        )

        bp.add_url_rule(
            base + f"/<uuid:record_id>/lines/{line_resource}/<uuid:line_id>/edit",
            "line_edit",
            line_edit,
            defaults={"kind": resource, "line_kind": line_resource},
            methods=["GET", "POST"],
        )
