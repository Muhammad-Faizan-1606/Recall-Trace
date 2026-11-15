"""Clients: the customer partners whose work the factory makes, and how screens show them.

A client is an ordinary Core partner with the customer role. This module adds its "brand":
a short badge name, a colour and an optional logo, so the planning board, orders, bundles
and the factory map can show at a glance whose work is whose.

Logos are re-encoded here: the uploaded file is opened with Pillow, checked (format, pixel
count), shrunk to at most 256 × 256 and saved as a fresh PNG. Only that PNG is stored and
served, never the uploaded bytes, so metadata and anything hidden in the original are gone.
"""

import hashlib
import io
import uuid
from dataclasses import dataclass

from flask import url_for
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models.factory import ClientBrand, ProductionOrder, Style
from app.models.master import Partner, PartnerRoleAssignment
from app.services.audit import record as audit
from app.services.business import DomainError, scoped
from app.services.jobroles import require_any

MANAGERS = ("factory.manage", "factory.plan")
LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}
UPLOAD_LIMIT = 2 * 1024 * 1024  # bytes accepted from the browser
STORED_LIMIT = 256 * 1024  # bytes of the re-encoded PNG (also a database check)
MAX_PIXELS = 16_000_000  # refuse decompression bombs before decoding
LOGO_SIDE = 256
# Default colours for clients without one: distinct, and readable with white text.
PALETTE = ("#1f6feb", "#c2410c", "#0f766e", "#7c3aed", "#be123c", "#4d7c0f", "#a16207", "#0e7490")
OPEN_ORDERS = ("planned", "released")


@dataclass(frozen=True)
class Badge:
    partner_id: uuid.UUID
    code: str
    name: str
    short: str
    colour: str
    ink: str  # text colour that reads on `colour`
    logo: str | None  # cache key (sha256) when a logo exists

    def as_json(self, company_id):
        return {
            "client": self.name,
            "short": self.short,
            "colour": self.colour,
            "ink": self.ink,
            "logo": logo_url(company_id, self),
        }


def logo_url(company_id, badge):
    """The private logo address; the hash in `v` changes whenever the logo does."""
    if badge is None or not badge.logo:
        return None
    return url_for(
        "clients.logo", company_id=company_id, partner_id=badge.partner_id, v=badge.logo[:12]
    )


def default_colour(code):
    digest = hashlib.sha256(code.encode()).digest()
    return PALETTE[digest[0] % len(PALETTE)]


def ink_for(colour):
    """Black or white text, whichever contrasts better with the colour (WCAG luminance)."""
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#111111" if (luminance + 0.05) / 0.05 > 1.05 / (luminance + 0.05) else "#ffffff"


def _clean_colour(value):
    colour = (value or "").strip().lower()
    if len(colour) != 7 or colour[0] != "#" or any(c not in "0123456789abcdef" for c in colour[1:]):
        raise DomainError("Choose a colour like #1f6feb.")
    return colour


def _customer_ids(company_id):
    return select(PartnerRoleAssignment.partner_id).where(
        PartnerRoleAssignment.organization_id == company_id,
        PartnerRoleAssignment.role_code == "customer",
    )


def badges(company_id):
    """Every client's badge, by partner id (also clients without a saved brand)."""
    rows = db.session.execute(
        select(Partner, ClientBrand.short_name, ClientBrand.colour, ClientBrand.logo_sha256)
        .outerjoin(
            ClientBrand,
            (ClientBrand.partner_id == Partner.id)
            & (ClientBrand.organization_id == Partner.organization_id),
        )
        .where(Partner.organization_id == company_id, Partner.id.in_(_customer_ids(company_id)))
    ).all()
    result = {}
    for partner, short, colour, sha in rows:
        colour = colour or default_colour(partner.code)
        result[partner.id] = Badge(
            partner.id, partner.code, partner.name, short or partner.code[:6], colour,
            ink_for(colour), sha,
        )  # fmt: skip
    return result


def style_clients(company_id):
    """Style id → client partner id, for screens that start from orders or bundles."""
    return dict(
        db.session.execute(
            select(Style.id, Style.buyer_id).where(
                Style.organization_id == company_id, Style.buyer_id.is_not(None)
            )
        ).all()
    )


def order_badges(company_id, orders):
    """Order id → Badge (or None) for the given production orders."""
    known = badges(company_id)
    by_style = style_clients(company_id)
    return {o.id: known.get(by_style.get(o.style_id)) for o in orders}


@dataclass
class ClientRow:
    partner: Partner
    badge: Badge
    brand: ClientBrand | None
    styles: int
    open_orders: int
    open_pieces: int


def listing(company_id):
    known = badges(company_id)
    partners = db.session.scalars(
        select(Partner)
        .where(Partner.organization_id == company_id, Partner.id.in_(known))
        .order_by(Partner.archived_at.is_not(None), Partner.name)
    ).all()
    brands = {
        b.partner_id: b
        for b in db.session.scalars(
            select(ClientBrand).where(ClientBrand.organization_id == company_id)
        )
    }
    styles = dict(
        db.session.execute(
            select(Style.buyer_id, func.count(Style.id))
            .where(Style.organization_id == company_id, Style.archived_at.is_(None))
            .group_by(Style.buyer_id)
        ).all()
    )
    orders = {
        buyer: (count, pieces)
        for buyer, count, pieces in db.session.execute(
            select(
                Style.buyer_id, func.count(ProductionOrder.id), func.sum(ProductionOrder.quantity)
            )
            .join(
                Style,
                (Style.id == ProductionOrder.style_id)
                & (Style.organization_id == ProductionOrder.organization_id),
            )
            .where(
                ProductionOrder.organization_id == company_id,
                ProductionOrder.status.in_(OPEN_ORDERS),
            )
            .group_by(Style.buyer_id)
        )
    }
    return [
        ClientRow(
            p,
            known[p.id],
            brands.get(p.id),
            styles.get(p.id, 0),
            orders.get(p.id, (0, 0))[0],
            int(orders.get(p.id, (0, 0))[1] or 0),
        )  # fmt: skip
        for p in partners
    ]


def client(company_id, partner_id):
    partner = scoped(Partner, company_id, partner_id)
    if partner.id not in badges(company_id):
        raise DomainError("That partner is not a client (customer).")
    brand = db.session.scalar(
        select(ClientBrand).where(
            ClientBrand.organization_id == company_id, ClientBrand.partner_id == partner.id
        )
    )
    return partner, brand


def _brand(company_id, partner, version):
    """The client's brand row, locked, after checking the screen's version (0 = none yet)."""
    brand = db.session.scalar(
        select(ClientBrand)
        .where(ClientBrand.organization_id == company_id, ClientBrand.partner_id == partner.id)
        .with_for_update()
    )
    if version is not None and version != (brand.version if brand else 0):
        raise DomainError("Someone changed this client; reload before editing.")
    if brand is None:
        brand = ClientBrand(
            organization_id=company_id,
            partner_id=partner.id,
            short_name=partner.code[:6],
            colour=default_colour(partner.code),
        )
        db.session.add(brand)
    return brand


def _commit(action):
    try:
        result = action()
        db.session.commit()
        return result
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        if "uq_partners_organization_id_code" in str(getattr(exc, "orig", "")):
            raise DomainError("Another partner already uses that code.") from None
        raise DomainError("Something changed at the same time; reload and try again.") from None
    except Exception:
        db.session.rollback()
        raise


def save(company_id, values, partner_id=None, version=None):
    """Add a client (a new customer partner and its brand) or edit one's name and badge."""
    require_any(company_id, *MANAGERS)
    name = (values.get("name") or "").strip()
    short = (values.get("short_name") or "").strip()
    colour = _clean_colour(values.get("colour"))
    if not name or len(name) > 160:
        raise DomainError("Give the client's name (up to 160 characters).")
    if not short or len(short) > 12:
        raise DomainError("Give a badge name of up to 12 characters.")

    def action():
        if partner_id is None:
            code = (values.get("code") or "").strip().upper()
            if not code or len(code) > 40:
                raise DomainError("Give the client a short code (up to 40 characters).")
            partner = Partner(organization_id=company_id, code=code, name=name)
            db.session.add(partner)
            db.session.flush()
            db.session.add(
                PartnerRoleAssignment(
                    organization_id=company_id, partner_id=partner.id, role_code="customer"
                )
            )
            brand = _brand(company_id, partner, None)
        else:
            partner, _ = client(company_id, partner_id)
            brand = _brand(company_id, partner, version)
            partner.name = name
            partner.status = "inactive" if values.get("inactive") else "active"
        brand.short_name, brand.colour = short, colour
        db.session.flush()
        audit(
            company_id,
            "factory.client_updated" if partner_id else "factory.client_created",
            "client_brands",
            brand.id,
            {"target_id": str(partner.id), "status": partner.status},
        )
        return partner

    return _commit(action)


def reencode(data):
    """The uploaded image as a fresh PNG of at most 256 × 256, or a DomainError."""
    if not data:
        raise DomainError("Choose an image file.")
    if len(data) > UPLOAD_LIMIT:
        raise DomainError("The logo must be 2 MB or smaller.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in LOGO_FORMATS:
                raise DomainError("Upload a PNG, JPEG or WebP image.")
            if probe.width * probe.height > MAX_PIXELS:
                raise DomainError("The image is too large; use one under 4000 × 4000.")
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            image = image.convert("RGBA")
            image.thumbnail((LOGO_SIDE, LOGO_SIDE), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
    except DomainError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise DomainError("That file is not a readable PNG, JPEG or WebP image.") from None
    png = output.getvalue()
    if len(png) > STORED_LIMIT:
        raise DomainError("The logo is too detailed to store; try a simpler image.")
    return png


def set_logo(company_id, partner_id, data, version):
    require_any(company_id, *MANAGERS)
    png = reencode(data)

    def action():
        partner, _ = client(company_id, partner_id)
        brand = _brand(company_id, partner, version)
        brand.logo_png = png
        brand.logo_sha256 = hashlib.sha256(png).hexdigest()
        db.session.flush()
        audit(
            company_id,
            "factory.client_logo",
            "client_brands",
            brand.id,
            {"target_id": str(partner.id), "result": brand.logo_sha256, "count": len(png)},
        )
        return brand

    return _commit(action)


def remove_logo(company_id, partner_id, version):
    require_any(company_id, *MANAGERS)

    def action():
        partner, brand = client(company_id, partner_id)
        if brand is None or brand.logo_sha256 is None:
            raise DomainError("This client has no logo.")
        brand = _brand(company_id, partner, version)
        brand.logo_png, brand.logo_sha256 = None, None
        db.session.flush()
        audit(
            company_id,
            "factory.client_logo_removed",
            "client_brands",
            brand.id,
            {"target_id": str(partner.id)},
        )
        return brand

    return _commit(action)


def logo(company_id, partner_id):
    """(png bytes, sha256) of a client's logo, or None."""
    row = db.session.execute(
        select(ClientBrand.logo_png, ClientBrand.logo_sha256).where(
            ClientBrand.organization_id == company_id,
            ClientBrand.partner_id == partner_id,
            ClientBrand.logo_sha256.is_not(None),
        )
    ).first()
    return (row[0], row[1]) if row else None
