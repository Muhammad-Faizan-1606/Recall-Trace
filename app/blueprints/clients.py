"""Clients: add customers, give each a badge colour and logo, and serve the logo privately."""

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_wtf.file import FileField, FileRequired
from sqlalchemy import select
from wtforms import BooleanField, StringField
from wtforms.validators import DataRequired, Length, Regexp

from app.blueprints.factory import context
from app.extensions import db
from app.forms import ActionForm
from app.models.factory import ProductionOrder, Style
from app.services import clients
from app.services.business import DomainError
from app.services.jobroles import permission_codes

bp = Blueprint("clients", __name__, url_prefix="/companies/<uuid:company_id>/factory")


def trimmed(value):
    return value.strip() if isinstance(value, str) else value


class ClientForm(ActionForm):
    code = StringField(
        "Code",
        validators=[DataRequired(), Length(max=40)],
        filters=[trimmed],
        description="A short, unique code, e.g. NPA. It cannot change later.",
    )
    name = StringField(
        "Client name", validators=[DataRequired(), Length(max=160)], filters=[trimmed]
    )
    short_name = StringField(
        "Badge name",
        validators=[DataRequired(), Length(max=12)],
        filters=[trimmed],
        description="Shown on bundles, orders and the factory map (up to 12 letters).",
    )
    colour = StringField(
        "Badge colour",
        validators=[DataRequired(), Regexp(r"^#[0-9a-fA-F]{6}$", message="Pick a colour.")],
    )
    inactive = BooleanField("Paused (no new orders)")


class LogoForm(ActionForm):
    logo = FileField("Logo (PNG, JPEG or WebP, up to 2 MB)", validators=[FileRequired()])


@bp.app_context_processor
def client_helpers():
    return {
        "client_logo": clients.logo_url,
        "style_client": lambda company_id, style: (
            clients.badges(company_id).get(style.buyer_id) if style and style.buyer_id else None
        ),
    }


def can_manage(company_id):
    return bool(set(clients.MANAGERS) & permission_codes(company_id))


def manage_guard(company_id):
    context(company_id, area="dashboard")
    if not can_manage(company_id):
        abort(403)


@bp.get("/clients")
@login_required
def listing(company_id):
    ctx = context(company_id, area="dashboard")
    return render_template(
        "factory/clients.html",
        rows=clients.listing(company_id),
        can_edit=can_manage(company_id),
        **ctx,
    )


def editor(company_id, partner_id=None):
    manage_guard(company_id)
    ctx = context(company_id, area="dashboard")
    partner = brand = None
    if partner_id:
        try:
            partner, brand = clients.client(company_id, partner_id)
        except DomainError:
            abort(404)
    badge = clients.badges(company_id).get(partner.id) if partner else None
    form = ClientForm(
        data={
            "version": str(brand.version if brand else 0),
            "code": partner.code if partner else "",
            "name": partner.name if partner else "",
            "short_name": badge.short if badge else "",
            "colour": badge.colour if badge else clients.PALETTE[0],
            "inactive": partner.status == "inactive" if partner else False,
        }
        if request.method == "GET"
        else None
    )
    if partner:
        form.code.render_kw = {"readonly": True}
    if form.validate_on_submit():
        values = {**form.data, "code": partner.code if partner else form.code.data}
        try:
            saved = clients.save(
                company_id,
                values,
                partner_id=partner.id if partner else None,
                version=int(form.version.data) if partner else None,
            )
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            flash(f"{saved.name} saved.", "success")
            return redirect(url_for(".edit", company_id=company_id, partner_id=saved.id), 303)
    orders = []
    if partner:
        orders = db.session.scalars(
            select(ProductionOrder)
            .join(
                Style,
                (Style.id == ProductionOrder.style_id)
                & (Style.organization_id == ProductionOrder.organization_id),
            )
            .where(ProductionOrder.organization_id == company_id, Style.buyer_id == partner.id)
            .order_by(ProductionOrder.ex_factory_on.desc())
            .limit(12)
        ).all()
    return render_template(
        "factory/client.html",
        form=form,
        partner=partner,
        brand=brand,
        badge=badge,
        orders=orders,
        logo_form=LogoForm(data={"version": str(brand.version if brand else 0)}),
        remove_form=ActionForm(data={"version": str(brand.version if brand else 0)}),
        **ctx,
    )


@bp.route("/clients/new", methods=["GET", "POST"])
@login_required
def new(company_id):
    return editor(company_id)


@bp.route("/clients/<uuid:partner_id>", methods=["GET", "POST"])
@login_required
def edit(company_id, partner_id):
    return editor(company_id, partner_id)


@bp.post("/clients/<uuid:partner_id>/logo")
@login_required
def upload_logo(company_id, partner_id):
    manage_guard(company_id)
    form = LogoForm()
    if not form.validate_on_submit():
        flash("Choose an image file to upload.", "danger")
    else:
        data = form.logo.data.stream.read(clients.UPLOAD_LIMIT + 1)
        try:
            clients.set_logo(company_id, partner_id, data, int(form.version.data))
        except DomainError as exc:
            flash(str(exc), "danger")
        else:
            flash("Logo saved.", "success")
    return redirect(url_for(".edit", company_id=company_id, partner_id=partner_id), 303)


@bp.post("/clients/<uuid:partner_id>/logo/remove")
@login_required
def remove_logo(company_id, partner_id):
    manage_guard(company_id)
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        clients.remove_logo(company_id, partner_id, int(form.version.data))
    except DomainError as exc:
        flash(str(exc), "danger")
    else:
        flash("Logo removed.", "success")
    return redirect(url_for(".edit", company_id=company_id, partner_id=partner_id), 303)


@bp.get("/clients/<uuid:partner_id>/logo.png")
@login_required
def logo(company_id, partner_id):
    """The stored, re-encoded PNG. Same access as the factory screens; never public."""
    context(company_id, area="dashboard")
    found = clients.logo(company_id, partner_id)
    if found is None:
        abort(404)
    png, sha = found
    if request.if_none_match.contains(sha):
        return Response(status=304, headers={"ETag": f'"{sha}"'})
    response = Response(png, mimetype="image/png")
    response.headers["ETag"] = f'"{sha}"'
    response.headers["Cache-Control"] = "private, max-age=86400"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Disposition"] = "inline; filename=logo.png"
    return response
