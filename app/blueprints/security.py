"""Account security screens and scoped read-only audit history."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_limiter.util import get_remote_address
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import PasswordField
from wtforms.validators import DataRequired, Length

from app.extensions import db, limiter
from app.models import Organization
from app.models.security import AuditEvent
from app.policies import require
from app.services import mfa

bp = Blueprint("security", __name__)


def factor_attempt_key():
    # Use account identity across password-authenticated sessions and IPs.
    return current_user.get_id() if current_user.is_authenticated else get_remote_address()


factor_attempt_limit = limiter.shared_limit(
    "10 per minute", scope="mfa-code-attempts", key_func=factor_attempt_key, methods=["POST"]
)


class PasswordConfirmation(FlaskForm):
    password = PasswordField("Current password", validators=[DataRequired(), Length(max=128)])


class Challenge(FlaskForm):
    code = PasswordField(
        "Authenticator or recovery code", validators=[DataRequired(), Length(max=64)]
    )


class DisableFactor(PasswordConfirmation):
    code = PasswordField(
        "Authenticator or recovery code", validators=[DataRequired(), Length(max=64)]
    )


@bp.before_app_request
def enforce_enrolled_factor():
    if request.endpoint in {"live", "ready"}:
        return None
    allowed = {
        "security.index",
        "security.enroll",
        "security.confirm",
        "security.challenge",
        "security.disable",
        "auth.logout",
        "auth.login",
        "static",
    }
    if current_user.is_authenticated and request.endpoint not in allowed:
        if not mfa.login_verified():
            return redirect(url_for("security.challenge"), code=303)
    return None


@bp.get("/security")
@login_required
def index():
    return render_template(
        "security/index.html",
        factor=mfa.factor_for_user(current_user.id),
        configured=bool(mfa.current_app.config.get("MFA_ENCRYPTION_KEY")),
        form=FlaskForm(),
    )


@bp.route("/security/enroll", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per minute", methods=["POST"])
def enroll():
    form = PasswordConfirmation()
    if form.validate_on_submit():
        try:
            secret = mfa.begin_enrollment(form.password.data)
        except mfa.MfaError as exc:
            flash(str(exc), "danger")
        else:
            return render_template(
                "security/enrollment.html",
                secret=secret,
                uri=mfa.provisioning_uri(secret),
                form=Challenge(),
            )
    return render_template(
        "form.html", title="Enroll an authenticator", form=form, submit="Begin enrollment"
    ), (422 if request.method == "POST" else 200)


@bp.post("/security/confirm")
@login_required
@limiter.limit("10 per minute", methods=["POST"])
@factor_attempt_limit
def confirm():
    form = Challenge()
    if not form.validate_on_submit():
        abort(400)
    try:
        codes = mfa.confirm_enrollment(form.code.data)
    except mfa.MfaError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("security.challenge"), code=303)
    return render_template("security/recovery.html", codes=codes)


@bp.route("/security/challenge", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute", methods=["POST"])
@factor_attempt_limit
def challenge():
    form = Challenge()
    if form.validate_on_submit():
        try:
            mfa.verify(form.code.data)
        except mfa.MfaError as exc:
            flash(str(exc), "danger")
        else:
            flash("Authenticator verified for this session.", "success")
            return redirect(url_for("catalog.companies"), code=303)
    return render_template(
        "form.html", title="Verify your authenticator", form=form, submit="Verify"
    ), (422 if request.method == "POST" else 200)


@bp.route("/security/disable", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per minute", methods=["POST"])
@factor_attempt_limit
def disable():
    form = DisableFactor()
    if form.validate_on_submit():
        try:
            mfa.disable(form.password.data, form.code.data)
        except mfa.MfaError as exc:
            flash(str(exc), "danger")
        else:
            flash("Authenticator removed and all sessions revoked. Sign in again.", "success")
            return redirect(url_for("auth.login"), code=303)
    return render_template(
        "form.html", title="Remove authenticator", form=form, submit="Remove and sign out"
    ), (422 if request.method == "POST" else 200)


@bp.get("/companies/<uuid:company_id>/audit")
@login_required
def audit(company_id):
    require(company_id, "audit.read")
    page = db.paginate(
        select(AuditEvent)
        .where(AuditEvent.organization_id == company_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id),
        per_page=50,
        max_per_page=50,
        error_out=False,
    )
    return render_template(
        "security/audit.html",
        page=page,
        company_id=company_id,
        company=db.session.get(Organization, company_id),
    )
