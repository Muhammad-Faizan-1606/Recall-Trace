"""Reviewed notice forms and recipient-restricted acknowledgement portal."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import SelectField, StringField, TextAreaField
from wtforms.fields import SelectChoice
from wtforms.validators import DataRequired, Length

from app.extensions import db
from app.forms import ActionForm
from app.models import Organization
from app.models.evidence import (
    Document,
    JobOutbox,
    NoticeAcknowledgement,
    NoticeDelivery,
    RecallNotice,
)
from app.models.master import PartnerContact
from app.models.recall import RecallCase
from app.policies import allowed, require
from app.services import notices
from app.services.business import DomainError

bp = Blueprint("notices", __name__)
BASE = "/companies/<uuid:company_id>/notices"


class NoticeForm(FlaskForm):
    case_id = SelectField("Approved recall case", validators=[DataRequired()])
    contact_id = SelectField("Affected customer contact", validators=[DataRequired()])


class NoticeEditForm(ActionForm):
    subject = StringField("Subject", validators=[DataRequired(), Length(max=160)])
    body = TextAreaField(
        "Recipient-specific instructions", validators=[DataRequired(), Length(max=20000)]
    )


class AcknowledgementForm(FlaskForm):
    method = SelectField(
        "Acknowledgement method",
        choices=[
            SelectChoice(value, value.capitalize())
            for value in ("email", "phone", "written", "portal")
        ],
    )
    safe_note = TextAreaField(
        "Recorded evidence of acknowledgement (no secrets)", validators=[Length(max=2000)]
    )


class ReconciliationForm(FlaskForm):
    outcome = SelectField(
        "Provider-confirmed outcome",
        choices=[
            SelectChoice("sent", "Sent (provider receipt required)"),
            SelectChoice("not_sent", "Not sent"),
        ],
    )
    document_id = SelectField("Clean private evidence", validators=[DataRequired()])
    provider_reference = StringField("Provider receipt reference", validators=[Length(max=160)])


def failure(exc):
    db.session.rollback()
    return render_template("error.html", message=str(exc)), 409


def context(company_id):
    member = notices.viewer(company_id)
    ctx = {
        "company_id": company_id,
        "member": member,
        "partner_view": bool(member.partner_id),
        "can_prepare": not member.partner_id and allowed(company_id, "notice.prepare"),
        "can_approve": not member.partner_id and allowed(company_id, "notice.approve"),
        "can_acknowledge": bool(member.partner_id) or allowed(company_id, "notice.acknowledge"),
    }
    # The internal workspace navigation itself requires an unrestricted membership.
    if not member.partner_id:
        ctx["company"] = db.session.get(Organization, company_id)
    return ctx


@bp.get(BASE)
@login_required
def listing(company_id):
    ctx = context(company_id)
    query = select(RecallNotice).where(RecallNotice.organization_id == company_id)
    if ctx["member"].partner_id:
        query = query.join(PartnerContact, PartnerContact.id == RecallNotice.contact_id).where(
            PartnerContact.partner_id == ctx["member"].partner_id,
            RecallNotice.status.in_(["approved", "queued", "sent", "local_written", "ambiguous"]),
        )
    rows = db.paginate(
        query.order_by(RecallNotice.created_at.desc()),
        per_page=30,
        max_per_page=30,
        error_out=False,
    )
    return render_template("notices/list.html", page=rows, **ctx)


@bp.route(BASE + "/new", methods=["GET", "POST"])
@login_required
def create(company_id):
    require(company_id, "notice.prepare")
    form = NoticeForm()
    cases = db.session.scalars(
        select(RecallCase)
        .where(RecallCase.organization_id == company_id, RecallCase.status == "approved")
        .order_by(RecallCase.reference)
    ).all()
    contacts = db.session.scalars(
        select(PartnerContact)
        .where(
            PartnerContact.organization_id == company_id,
            PartnerContact.archived_at.is_(None),
            PartnerContact.email.is_not(None),
        )
        .order_by(PartnerContact.name)
    ).all()
    form.case_id.choices = [
        SelectChoice(str(row.id), f"{row.reference} — {row.title}") for row in cases
    ]
    form.contact_id.choices = [
        SelectChoice(str(row.id), f"{row.name} — {row.email}") for row in contacts
    ]
    if form.validate_on_submit():
        try:
            row = notices.create_notice(company_id, form.case_id.data, form.contact_id.data)
        except DomainError as exc:
            return failure(exc)
        return redirect(
            url_for("notices.detail", company_id=company_id, notice_id=row.id), code=303
        )
    return render_template(
        "form.html",
        title="Prepare recipient-specific notice",
        form=form,
        submit="Prepare draft",
        **context(company_id),
    ), (422 if request.method == "POST" else 200)


@bp.get(BASE + "/<uuid:notice_id>")
@login_required
def detail(company_id, notice_id):
    row = notices.readable(company_id, notice_id)
    ctx = context(company_id)
    deliveries = (
        []
        if ctx["partner_view"]
        else db.session.scalars(
            select(NoticeDelivery)
            .where(NoticeDelivery.organization_id == company_id, NoticeDelivery.notice_id == row.id)
            .order_by(NoticeDelivery.attempt)
        ).all()
    )
    jobs = (
        []
        if ctx["partner_view"]
        else db.session.scalars(
            select(JobOutbox).where(
                JobOutbox.organization_id == company_id,
                JobOutbox.deduplication_key == f"notice:{row.id}:{row.revision}",
            )
        ).all()
    )
    acknowledgement = db.session.scalar(
        select(NoticeAcknowledgement).where(
            NoticeAcknowledgement.organization_id == company_id,
            NoticeAcknowledgement.notice_id == row.id,
        )
    )
    form = AcknowledgementForm()
    reconciliation_form = ReconciliationForm()
    if not ctx["partner_view"]:
        documents = db.session.scalars(
            select(Document)
            .where(
                Document.organization_id == company_id,
                Document.state == "active",
                Document.scan_status == "clean",
                Document.archived_at.is_(None),
            )
            .order_by(Document.created_at.desc())
            .limit(500)
        ).all()
        reconciliation_form.document_id.choices = [
            SelectChoice(str(row.id), row.original_name) for row in documents
        ]
    if ctx["partner_view"]:
        form.method.choices = [SelectChoice("portal", "Portal")]
    return render_template(
        "notices/detail.html",
        record=row,
        deliveries=deliveries,
        jobs=jobs,
        acknowledgement=acknowledgement,
        acknowledgement_form=form,
        reconciliation_form=reconciliation_form,
        action_form=ActionForm(version=str(row.version)),
        **ctx,
    )


@bp.route(BASE + "/<uuid:notice_id>/edit", methods=["GET", "POST"])
@login_required
def edit(company_id, notice_id):
    require(company_id, "notice.prepare")
    row = notices.readable(company_id, notice_id)
    if row.status != "draft":
        return failure(
            DomainError("Only a draft notice can be edited. Create a new revision for corrections.")
        )
    form = NoticeEditForm(obj=row)
    if request.method == "GET":
        form.version.data = str(row.version)
    if form.validate_on_submit():
        try:
            notices.edit_notice(
                company_id, notice_id, form.subject.data, form.body.data, int(form.version.data)
            )
        except DomainError as exc:
            return failure(exc)
        return redirect(
            url_for("notices.detail", company_id=company_id, notice_id=notice_id), code=303
        )
    return render_template(
        "form.html",
        title="Edit draft notice",
        form=form,
        submit="Save draft",
        **context(company_id),
    ), (422 if request.method == "POST" else 200)


@bp.post(BASE + "/<uuid:notice_id>/approve")
@login_required
def approve(company_id, notice_id):
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        notices.approve_notice(company_id, notice_id, int(form.version.data))
    except DomainError as exc:
        return failure(exc)
    flash("Notice approved; delivery remains a separate committed action.", "success")
    return redirect(url_for("notices.detail", company_id=company_id, notice_id=notice_id), code=303)


@bp.post(BASE + "/<uuid:notice_id>/queue")
@login_required
def queue(company_id, notice_id):
    if not FlaskForm().validate_on_submit():
        abort(400)
    try:
        notices.enqueue_notice(company_id, notice_id)
    except DomainError as exc:
        return failure(exc)
    flash(
        "Committed delivery intent. The configured worker must process it; this is not proof of delivery.",
        "success",
    )
    return redirect(url_for("notices.detail", company_id=company_id, notice_id=notice_id), code=303)


@bp.post(BASE + "/<uuid:notice_id>/delete")
@login_required
def delete(company_id, notice_id):
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        notices.delete_notice(company_id, notice_id, int(form.version.data))
    except DomainError as exc:
        return failure(exc)
    return redirect(url_for("notices.listing", company_id=company_id), code=303)


@bp.post(BASE + "/<uuid:notice_id>/acknowledge")
@login_required
def acknowledge(company_id, notice_id):
    ctx = context(company_id)
    form = AcknowledgementForm()
    if ctx["partner_view"]:
        form.method.choices = [SelectChoice("portal", "Portal")]
    if not form.validate_on_submit():
        abort(422)
    try:
        notices.acknowledge(company_id, notice_id, form.method.data, form.safe_note.data or "")
    except DomainError as exc:
        return failure(exc)
    flash(
        "Acknowledgement recorded. Physical recovery requires separate verified evidence.",
        "success",
    )
    return redirect(url_for("notices.detail", company_id=company_id, notice_id=notice_id), code=303)


@bp.post("/companies/<uuid:company_id>/outbox/<uuid:job_id>/retry")
@login_required
def retry(company_id, job_id):
    if not FlaskForm().validate_on_submit():
        abort(400)
    from app.services.jobs import retry_failed

    try:
        retry_failed(company_id, job_id)
    except DomainError as exc:
        return failure(exc)
    return redirect(url_for("notices.listing", company_id=company_id), code=303)


@bp.post("/companies/<uuid:company_id>/notice-deliveries/<uuid:delivery_id>/reconcile")
@login_required
def reconcile(company_id, delivery_id):
    require(company_id, "notice.approve")
    form = ReconciliationForm()
    documents = db.session.scalars(
        select(Document)
        .where(
            Document.organization_id == company_id,
            Document.state == "active",
            Document.scan_status == "clean",
            Document.archived_at.is_(None),
        )
        .order_by(Document.created_at.desc())
        .limit(500)
    ).all()
    form.document_id.choices = [SelectChoice(str(row.id), row.original_name) for row in documents]
    if not form.validate_on_submit():
        abort(422)
    try:
        delivery = notices.reconcile_delivery(
            company_id,
            delivery_id,
            form.outcome.data,
            form.document_id.data,
            form.provider_reference.data or None,
        )
    except DomainError as exc:
        return failure(exc)
    return redirect(
        url_for("notices.detail", company_id=company_id, notice_id=delivery.notice_id), code=303
    )
