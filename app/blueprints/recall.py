"""Investigation workspace with explicit scoped recall lifecycle actions."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import BooleanField, HiddenField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length

from app.extensions import db
from app.models import Membership, Organization, User
from app.models.master import Lot
from app.models.operations import ShipmentLine
from app.models.quality import Nonconformance
from app.models.recall import (
    CaseAffectedShipment,
    CaseComment,
    CaseDocument,
    CaseSource,
    CaseTask,
    RecallCase,
    RecoveryRecord,
    TraceRun,
)
from app.services import recall as service
from app.services import trace as tracing
from app.services.business import DomainError, actor, scoped

bp = Blueprint("recall", __name__, url_prefix="/companies/<uuid:company_id>/cases")


class CaseForm(FlaskForm):
    version = HiddenField()
    reference = StringField("Reference", validators=[DataRequired(), Length(max=80)])
    title = StringField("Title", validators=[DataRequired(), Length(max=160)])
    reason = TextAreaField(
        "Suspected defect and supporting reason", validators=[DataRequired(), Length(max=4000)]
    )
    severity = SelectField(
        "Severity", choices=[(v, v.capitalize()) for v in ("low", "medium", "high", "critical")]
    )


class SourceForm(FlaskForm):
    lot_id = SelectField("Source lot", validators=[DataRequired()])
    nonconformance_id = SelectField("Supporting quality issue")
    note = TextAreaField("Source evidence", validators=[DataRequired(), Length(max=4000)])


class TraceForm(FlaskForm):
    direction = SelectField(
        "Trace direction",
        choices=[("downstream", "Downstream exposure"), ("upstream", "Upstream sources")],
    )


class TaskForm(FlaskForm):
    version = HiddenField()
    title = StringField("Task title", validators=[DataRequired(), Length(max=160)])
    description = TextAreaField("Required evidence", validators=[DataRequired(), Length(max=4000)])
    assignee_id = SelectField("Assignee", validators=[DataRequired()])
    mandatory = BooleanField("Mandatory before closure", default=True)


class CommentForm(FlaskForm):
    version = HiddenField()
    body = TextAreaField("Comment", validators=[DataRequired(), Length(max=4000)])


class ActionForm(FlaskForm):
    version = HiddenField()
    note = TextAreaField("Review / verification note", validators=[Length(max=4000)])
    acknowledgement_exception = TextAreaField(
        "Reviewed acknowledgement exception, if required", validators=[Length(max=4000)]
    )


class RecoveryForm(FlaskForm):
    shipment_line_id = SelectField("Affected shipment line", validators=[DataRequired()])
    amount = StringField(
        "Verified quantity in SKU base units", validators=[DataRequired(), Length(max=40)]
    )
    disposition = SelectField(
        "Verified disposition",
        choices=[
            ("returned", "Physically returned"),
            ("destroyed", "Confirmed destroyed"),
            ("other_resolved", "Other verified resolution"),
        ],
    )
    evidence_reference = StringField(
        "Unique physical evidence reference", validators=[DataRequired(), Length(max=100)]
    )
    evidence_note = TextAreaField(
        "Verification evidence", validators=[DataRequired(), Length(max=4000)]
    )


class DocumentForm(FlaskForm):
    document_id = SelectField("Scanned private evidence", validators=[DataRequired()])


def context(company_id):
    actor(company_id, "catalog.read")
    return {"company_id": company_id, "company": db.session.get(Organization, company_id)}


def safe_action(company_id, case_id, function, *args, **kwargs):
    form = ActionForm()
    if not form.validate_on_submit():
        return "Invalid action.", 400
    try:
        result = function(company_id, *args, **kwargs)
    except DomainError as exc:
        return render_template("quality/error.html", **context(company_id), message=str(exc)), 409
    flash("Investigation action saved.", "success")
    if isinstance(result, TraceRun):
        return redirect(
            url_for("recall.trace", company_id=company_id, trace_id=result.id), code=303
        )
    return redirect(url_for("recall.detail", company_id=company_id, case_id=case_id), code=303)


@bp.get("")
@login_required
def dashboard(company_id):
    page = db.paginate(
        select(RecallCase)
        .where(RecallCase.organization_id == company_id)
        .order_by(RecallCase.created_at.desc()),
        per_page=30,
        max_per_page=30,
        error_out=False,
    )
    return render_template("recall/dashboard.html", **context(company_id), page=page)


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<uuid:case_id>/edit", methods=["GET", "POST"])
@login_required
def editor(company_id, case_id=None):
    actor(company_id, "case.prepare")
    row = scoped(RecallCase, company_id, case_id) if case_id else None
    form = CaseForm(obj=row)
    if form.validate_on_submit():
        try:
            row = service.save_case(
                company_id,
                form.reference.data,
                form.title.data,
                form.reason.data,
                form.severity.data,
                case_id,
                form.version.data or None,
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            return redirect(
                url_for("recall.detail", company_id=company_id, case_id=row.id), code=303
            )
    return render_template(
        "quality/form.html", **context(company_id), form=form, title="Recall investigation"
    ), 422 if request.method == "POST" else 200


@bp.get("/<uuid:case_id>")
@login_required
def detail(company_id, case_id):
    ctx = context(company_id)
    row = scoped(RecallCase, company_id, case_id)
    source = SourceForm()
    source.lot_id.choices = [
        (str(r.id), r.lot_code)
        for r in db.session.scalars(
            select(Lot).where(Lot.organization_id == company_id).order_by(Lot.lot_code).limit(1000)
        )
    ]
    source.nonconformance_id.choices = [("", "No linked quality issue")] + [
        (str(r.id), r.reference)
        for r in db.session.scalars(
            select(Nonconformance).where(Nonconformance.organization_id == company_id).limit(1000)
        )
    ]
    task = TaskForm()
    task.assignee_id.choices = [
        (str(member.id), user.display_name)
        for member, user in db.session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == company_id,
                Membership.status == "active",
                Membership.partner_id.is_(None),
                Membership.archived_at.is_(None),
            )
        )
    ]
    runs = db.session.scalars(
        select(TraceRun)
        .where(TraceRun.case_id == row.id)
        .order_by(TraceRun.created_at.desc())
        .limit(50)
    ).all()
    downstream = next((r for r in runs if r.direction == "downstream"), None)
    exposures = (
        db.session.execute(
            select(CaseAffectedShipment, ShipmentLine, Lot)
            .join(ShipmentLine, ShipmentLine.id == CaseAffectedShipment.shipment_line_id)
            .join(Lot, Lot.id == ShipmentLine.lot_id)
            .where(CaseAffectedShipment.trace_run_id == downstream.id)
        ).all()
        if downstream
        else []
    )
    recovery = RecoveryForm()
    recovery.shipment_line_id.choices = [
        (
            str(line.id),
            f"{lot.lot_code} / {line.id} / dispatched {exposure.quantity_dispatched}, resolved {exposure.quantity_resolved}",
        )
        for exposure, line, lot in exposures
    ]
    documents = DocumentForm()
    from app.models.evidence import Document

    documents.document_id.choices = [
        (str(doc.id), doc.original_name)
        for doc in db.session.scalars(
            select(Document)
            .where(
                Document.organization_id == company_id,
                Document.scan_status == "clean",
                Document.state == "active",
                Document.archived_at.is_(None),
            )
            .limit(1000)
        )
    ]
    return render_template(
        "recall/detail.html",
        **ctx,
        row=row,
        source=source,
        task=task,
        comment=CommentForm(),
        trace_form=TraceForm(),
        recovery=recovery,
        documents=documents,
        action=ActionForm(version=str(row.version)),
        sources=db.session.execute(
            select(CaseSource, Lot)
            .join(Lot, Lot.id == CaseSource.lot_id)
            .where(CaseSource.case_id == row.id)
        ).all(),
        tasks=db.session.scalars(
            select(CaseTask).where(CaseTask.case_id == row.id).order_by(CaseTask.created_at)
        ).all(),
        comments=db.session.scalars(
            select(CaseComment)
            .where(CaseComment.case_id == row.id)
            .order_by(CaseComment.created_at)
        ).all(),
        runs=runs,
        exposures=exposures,
        recoveries=db.session.scalars(
            select(RecoveryRecord)
            .where(RecoveryRecord.case_id == row.id)
            .order_by(RecoveryRecord.created_at)
        ).all(),
        links=db.session.scalars(select(CaseDocument).where(CaseDocument.case_id == row.id)).all(),
    )


@bp.post("/<uuid:case_id>/sources")
@login_required
def source(company_id, case_id):
    return safe_action(
        company_id,
        case_id,
        service.source,
        case_id,
        request.form.get("lot_id"),
        request.form.get("note"),
        request.form.get("nonconformance_id") or None,
    )


@bp.post("/<uuid:case_id>/sources/<uuid:source_id>/delete")
@login_required
def remove_source(company_id, case_id, source_id):
    row = scoped(CaseSource, company_id, source_id)
    if row.case_id != case_id:
        return "Not found.", 404
    return safe_action(
        company_id, case_id, service.remove_source, source_id, request.form.get("version") or None
    )


@bp.post("/<uuid:case_id>/submit")
@login_required
def submit(company_id, case_id):
    return safe_action(
        company_id, case_id, service.submit, case_id, request.form.get("version") or None
    )


@bp.post("/<uuid:case_id>/approve")
@login_required
def approve(company_id, case_id):
    return safe_action(
        company_id, case_id, service.approve, case_id, request.form.get("version") or None
    )


@bp.post("/<uuid:case_id>/reject")
@login_required
def reject(company_id, case_id):
    return safe_action(
        company_id,
        case_id,
        service.reject,
        case_id,
        request.form.get("note"),
        request.form.get("version") or None,
    )


@bp.post("/<uuid:case_id>/close")
@login_required
def close(company_id, case_id):
    return safe_action(
        company_id,
        case_id,
        service.close,
        case_id,
        request.form.get("note"),
        request.form.get("acknowledgement_exception", ""),
        request.form.get("version") or None,
    )


@bp.post("/<uuid:case_id>/reopen")
@login_required
def reopen(company_id, case_id):
    return safe_action(
        company_id,
        case_id,
        service.reopen,
        case_id,
        request.form.get("note"),
        request.form.get("version") or None,
    )


@bp.post("/<uuid:case_id>/traces")
@login_required
def compute(company_id, case_id):
    return safe_action(
        company_id, case_id, tracing.compute, case_id, request.form.get("direction", "downstream")
    )


@bp.post("/<uuid:case_id>/tasks")
@login_required
def task(company_id, case_id):
    return safe_action(
        company_id,
        case_id,
        service.task,
        case_id,
        request.form.get("title"),
        request.form.get("description"),
        request.form.get("assignee_id"),
        request.form.get("mandatory") in {"y", "on", "true", "1"},
    )


@bp.post("/<uuid:case_id>/tasks/<uuid:task_id>/complete")
@login_required
def complete_task(company_id, case_id, task_id):
    row = scoped(CaseTask, company_id, task_id)
    if row.case_id != case_id:
        return "Not found.", 404
    return safe_action(
        company_id,
        case_id,
        service.complete_task,
        task_id,
        request.form.get("note"),
        request.form.get("verify") == "yes",
        request.form.get("version") or None,
    )


@bp.post("/<uuid:case_id>/comments")
@login_required
def comment(company_id, case_id):
    return safe_action(company_id, case_id, service.comment, case_id, request.form.get("body"))


@bp.post("/<uuid:case_id>/recovery")
@login_required
def recovery(company_id, case_id):
    return safe_action(
        company_id,
        case_id,
        service.record_recovery,
        case_id,
        request.form.get("shipment_line_id"),
        request.form.get("amount"),
        request.form.get("disposition"),
        request.form.get("evidence_note"),
        request.form.get("evidence_reference"),
    )


@bp.post("/<uuid:case_id>/documents")
@login_required
def document(company_id, case_id):
    return safe_action(
        company_id, case_id, service.attach_document, case_id, request.form.get("document_id")
    )


@bp.get("/traces/<uuid:trace_id>")
@login_required
def trace(company_id, trace_id):
    run, rows = tracing.results(company_id, trace_id)
    page_number = request.args.get("page", 1, type=int)
    page_number = max(1, page_number)
    nodes = rows[:200]
    positions = {
        str(result.lot_id): (min(result.depth, 4) * 210 + 15, index * 60 + 20)
        for index, (result, lot, variant) in enumerate(nodes)
    }
    edges = []
    for result, _lot, _variant in nodes:
        for parent, child in zip(result.evidence_path, result.evidence_path[1:], strict=False):
            if parent["lot"] in positions and child["lot"] in positions:
                link = (positions[parent["lot"]], positions[child["lot"]])
                if link not in edges:
                    edges.append(link)
    return render_template(
        "recall/trace.html",
        **context(company_id),
        run=run,
        rows=rows[(page_number - 1) * 50 : page_number * 50],
        total=len(rows),
        page_number=page_number,
        nodes=nodes,
        positions=positions,
        edges=edges,
        height=max(100, len(nodes) * 60 + 20),
        totals=tracing.summary(company_id, trace_id),
    )


@bp.post("/<uuid:case_id>/cancel")
@login_required
def cancel(company_id, case_id):
    return safe_action(
        company_id,
        case_id,
        service.cancel_draft,
        case_id,
        request.form.get("note"),
        request.form.get("version") or None,
    )


@bp.route("/<uuid:case_id>/tasks/<uuid:task_id>/edit", methods=["GET", "POST"])
@login_required
def task_editor(company_id, case_id, task_id):
    actor(company_id, "case.prepare")
    row = scoped(CaseTask, company_id, task_id)
    if row.case_id != case_id:
        return "Not found.", 404
    form = TaskForm(obj=row)
    form.assignee_id.choices = [
        (str(member.id), user.display_name)
        for member, user in db.session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == company_id,
                Membership.status == "active",
                Membership.partner_id.is_(None),
                Membership.archived_at.is_(None),
            )
        )
    ]
    if form.validate_on_submit():
        try:
            service.task(
                company_id,
                case_id,
                form.title.data,
                form.description.data,
                form.assignee_id.data,
                form.mandatory.data,
                task_id,
                form.version.data or None,
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            return redirect(
                url_for("recall.detail", company_id=company_id, case_id=case_id), code=303
            )
    return render_template(
        "quality/form.html", **context(company_id), form=form, title="Edit open investigation task"
    ), 422 if request.method == "POST" else 200


@bp.post("/<uuid:case_id>/tasks/<uuid:task_id>/delete")
@login_required
def remove_task(company_id, case_id, task_id):
    row = scoped(CaseTask, company_id, task_id)
    if row.case_id != case_id:
        return "Not found.", 404
    return safe_action(
        company_id, case_id, service.remove_task, task_id, request.form.get("version") or None
    )


@bp.route("/<uuid:case_id>/comments/<uuid:comment_id>/amend", methods=["GET", "POST"])
@login_required
def amend_comment(company_id, case_id, comment_id):
    actor(company_id, "case.prepare")
    row = scoped(CaseComment, company_id, comment_id)
    if row.case_id != case_id:
        return "Not found.", 404
    form = CommentForm(obj=row)
    if form.validate_on_submit():
        try:
            service.comment(
                company_id, case_id, form.body.data, comment_id, form.version.data or None
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            return redirect(
                url_for("recall.detail", company_id=company_id, case_id=case_id), code=303
            )
    return render_template(
        "quality/form.html",
        **context(company_id),
        form=form,
        title="Append a correction; original comment is preserved",
    ), 422 if request.method == "POST" else 200


@bp.post("/<uuid:case_id>/documents/<uuid:link_id>/detach")
@login_required
def detach_document(company_id, case_id, link_id):
    return safe_action(
        company_id,
        case_id,
        service.detach_document,
        case_id,
        link_id,
        request.form.get("version") or None,
    )
