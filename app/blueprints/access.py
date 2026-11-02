import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from wtforms import PasswordField, SelectField, SelectMultipleField, StringField
from wtforms.fields import SelectChoice
from wtforms.validators import DataRequired, Length

from app.extensions import db, limiter
from app.forms import ActionForm, email_syntax, trimmed
from app.models import Membership, Organization, Role
from app.models.invitations import Invitation
from app.models.master import Partner
from app.policies import membership_for, require
from app.services import access

bp = Blueprint("access", __name__)


class RoleForm(ActionForm):
    code = StringField("Code", validators=[DataRequired(), Length(max=50)], filters=[trimmed])
    name = StringField("Name", validators=[DataRequired(), Length(max=80)], filters=[trimmed])
    permissions = SelectMultipleField("Permissions", validators=[DataRequired()])


class MembershipForm(ActionForm):
    role_id = SelectField("Role", validators=[DataRequired()])
    partner_id = SelectField("Partner restriction (blank for internal users)", default="")
    status = SelectField(
        "Status", choices=[SelectChoice("active", "Active"), SelectChoice("inactive", "Inactive")]
    )


class InviteForm(FlaskForm):
    email = StringField(
        "Email", validators=[DataRequired(), email_syntax, Length(max=254)], filters=[trimmed]
    )
    role_id = SelectField("Role", validators=[DataRequired()])
    partner_id = SelectField("Partner restriction (blank for internal users)", default="")


class AcceptForm(FlaskForm):
    token = PasswordField("Invitation code", validators=[DataRequired(), Length(max=128)])
    display_name = StringField(
        "Display name (new accounts)", validators=[Length(max=120)], filters=[trimmed]
    )
    password = PasswordField("Password (new accounts)", validators=[Length(max=128)])


def context(company_id):
    require(company_id, "access.manage")
    return {"company_id": company_id, "company": db.session.get(Organization, company_id)}


def role_choices(company_id):
    actor = membership_for(company_id)
    return [
        SelectChoice(str(r.id), r.name)
        for r in db.session.scalars(
            select(Role)
            .where(Role.organization_id == company_id, Role.archived_at.is_(None))
            .order_by(Role.name)
        )
        if access.grantable(r, actor)
    ]


def partner_choices(company_id):
    return [SelectChoice("", "Internal company user")] + [
        SelectChoice(str(p.id), f"{p.code} — {p.name}")
        for p in db.session.scalars(
            select(Partner)
            .where(
                Partner.organization_id == company_id,
                Partner.status == "active",
                Partner.archived_at.is_(None),
            )
            .order_by(Partner.code)
        )
    ]


@bp.get("/companies/<uuid:company_id>/access")
@login_required
def dashboard(company_id):
    ctx = context(company_id)
    return render_template(
        "access/dashboard.html",
        members=db.session.scalars(
            select(Membership)
            .where(Membership.organization_id == company_id)
            .order_by(Membership.created_at)
        ).all(),
        roles=db.session.scalars(
            select(Role).where(Role.organization_id == company_id).order_by(Role.name)
        ).all(),
        invitations=db.session.scalars(
            select(Invitation)
            .where(Invitation.organization_id == company_id)
            .order_by(Invitation.created_at.desc())
            .limit(100)
        ).all(),
        form=FlaskForm(),
        **ctx,
    )


@bp.route("/companies/<uuid:company_id>/access/roles/new", methods=["GET", "POST"])
@bp.route("/companies/<uuid:company_id>/access/roles/<uuid:role_id>/edit", methods=["GET", "POST"])
@login_required
def role_edit(company_id, role_id=None):
    ctx = context(company_id)
    role = access.scoped(Role, company_id, role_id) if role_id else None
    form = RoleForm(obj=role)
    form.permissions.choices = [
        SelectChoice(c, c)
        for c in sorted(access.permissions_for(membership_for(company_id)) & access.ACTIONS)
    ]
    if request.method == "GET":
        form.version.data = str(role.version if role else 0)
        form.permissions.data = sorted(access.role_permissions(role)) if role else []
    status = 422 if request.method == "POST" else 200
    if form.validate_on_submit():
        try:
            access.save_role(
                company_id,
                form.code.data,
                form.name.data,
                form.permissions.data,
                role_id,
                int(form.version.data),
            )
        except access.AccessConflict as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            status = 409
        else:
            flash("Role saved. Affected users must sign in again.", "success")
            return redirect(url_for("access.dashboard", company_id=company_id), code=303)
    return render_template(
        "form.html", form=form, title="Edit role" if role else "New role", submit="Save role", **ctx
    ), status


@bp.route(
    "/companies/<uuid:company_id>/access/members/<uuid:membership_id>/edit", methods=["GET", "POST"]
)
@login_required
def member_edit(company_id, membership_id):
    ctx = context(company_id)
    member = access.scoped(Membership, company_id, membership_id)
    form = MembershipForm(obj=member)
    form.role_id.choices = role_choices(company_id)
    form.partner_id.choices = partner_choices(company_id)
    if request.method == "GET" or "partner_id" not in request.form:
        form.partner_id.data = str(member.partner_id) if member.partner_id else ""
    if request.method == "GET":
        form.version.data = str(member.version)
    status = 422 if request.method == "POST" else 200
    if form.validate_on_submit():
        try:
            access.change_membership(
                company_id,
                member.id,
                uuid.UUID(form.role_id.data),
                form.status.data,
                int(form.version.data),
                partner_id=uuid.UUID(form.partner_id.data) if form.partner_id.data else None,
            )
        except access.AccessConflict as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            status = 409
        else:
            flash("Membership saved. The member must sign in again.", "success")
            return redirect(url_for("access.dashboard", company_id=company_id), code=303)
    return render_template(
        "form.html",
        form=form,
        title=f"Manage {member.user.display_name}",
        submit="Save membership",
        **ctx,
    ), status


@bp.route("/companies/<uuid:company_id>/access/invitations/new", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per hour", methods=["POST"])
def invite(company_id):
    ctx = context(company_id)
    form = InviteForm()
    form.role_id.choices = role_choices(company_id)
    form.partner_id.choices = partner_choices(company_id)
    status = 422 if request.method == "POST" else 200
    if form.validate_on_submit():
        try:
            access.invite(
                company_id,
                form.email.data,
                uuid.UUID(form.role_id.data),
                partner_id=uuid.UUID(form.partner_id.data) if form.partner_id.data else None,
            )
        except access.AccessConflict as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            status = 409
        else:
            flash(
                "Invitation saved and delivery confirmed by the configured account adapter.",
                "success",
            )
            return redirect(url_for("access.dashboard", company_id=company_id), code=303)
    return render_template(
        "form.html", form=form, title="Invite a company member", submit="Send invitation", **ctx
    ), status


@bp.post("/companies/<uuid:company_id>/access/invitations/<uuid:invitation_id>/revoke")
@login_required
def revoke(company_id, invitation_id):
    context(company_id)
    if not FlaskForm().validate_on_submit():
        abort(400)
    try:
        access.revoke_invitation(company_id, invitation_id)
    except access.AccessConflict as exc:
        db.session.rollback()
        return render_template("error.html", message=str(exc)), 409
    flash("Invitation revoked.", "success")
    return redirect(url_for("access.dashboard", company_id=company_id), code=303)


@bp.route("/invitations/accept", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def accept():
    form = AcceptForm()
    status = 422 if request.method == "POST" else 200
    if form.validate_on_submit():
        try:
            accepted = access.accept_invitation(
                form.token.data, form.display_name.data, form.password.data
            )
        except access.AccessConflict as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            status = 409
        except IntegrityError:
            db.session.rollback()
            flash("The account changed. Sign in to the invited account and try again.", "danger")
            status = 409
        else:
            if accepted:
                flash("Invitation accepted. Sign in to your company.", "success")
                return redirect(url_for("auth.login"), code=303)
            db.session.rollback()
            flash("This invitation is invalid or has expired.", "danger")
            status = 400
    return render_template("access/accept.html", form=form), status


@bp.post("/companies/<uuid:company_id>/access/roles/<uuid:role_id>/delete")
@login_required
def role_delete(company_id, role_id):
    context(company_id)
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        result = access.remove_role(company_id, role_id, int(form.version.data))
    except access.AccessConflict as exc:
        db.session.rollback()
        return render_template("error.html", message=str(exc)), 409
    flash(result, "success")
    return redirect(url_for("access.dashboard", company_id=company_id), code=303)
