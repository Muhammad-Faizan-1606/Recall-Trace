"""Explicit evidence, catalog import, private export and own notification forms."""

import io
import secrets

from flask import Blueprint, abort, flash, redirect, render_template, send_file, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from sqlalchemy import select
from wtforms import BooleanField, SelectField, StringField
from wtforms.fields import SelectChoice
from wtforms.validators import DataRequired, Length, Regexp

from app.extensions import db
from app.forms import ActionForm
from app.models import Organization
from app.models.evidence import Document, ExportJob, ImportJob, Notification, NotificationPreference
from app.policies import allowed, membership_for, require
from app.services import evidence
from app.services.business import DomainError, scoped

bp = Blueprint("evidence", __name__)
BASE = "/companies/<uuid:company_id>"


class UploadForm(FlaskForm):
    file = FileField(
        "PDF, PNG or JPEG (up to 10 MiB)", validators=[FileRequired()], id="evidence-file"
    )


class ImportForm(FlaskForm):
    file = FileField(
        "UTF-8 item CSV (code,name,kind)", validators=[FileRequired()], id="import-file"
    )
    identifier = StringField(
        "Import identifier", validators=[DataRequired(), Regexp(r"^[A-Za-z0-9_-]{16,100}$")]
    )


class ExportForm(FlaskForm):
    kind = SelectField(
        "Export",
        choices=[SelectChoice("items", "Catalog items"), SelectChoice("stock", "Stock balances")],
    )


class PreferenceForm(FlaskForm):
    event_type = SelectField(
        "Event",
        choices=[SelectChoice(kind, kind.capitalize()) for kind in sorted(evidence.EVENT_TYPES)],
    )
    enabled = BooleanField("Show in-app notifications")


class RenameForm(ActionForm):
    original_name = StringField("Display filename", validators=[DataRequired(), Length(max=240)])


def context(company_id):
    member = membership_for(company_id)
    return {
        "company_id": company_id,
        "company": db.session.get(Organization, company_id),
        "member": member,
        "can_upload": allowed(company_id, "evidence.upload"),
        "can_import": allowed(company_id, "catalog.manage"),
        "can_export": allowed(company_id, "reports.export"),
    }


def failure(exc):
    db.session.rollback()
    return render_template("error.html", message=str(exc)), 409


@bp.get(BASE + "/evidence")
@login_required
def listing(company_id):
    require(company_id, "evidence.read")
    ctx = context(company_id)
    documents = db.paginate(
        select(Document)
        .where(
            Document.organization_id == company_id, Document.state.in_(["active", "quarantined"])
        )
        .order_by(Document.created_at.desc()),
        per_page=30,
        max_per_page=30,
        error_out=False,
    )
    imports = db.session.scalars(
        select(ImportJob)
        .where(
            ImportJob.organization_id == company_id, ImportJob.requested_by_id == ctx["member"].id
        )
        .order_by(ImportJob.created_at.desc())
        .limit(30)
    ).all()
    exports = db.session.scalars(
        select(ExportJob)
        .where(
            ExportJob.organization_id == company_id, ExportJob.requested_by_id == ctx["member"].id
        )
        .order_by(ExportJob.created_at.desc())
        .limit(30)
    ).all()
    return render_template(
        "evidence/list.html",
        page=documents,
        imports=imports,
        exports=exports,
        upload_form=UploadForm(),
        import_form=ImportForm(identifier=secrets.token_urlsafe(24)),
        export_form=ExportForm(),
        **ctx,
    )


@bp.post(BASE + "/evidence/upload")
@login_required
def upload(company_id):
    require(company_id, "evidence.upload")
    form = UploadForm()
    if not form.validate_on_submit():
        abort(422)
    try:
        record = evidence.upload(company_id, form.file.data.filename, form.file.data.stream)
    except DomainError as exc:
        return failure(exc)
    flash(
        "Evidence stored privately. Download remains blocked unless scanning reports clean.",
        "success",
    )
    return redirect(
        url_for("evidence.detail", company_id=company_id, document_id=record.id), code=303
    )


@bp.get(BASE + "/evidence/<uuid:document_id>")
@login_required
def detail(company_id, document_id):
    require(company_id, "evidence.read")
    row = scoped(Document, company_id, document_id)
    if row.state not in {"active", "quarantined"}:
        abort(404)
    return render_template(
        "evidence/detail.html",
        record=row,
        action_form=ActionForm(version=str(row.version)),
        rename_form=RenameForm(version=str(row.version), original_name=row.original_name),
        **context(company_id),
    )


@bp.post(BASE + "/evidence/<uuid:document_id>/rename")
@login_required
def rename(company_id, document_id):
    require(company_id, "evidence.upload")
    form = RenameForm()
    if not form.validate_on_submit():
        abort(422)
    row = scoped(Document, company_id, document_id, lock=True)
    if row.version != int(form.version.data) or row.state not in {"active", "quarantined"}:
        return failure(DomainError("Document changed or cannot be renamed."))
    name = form.original_name.data.strip()
    if "/" in name or "\\" in name or any(ord(c) < 32 for c in name):
        return failure(DomainError("Choose a printable display filename without path separators."))
    row.original_name = name
    db.session.commit()
    return redirect(url_for("evidence.detail", company_id=company_id, document_id=row.id), code=303)


@bp.get(BASE + "/evidence/<uuid:document_id>/download")
@login_required
def download(company_id, document_id):
    try:
        row, data = evidence.downloadable(company_id, document_id)
    except DomainError as exc:
        return failure(exc)
    response = send_file(
        io.BytesIO(data),
        mimetype=row.media_type,
        download_name=row.original_name,
        as_attachment=True,
        max_age=0,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.post(BASE + "/evidence/<uuid:document_id>/rescan")
@login_required
def rescan(company_id, document_id):
    if not FlaskForm().validate_on_submit():
        abort(400)
    try:
        evidence.rescan(company_id, document_id)
    except DomainError as exc:
        return failure(exc)
    return redirect(
        url_for("evidence.detail", company_id=company_id, document_id=document_id), code=303
    )


@bp.post(BASE + "/evidence/<uuid:document_id>/delete")
@login_required
def delete(company_id, document_id):
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        evidence.remove_document(company_id, document_id, int(form.version.data))
    except DomainError as exc:
        return failure(exc)
    return redirect(url_for("evidence.listing", company_id=company_id), code=303)


@bp.post(BASE + "/imports/items")
@login_required
def prepare_import(company_id):
    form = ImportForm()
    if not form.validate_on_submit():
        abort(422)
    try:
        job = evidence.prepare_import(
            company_id, form.file.data.filename, form.file.data.stream, form.identifier.data
        )
    except DomainError as exc:
        return failure(exc)
    return redirect(
        url_for("evidence.import_detail", company_id=company_id, job_id=job.id), code=303
    )


@bp.get(BASE + "/imports/<uuid:job_id>")
@login_required
def import_detail(company_id, job_id):
    require(company_id, "catalog.manage")
    member = membership_for(company_id)
    job = scoped(ImportJob, company_id, job_id)
    if job.requested_by_id != member.id:
        abort(404)
    source = scoped(Document, company_id, job.source_document_id)
    try:
        rows = evidence.parse_items_csv(evidence.read_bytes(source))[:30]
    except DomainError as exc:
        return failure(exc)
    return render_template(
        "evidence/import.html", job=job, rows=rows, action_form=FlaskForm(), **context(company_id)
    )


@bp.post(BASE + "/imports/<uuid:job_id>/commit")
@login_required
def commit_import(company_id, job_id):
    if not FlaskForm().validate_on_submit():
        abort(400)
    try:
        evidence.commit_import(company_id, job_id)
    except DomainError as exc:
        return failure(exc)
    flash("All imported rows committed atomically.", "success")
    return redirect(
        url_for("evidence.import_detail", company_id=company_id, job_id=job_id), code=303
    )


@bp.post(BASE + "/imports/<uuid:job_id>/cancel")
@login_required
def cancel_import(company_id, job_id):
    if not FlaskForm().validate_on_submit():
        abort(400)
    try:
        evidence.cancel_import(company_id, job_id)
    except DomainError as exc:
        return failure(exc)
    return redirect(
        url_for("evidence.import_detail", company_id=company_id, job_id=job_id), code=303
    )


@bp.post(BASE + "/exports")
@login_required
def create_export(company_id):
    form = ExportForm()
    if not form.validate_on_submit():
        abort(422)
    try:
        job = evidence.create_export(company_id, form.kind.data)
    except DomainError as exc:
        return failure(exc)
    return redirect(
        url_for("evidence.download", company_id=company_id, document_id=job.output_document_id),
        code=303,
    )


@bp.get(BASE + "/notifications")
@login_required
def notifications(company_id):
    ctx = context(company_id)
    rows = db.paginate(
        select(Notification)
        .where(
            Notification.organization_id == company_id,
            Notification.membership_id == ctx["member"].id,
            Notification.archived_at.is_(None),
        )
        .order_by(Notification.created_at.desc()),
        per_page=30,
        max_per_page=30,
        error_out=False,
    )
    preferences = db.session.scalars(
        select(NotificationPreference).where(
            NotificationPreference.organization_id == company_id,
            NotificationPreference.membership_id == ctx["member"].id,
        )
    ).all()
    return render_template(
        "evidence/notifications.html",
        page=rows,
        preferences=preferences,
        preference_form=PreferenceForm(),
        action_form=FlaskForm(),
        **ctx,
    )


@bp.post(BASE + "/notifications/<uuid:notification_id>/read")
@login_required
def mark_read(company_id, notification_id):
    if not FlaskForm().validate_on_submit():
        abort(400)
    evidence.mark_notification(company_id, notification_id)
    return redirect(url_for("evidence.notifications", company_id=company_id), code=303)


@bp.post(BASE + "/notification-preferences")
@login_required
def preferences(company_id):
    form = PreferenceForm()
    if not form.validate_on_submit():
        abort(422)
    evidence.set_preference(company_id, form.event_type.data, form.enabled.data)
    return redirect(url_for("evidence.notifications", company_id=company_id), code=303)
