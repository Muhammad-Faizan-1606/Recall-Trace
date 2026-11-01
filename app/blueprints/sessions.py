from flask import Blueprint, flash, redirect, render_template, session, url_for
from flask_login import login_required, logout_user
from flask_wtf import FlaskForm

from app.services import sessions
from app.services.auth import digest

bp = Blueprint("sessions", __name__, url_prefix="/account/sessions")


@bp.get("")
@login_required
def listing():
    return render_template(
        "sessions.html",
        records=sessions.own_sessions(),
        form=FlaskForm(),
        current_digest=digest(session.get("auth_ref", "")),
    )


@bp.post("/<uuid:session_id>/revoke")
@login_required
def revoke(session_id):
    if not FlaskForm().validate_on_submit():
        return "", 400
    if sessions.revoke(session_id):
        logout_user()
        session.clear()
        flash("This session has been signed out.", "success")
        return redirect(url_for("auth.login"), code=303)
    flash("Session revoked.", "success")
    return redirect(url_for("sessions.listing"), code=303)
