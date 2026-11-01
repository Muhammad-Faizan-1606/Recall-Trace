"""Public account forms; one-time codes are POSTed, never placed in URLs."""

import hashlib

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, EqualTo, Length

from app.extensions import limiter
from app.forms import email_syntax, trimmed
from app.models.account_tokens import EmailVerificationToken, PasswordResetToken
from app.services.account_recovery import request_challenge, reset_password, verify_email
from app.services.development_mail import development_mail_configured

bp = Blueprint("account_recovery", __name__, url_prefix="/account")
GENERIC_RESPONSE = "If this address belongs to an eligible account, instructions will be sent."
INVALID_CODE = "This code is invalid or has expired. Request a new email."


class RequestForm(FlaskForm):
    email = StringField(
        "Email", validators=[DataRequired(), email_syntax, Length(max=254)], filters=[trimmed]
    )


class CodeForm(FlaskForm):
    token = PasswordField(
        "One-time code",
        validators=[DataRequired(), Length(max=128)],
        render_kw={"autocomplete": "one-time-code"},
    )


class ResetForm(CodeForm):
    password = PasswordField(
        "New password",
        validators=[DataRequired(), Length(min=15, max=128)],
        render_kw={"autocomplete": "new-password"},
    )
    confirmation = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
        render_kw={"autocomplete": "new-password"},
    )


def email_rate_key():
    # Shared counters identify the submitted account without storing email addresses as keys.
    return hashlib.sha256(request.form.get("email", "").strip().lower().encode()).hexdigest()


def request_view(model, title):
    form = RequestForm()
    if form.validate_on_submit():
        request_challenge(form.email.data, model)
        flash(GENERIC_RESPONSE, "info")
        return redirect(url_for(request.endpoint), code=303)
    return render_template(
        "account_recovery/request.html",
        form=form,
        title=title,
        delivery_configured=development_mail_configured(),
    ), (422 if request.method == "POST" else 200)


@bp.route("/reset/request", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
@limiter.limit("3 per hour", methods=["POST"], key_func=email_rate_key)
def request_reset():
    return request_view(PasswordResetToken, "Recover your password")


@bp.route("/verify/request", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
@limiter.limit("3 per hour", methods=["POST"], key_func=email_rate_key)
def request_verification():
    return request_view(EmailVerificationToken, "Verify your email")


@bp.route("/reset", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def reset():
    form = ResetForm()
    status = 422 if request.method == "POST" else 200
    if form.validate_on_submit():
        try:
            changed = reset_password(form.token.data, form.password.data)
        except ValueError as exc:
            form.password.errors.append(str(exc))
        else:
            if changed:
                flash("Password changed. Sign in with your new password.", "success")
                return redirect(url_for("auth.login"), code=303)
            flash(INVALID_CODE, "danger")
            status = 400
    return render_template(
        "account_recovery/consume.html",
        form=form,
        title="Set a new password",
        submit="Change password",
    ), status


@bp.route("/verify", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def verify():
    form = CodeForm()
    status = 422 if request.method == "POST" else 200
    if form.validate_on_submit():
        if verify_email(form.token.data):
            flash("Email verified. You can sign in to RecallTrace.", "success")
            return redirect(url_for("auth.login"), code=303)
        flash(INVALID_CODE, "danger")
        status = 400
    return render_template(
        "account_recovery/consume.html",
        form=form,
        title="Confirm your email",
        submit="Verify email",
    ), status
