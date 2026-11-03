import hashlib

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_wtf import FlaskForm

from app.extensions import limiter
from app.forms import LoginForm
from app.services.auth import authenticate, signout

bp = Blueprint("auth", __name__)


def account_rate_key():
    """IP rotation must not reset the guessing budget for a single account."""
    email = request.form.get("email", "").strip().lower()
    return hashlib.sha256(email.encode()).hexdigest()


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"], key_func=account_rate_key)
def login():
    form = LoginForm()
    if form.validate_on_submit():
        if authenticate(form.email.data, form.password.data):
            # Always redirect locally; never trust the submitted next URL.
            return redirect(url_for("catalog.companies"), code=303)
        flash("Invalid email or password.", "danger")
    return render_template("form.html", form=form, title="Sign in", submit="Sign in"), (
        422 if request.method == "POST" else 200
    )


@bp.post("/logout")
@login_required
def logout():
    if not FlaskForm().validate_on_submit():
        return "", 400
    signout()
    return redirect(url_for("auth.login"), code=303)
