"""Server-rendered quality definitions, observations, issues and hold decisions."""

import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import HiddenField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.fields import SelectChoice
from wtforms.validators import DataRequired, Length, NumberRange

from app.extensions import db
from app.models import Organization
from app.models.master import Lot
from app.models.quality import (
    HoldReview,
    Inspection,
    InspectionCheck,
    InspectionResult,
    InspectionTemplate,
    Nonconformance,
    QualityDocument,
    QualityHold,
)
from app.policies import allowed
from app.services import quality as service
from app.services.business import DomainError, actor, scoped

bp = Blueprint("quality", __name__, url_prefix="/companies/<uuid:company_id>/quality")


class TemplateForm(FlaskForm):
    version = HiddenField()
    code = StringField("Code", validators=[DataRequired(), Length(max=60)])
    revision = IntegerField("Revision", default=1, validators=[DataRequired(), NumberRange(min=1)])


class CheckForm(FlaskForm):
    version = HiddenField()
    sequence = IntegerField("Sequence", validators=[DataRequired(), NumberRange(min=1)])
    label = StringField("Criterion", validators=[DataRequired(), Length(max=160)])
    value_type = SelectField(
        "Observation type",
        choices=[
            SelectChoice("number", "Number"),
            SelectChoice("text", "Text"),
            SelectChoice("boolean", "True/false"),
        ],
    )
    rule = TextAreaField(
        "Rule JSON (min, max, equals only)",
        default="{}",
        validators=[DataRequired(), Length(max=2000)],
    )


class InspectionForm(FlaskForm):
    reference = StringField("Reference", validators=[DataRequired(), Length(max=80)])
    lot_id = SelectField("Lot", validators=[DataRequired()])
    template_id = SelectField("Published template revision", validators=[DataRequired()])


class InspectionReferenceForm(FlaskForm):
    version = HiddenField()
    reference = StringField("Reference", validators=[DataRequired(), Length(max=80)])


class ObservationForm(FlaskForm):
    version = HiddenField()
    check_id = SelectField("Criterion", validators=[DataRequired()])
    value = StringField(
        "Observation (boolean: true or false)", validators=[DataRequired(), Length(max=1000)]
    )
    comment = TextAreaField("Comment", validators=[Length(max=4000)])


class IssueForm(FlaskForm):
    version = HiddenField()
    reference = StringField("Reference", validators=[DataRequired(), Length(max=80)])
    lot_id = SelectField("Lot", validators=[DataRequired()])
    inspection_id = SelectField("Inspection evidence", choices=[])
    description = TextAreaField("Description", validators=[DataRequired(), Length(max=4000)])
    severity = SelectField(
        "Severity",
        choices=[SelectChoice(v, v.capitalize()) for v in ("low", "medium", "high", "critical")],
    )


class HoldForm(FlaskForm):
    lot_id = SelectField("Lot", validators=[DataRequired()])
    nonconformance_id = SelectField("Quality issue", choices=[])
    reason = TextAreaField("Reason", validators=[DataRequired(), Length(max=4000)])


class ReviewForm(FlaskForm):
    version = HiddenField()
    decision = SelectField(
        "Decision",
        choices=[SelectChoice("retain", "Retain hold"), SelectChoice("release", "Release hold")],
    )
    reason = TextAreaField(
        "Independent review evidence", validators=[DataRequired(), Length(max=4000)]
    )


class ActionForm(FlaskForm):
    version = HiddenField()


class DocumentForm(FlaskForm):
    document_id = SelectField("Scanned private document", validators=[DataRequired()])


def context(company_id):
    actor(company_id, "catalog.read")
    return {"company_id": company_id, "company": db.session.get(Organization, company_id)}


def choices(model, company_id, label, *where):
    return [
        SelectChoice(str(r.id), label(r))
        for r in db.session.scalars(
            select(model)
            .where(model.organization_id == company_id, *where)
            .order_by(model.created_at.desc())
            .limit(1000)
        )
    ]


def available_documents(company_id):
    if not allowed(company_id, "evidence.read"):
        return []
    from app.models.evidence import Document

    return choices(
        Document,
        company_id,
        lambda r: r.original_name,
        Document.scan_status == "clean",
        Document.state == "active",
        Document.archived_at.is_(None),
    )


def run_action(company_id, function, *args, destination="quality.dashboard", **kwargs):
    form = ActionForm()
    if not form.validate_on_submit():
        return "Invalid action.", 400
    try:
        function(company_id, *args, **kwargs)
    except DomainError as exc:
        flash(str(exc), "danger")
        return render_template("quality/error.html", **context(company_id), message=str(exc)), 409
    flash("Quality action saved.", "success")
    return redirect(url_for(destination, company_id=company_id), code=303)


@bp.get("")
@login_required
def dashboard(company_id):
    return render_template(
        "quality/dashboard.html",
        **context(company_id),
        templates=db.session.scalars(
            select(InspectionTemplate)
            .where(InspectionTemplate.organization_id == company_id)
            .order_by(InspectionTemplate.created_at.desc())
            .limit(100)
        ).all(),
        inspections=db.session.scalars(
            select(Inspection)
            .where(Inspection.organization_id == company_id)
            .order_by(Inspection.created_at.desc())
            .limit(100)
        ).all(),
        issues=db.session.scalars(
            select(Nonconformance)
            .where(Nonconformance.organization_id == company_id)
            .order_by(Nonconformance.created_at.desc())
            .limit(100)
        ).all(),
        holds=db.session.scalars(
            select(QualityHold)
            .where(QualityHold.organization_id == company_id)
            .order_by(QualityHold.created_at.desc())
            .limit(100)
        ).all(),
    )


@bp.route("/templates/new", methods=["GET", "POST"])
@bp.route("/templates/<uuid:template_id>/edit", methods=["GET", "POST"])
@login_required
def template_form(company_id, template_id=None):
    actor(company_id, "quality.inspect")
    row = scoped(InspectionTemplate, company_id, template_id) if template_id else None
    form = TemplateForm(obj=row)
    if form.validate_on_submit():
        try:
            row = service.save_template(
                company_id,
                form.code.data,
                form.revision.data,
                template_id,
                form.version.data or None,
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            return redirect(
                url_for("quality.template", company_id=company_id, template_id=row.id), code=303
            )
    return render_template(
        "quality/form.html", **context(company_id), form=form, title="Inspection template revision"
    ), 422 if request.method == "POST" else 200


@bp.route("/templates/<uuid:template_id>", methods=["GET", "POST"])
@login_required
def template(company_id, template_id):
    row = scoped(InspectionTemplate, company_id, template_id)
    form = CheckForm()
    if form.validate_on_submit():
        try:
            rule = json.loads(form.rule.data)
            service.save_check(
                company_id, row.id, form.sequence.data, form.label.data, form.value_type.data, rule
            )
        except (DomainError, ValueError) as exc:
            flash(str(exc) if isinstance(exc, DomainError) else "Enter valid rule JSON.", "danger")
        else:
            return redirect(
                url_for("quality.template", company_id=company_id, template_id=row.id), code=303
            )
    checks = db.session.scalars(
        select(InspectionCheck)
        .where(InspectionCheck.template_id == row.id)
        .order_by(InspectionCheck.sequence)
    ).all()
    return render_template(
        "quality/template.html",
        **context(company_id),
        row=row,
        checks=checks,
        form=form,
        action=ActionForm(version=str(row.version)),
    ), 422 if request.method == "POST" else 200


@bp.post("/templates/<uuid:template_id>/publish")
@login_required
def publish(company_id, template_id):
    return run_action(
        company_id, service.publish_template, template_id, version=request.form.get("version")
    )


@bp.post("/templates/<uuid:template_id>/delete")
@login_required
def delete_template(company_id, template_id):
    return run_action(
        company_id, service.delete_template, template_id, version=request.form.get("version")
    )


@bp.post("/checks/<uuid:check_id>/delete")
@login_required
def delete_check(company_id, check_id):
    return run_action(
        company_id, service.delete_check, check_id, version=request.form.get("version")
    )


@bp.route("/inspections/new", methods=["GET", "POST"])
@login_required
def inspection_form(company_id):
    actor(company_id, "quality.inspect")
    form = InspectionForm()
    form.lot_id.choices = choices(Lot, company_id, lambda r: r.lot_code, Lot.archived_at.is_(None))
    form.template_id.choices = choices(
        InspectionTemplate,
        company_id,
        lambda r: f"{r.code} revision {r.revision}",
        InspectionTemplate.status == "published",
    )
    if form.validate_on_submit():
        try:
            row = service.create_inspection(
                company_id, form.reference.data, form.lot_id.data, form.template_id.data
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            return redirect(
                url_for("quality.inspection", company_id=company_id, inspection_id=row.id), code=303
            )
    return render_template(
        "quality/form.html", **context(company_id), form=form, title="Inspect lot"
    ), 422 if request.method == "POST" else 200


@bp.route("/inspections/<uuid:inspection_id>", methods=["GET", "POST"])
@login_required
def inspection(company_id, inspection_id):
    row = scoped(Inspection, company_id, inspection_id)
    form = ObservationForm(version=str(row.version))
    checks = db.session.scalars(
        select(InspectionCheck)
        .where(InspectionCheck.template_id == row.template_id)
        .order_by(InspectionCheck.sequence)
    ).all()
    form.check_id.choices = [SelectChoice(str(r.id), r.label) for r in checks]
    if form.validate_on_submit():
        try:
            service.observe(
                company_id,
                row.id,
                form.check_id.data,
                form.value.data,
                form.comment.data,
                form.version.data or None,
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            return redirect(
                url_for("quality.inspection", company_id=company_id, inspection_id=row.id), code=303
            )
    documents = DocumentForm()
    documents.document_id.choices = available_documents(company_id)
    return render_template(
        "quality/inspection.html",
        **context(company_id),
        row=row,
        checks=checks,
        results=db.session.scalars(
            select(InspectionResult).where(InspectionResult.inspection_id == row.id)
        ).all(),
        form=form,
        documents=documents,
        links=db.session.scalars(
            select(QualityDocument).where(QualityDocument.inspection_id == row.id)
        ).all(),
        action=ActionForm(version=str(row.version)),
    ), 422 if request.method == "POST" else 200


@bp.post("/inspections/<uuid:inspection_id>/complete")
@login_required
def complete(company_id, inspection_id):
    return run_action(
        company_id, service.complete_inspection, inspection_id, version=request.form.get("version")
    )


@bp.post("/inspections/<uuid:inspection_id>/delete")
@login_required
def delete_inspection(company_id, inspection_id):
    return run_action(
        company_id, service.delete_inspection, inspection_id, version=request.form.get("version")
    )


@bp.post("/inspections/<uuid:inspection_id>/documents")
@login_required
def inspection_document(company_id, inspection_id):
    return run_action(
        company_id,
        service.attach_document,
        request.form.get("document_id"),
        inspection_id=inspection_id,
    )


@bp.route("/issues/new", methods=["GET", "POST"])
@bp.route("/issues/<uuid:record_id>/edit", methods=["GET", "POST"])
@login_required
def issue_form(company_id, record_id=None):
    actor(company_id, "quality.inspect")
    row = scoped(Nonconformance, company_id, record_id) if record_id else None
    form = IssueForm(obj=row)
    form.lot_id.choices = choices(Lot, company_id, lambda r: r.lot_code)
    form.inspection_id.choices = [SelectChoice("", "No inspection evidence")] + choices(
        Inspection, company_id, lambda r: r.reference
    )
    if form.validate_on_submit():
        try:
            service.save_nonconformance(
                company_id,
                form.reference.data,
                form.lot_id.data,
                form.description.data,
                form.severity.data,
                form.inspection_id.data or None,
                record_id,
                form.version.data or None,
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            return redirect(url_for("quality.dashboard", company_id=company_id), code=303)
    return render_template(
        "quality/form.html", **context(company_id), form=form, title="Quality issue"
    ), 422 if request.method == "POST" else 200


@bp.post("/issues/<uuid:record_id>/resolve")
@login_required
def resolve(company_id, record_id):
    return run_action(
        company_id, service.resolve_nonconformance, record_id, version=request.form.get("version")
    )


@bp.route("/holds/new", methods=["GET", "POST"])
@login_required
def hold_form(company_id):
    actor(company_id, "quality.hold")
    form = HoldForm()
    form.lot_id.choices = choices(Lot, company_id, lambda r: r.lot_code)
    form.nonconformance_id.choices = [SelectChoice("", "No linked issue")] + choices(
        Nonconformance, company_id, lambda r: r.reference, Nonconformance.status == "open"
    )
    if form.validate_on_submit():
        try:
            row = service.place_hold(
                company_id, form.lot_id.data, form.reason.data, form.nonconformance_id.data or None
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            return redirect(
                url_for("quality.hold", company_id=company_id, hold_id=row.id), code=303
            )
    return render_template(
        "quality/form.html", **context(company_id), form=form, title="Place lot hold"
    ), 422 if request.method == "POST" else 200


@bp.route("/holds/<uuid:hold_id>", methods=["GET", "POST"])
@login_required
def hold(company_id, hold_id):
    row = scoped(QualityHold, company_id, hold_id)
    form = ReviewForm(version=str(row.version))
    if form.validate_on_submit():
        try:
            service.review_hold(
                company_id, row.id, form.decision.data, form.reason.data, form.version.data or None
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            return redirect(
                url_for("quality.hold", company_id=company_id, hold_id=row.id), code=303
            )
    return render_template(
        "quality/hold.html",
        **context(company_id),
        row=row,
        form=form,
        reviews=db.session.scalars(
            select(HoldReview).where(HoldReview.hold_id == row.id).order_by(HoldReview.created_at)
        ).all(),
    ), 422 if request.method == "POST" else 200


@bp.route("/checks/<uuid:check_id>/edit", methods=["GET", "POST"])
@login_required
def check_editor(company_id, check_id):
    actor(company_id, "quality.inspect")
    row = scoped(InspectionCheck, company_id, check_id)
    form = CheckForm(obj=row)
    if request.method == "GET":
        form.rule.data = json.dumps(row.rule_definition)
    if form.validate_on_submit():
        try:
            rule = json.loads(form.rule.data)
            service.save_check(
                company_id,
                row.template_id,
                form.sequence.data,
                form.label.data,
                form.value_type.data,
                rule,
                row.id,
                request.form.get("version"),
            )
        except (DomainError, ValueError) as exc:
            flash(str(exc) if isinstance(exc, DomainError) else "Enter valid rule JSON.", "danger")
        else:
            return redirect(
                url_for("quality.template", company_id=company_id, template_id=row.template_id),
                code=303,
            )
    return render_template(
        "quality/form.html", **context(company_id), form=form, title="Edit draft criterion"
    ), 422 if request.method == "POST" else 200


@bp.route("/inspections/<uuid:inspection_id>/edit", methods=["GET", "POST"])
@login_required
def inspection_editor(company_id, inspection_id):
    actor(company_id, "quality.inspect")
    row = scoped(Inspection, company_id, inspection_id)
    form = InspectionReferenceForm(obj=row)
    if form.validate_on_submit():
        try:
            service.edit_inspection(
                company_id, row.id, form.reference.data, form.version.data or None
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            return redirect(
                url_for("quality.inspection", company_id=company_id, inspection_id=row.id), code=303
            )
    return render_template(
        "quality/form.html",
        **context(company_id),
        form=form,
        title="Edit draft inspection reference",
    ), 422 if request.method == "POST" else 200


@bp.post("/inspections/<uuid:inspection_id>/observations/<uuid:result_id>/delete")
@login_required
def remove_observation(company_id, inspection_id, result_id):
    return run_action(
        company_id,
        service.remove_observation,
        inspection_id,
        result_id,
        version=request.form.get("version"),
    )


@bp.get("/issues/<uuid:record_id>")
@login_required
def issue(company_id, record_id):
    row = scoped(Nonconformance, company_id, record_id)
    documents = DocumentForm()
    documents.document_id.choices = available_documents(company_id)
    return render_template(
        "quality/issue.html",
        **context(company_id),
        row=row,
        action=ActionForm(version=str(row.version)),
        documents=documents,
        links=db.session.scalars(
            select(QualityDocument).where(QualityDocument.nonconformance_id == row.id)
        ).all(),
    )


@bp.post("/issues/<uuid:record_id>/delete")
@login_required
def remove_issue(company_id, record_id):
    return run_action(
        company_id, service.remove_nonconformance, record_id, version=request.form.get("version")
    )


@bp.post("/issues/<uuid:record_id>/documents")
@login_required
def issue_document(company_id, record_id):
    return run_action(
        company_id,
        service.attach_document,
        request.form.get("document_id"),
        nonconformance_id=record_id,
    )


@bp.post("/documents/<uuid:link_id>/detach")
@login_required
def detach_document(company_id, link_id):
    return run_action(
        company_id, service.detach_document, link_id, version=request.form.get("version")
    )
