"""Clients (badge, colour and logo), the drag-and-drop planning board, and the picture
panels on the factory sections."""

import io
import re
from datetime import date

import pytest
from conftest import csrf, login
from PIL import Image
from sqlalchemy import select
from test_balancing import line  # noqa: F401
from test_factory import grant
from test_planning import factory, order_values  # noqa: F401
from test_shopfloor import floor, mill  # noqa: F401

from app.extensions import db
from app.models.factory import ClientBrand, ProductionOrder, Style
from app.models.master import PartnerRoleAssignment
from app.services import clients, planning, shopfloor, visuals
from app.services.business import DomainError


def image_bytes(fmt="PNG", size=(600, 300), colour=(31, 78, 140), exif=False):
    image = Image.new("RGB", size, colour)
    buffer = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010E] = "secret description"  # ImageDescription
        image.save(buffer, format=fmt, exif=data)
    else:
        image.save(buffer, format=fmt)
    return buffer.getvalue()


def new_client(company_id, code="NPA", name="Northpeak (test)", colour="#1F4E8C"):
    return clients.save(
        company_id, {"code": code, "name": name, "short_name": code.title(), "colour": colour}
    )


# ---------- Service ----------


def test_adding_a_client_creates_a_customer_partner_and_badge(factory):  # noqa: F811
    company_id = factory.company_id
    partner = new_client(company_id)
    assert partner.code == "NPA"
    roles = db.session.scalars(
        select(PartnerRoleAssignment.role_code).where(
            PartnerRoleAssignment.partner_id == partner.id
        )
    ).all()
    assert roles == ["customer"]
    badge = clients.badges(company_id)[partner.id]
    assert (badge.short, badge.colour, badge.ink, badge.logo) == ("Npa", "#1f4e8c", "#ffffff", None)
    assert clients.ink_for("#f4f4f2") == "#111111"
    with pytest.raises(DomainError, match="already uses that code"):
        new_client(company_id, name="Copy")
    with pytest.raises(DomainError, match="colour"):
        new_client(company_id, code="X1", colour="red")
    brand = db.session.scalar(select(ClientBrand).where(ClientBrand.partner_id == partner.id))
    with pytest.raises(DomainError, match="reload"):
        clients.save(
            company_id,
            {"name": "New name", "short_name": "NP", "colour": "#000000"},
            partner_id=partner.id,
            version=brand.version + 5,
        )
    clients.save(
        company_id,
        {"name": "New name", "short_name": "NP", "colour": "#000000", "inactive": True},
        partner_id=partner.id,
        version=brand.version,
    )
    assert partner.name == "New name" and partner.status == "inactive"
    assert clients.badges(company_id)[partner.id].short == "NP"


def test_logos_are_re_encoded_small_pngs(factory):  # noqa: F811
    company_id = factory.company_id
    partner = new_client(company_id)
    version = db.session.scalar(
        select(ClientBrand.version).where(ClientBrand.partner_id == partner.id)
    )
    brand = clients.set_logo(
        company_id, partner.id, image_bytes("JPEG", (1200, 600), exif=True), version
    )
    stored = Image.open(io.BytesIO(brand.logo_png))
    assert stored.format == "PNG" and max(stored.size) == 256
    assert b"secret description" not in brand.logo_png and not stored.getexif()
    png, sha = clients.logo(company_id, partner.id)
    assert png == brand.logo_png and len(sha) == 64
    for data, message in (
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "readable"),
        (image_bytes("GIF"), "PNG, JPEG or WebP"),
        (b"\x89PNG" + b"0" * (clients.UPLOAD_LIMIT + 1), "2 MB"),
        (b"", "Choose an image"),
    ):
        with pytest.raises(DomainError, match=message):
            clients.reencode(data)
    # A tiny file that claims to be enormous is refused before it is decoded.
    bomb = image_bytes("PNG", (5000, 5000))
    with pytest.raises(DomainError, match="too large"):
        clients.reencode(bomb)
    brand = clients.remove_logo(company_id, partner.id, brand.version)
    assert brand.logo_png is None and clients.logo(company_id, partner.id) is None


# ---------- Screens and permissions ----------


def test_client_screens_upload_and_private_logo(factory, client):  # noqa: F811
    company_id = factory.company_id
    login(client)
    base = f"/companies/{company_id}/factory"
    form = client.get(f"{base}/clients/new")
    assert form.status_code == 200
    response = client.post(
        f"{base}/clients/new",
        data={
            "csrf_token": csrf(form),
            "version": "0",
            "code": "hpa",
            "name": "Harbour (test)",
            "short_name": "Harbour",
            "colour": "#0F766E",
        },
    )
    assert response.status_code == 303
    page = client.get(response.headers["Location"])
    assert page.status_code == 200 and "Harbour (test)" in page.text
    partner_id = response.headers["Location"].rsplit("/", 1)[-1]
    token = csrf(page)
    upload = client.post(
        f"{base}/clients/{partner_id}/logo",
        data={"csrf_token": token, "version": "1", "logo": (io.BytesIO(image_bytes()), "l.png")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 303
    listing = client.get(f"{base}/clients")
    assert "Harbour (test)" in listing.text
    src = re.search(r'src="([^"]+/logo\.png\?v=[0-9a-f]+)"', listing.text).group(1)
    logo = client.get(src)
    assert logo.status_code == 200 and logo.mimetype == "image/png"
    assert logo.headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in logo.headers["Content-Security-Policy"]
    again = client.get(src, headers={"If-None-Match": logo.headers["ETag"]})
    assert again.status_code == 304
    # Without the CSRF token nothing is uploaded.
    refused = client.post(
        f"{base}/clients/{partner_id}/logo",
        data={"version": "2", "logo": (io.BytesIO(image_bytes()), "l.png")},
        content_type="multipart/form-data",
    )
    assert refused.status_code == 400
    client.post("/logout", data={"csrf_token": token})
    assert client.get(src).status_code in (302, 303)


def test_read_only_staff_see_clients_but_cannot_change_them(factory, client):  # noqa: F811
    company_id = factory.company_id
    partner = new_client(company_id)
    grant(company_id, codes=("factory.read",), role_code="auditor")
    login(client, "auditor@aurora.test")
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/clients")
    assert page.status_code == 200 and "Northpeak (test)" in page.text
    assert "Add a client" not in page.text
    assert client.get(f"{base}/clients/new").status_code == 403
    assert client.get(f"{base}/clients/{partner.id}").status_code == 403
    response = client.post(
        f"{base}/clients/{partner.id}/logo",
        data={
            "csrf_token": csrf(page),
            "version": "1",
            "logo": (io.BytesIO(image_bytes()), "l.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 403


# ---------- Planning board: preview, then apply ----------


def test_board_lane_move_previews_then_replans(factory, client):  # noqa: F811
    company_id = factory.company_id
    partner = new_client(company_id)
    factory.style.buyer_id = partner.id
    db.session.commit()
    first = planning.save_order(
        company_id, order_values(factory, "PO-1", days=30), today=date.today()
    )
    second = planning.save_order(
        company_id, order_values(factory, "PO-2", days=31, priority=4), today=date.today()
    )
    login(client)
    base = f"/companies/{company_id}/factory"
    board = client.get(f"{base}/planning")
    assert board.status_code == 200
    assert (
        'data-lane="4"' in board.text and "Npa" in board.text and "Release to floor" in board.text
    )
    token = re.search(r'data-csrf="([^"]+)"', board.text).group(1)
    db.session.expire_all()
    second = db.session.get(ProductionOrder, second.id)
    preview = client.get(f"{base}/planning/orders/{second.id}/preview.json?priority=1&lines=2")
    body = preview.get_json()
    assert preview.status_code == 200 and body["priority"] == 1 and body["finish"]
    # Previewing saves nothing.
    db.session.expire_all()
    assert db.session.get(ProductionOrder, second.id).priority == 4
    url = f"{base}/planning/orders/{second.id}/change"
    payload = {"priority": 1, "lines": 2, "version": body["version"]}
    assert client.post(url, json=payload).status_code == 400  # no CSRF token
    response = client.post(url, json=payload, headers={"X-CSRFToken": token})
    assert response.status_code == 200 and "re-planned" in response.get_json()["message"]
    db.session.expire_all()
    assert db.session.get(ProductionOrder, second.id).priority == 1
    stale = client.post(url, json=payload, headers={"X-CSRFToken": token})
    assert stale.status_code == 409
    # Released orders keep their plan.
    first = db.session.get(ProductionOrder, first.id)
    planning.transition(company_id, first.id, "release", first.version)
    refused = client.get(f"{base}/planning/orders/{first.id}/preview.json?priority=2")
    assert refused.status_code == 409


def test_read_only_staff_cannot_move_orders_on_the_board(factory, client):  # noqa: F811
    company_id = factory.company_id
    order = planning.save_order(company_id, order_values(factory, days=30), today=date.today())
    grant(company_id, codes=("factory.read", "factory.read_all"), role_code="auditor")
    login(client, "auditor@aurora.test")
    base = f"/companies/{company_id}/factory"
    board = client.get(f"{base}/planning")
    assert board.status_code == 200 and "can-plan" not in board.text
    assert client.get(f"{base}/planning/orders/{order.id}/preview.json").status_code == 403
    token = re.search(r'data-csrf="([^"]+)"', board.text).group(1)
    response = client.post(
        f"{base}/planning/orders/{order.id}/change",
        json={"priority": 1, "lines": 1, "version": order.version},
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 403


# ---------- Picture panels on the factory sections ----------


def test_section_panels_show_recorded_data(mill, client):  # noqa: F811
    company_id = mill.company_id
    partner = new_client(company_id)
    style = db.session.get(Style, mill.order.style_id)
    style.buyer_id = partner.id
    db.session.commit()
    shopfloor.cut_bundles(
        company_id,
        {
            "production_order_id": str(mill.order.id),
            "lay_number": "L-1",
            "bundle_size": 30,
            "sizes": "M:60",
        },
    )
    bins = {b.key: b for b in visuals.bundle_bins(company_id)}
    assert (bins["cut"].bundles, bins["cut"].pieces) == (2, 60)
    assert bins["cut"].boxes[0][0].partner_id == partner.id
    rooms = visuals.machine_rooms(company_id, with_maintenance=True)
    assert any(light.machine.asset_tag == "KN-1" for room in rooms for light in room.lights)
    assert [v.machine.asset_tag for v in visuals.dye_vessels(company_id)] == ["JET-1"]
    assert visuals.shade("Heather Grey") == "#b5b8bc" and visuals.shade("Zz").startswith("#")
    login(client)
    base = f"/companies/{company_id}/factory"
    for path, marker in (
        ("/orders", "Where every open order is today"),
        ("", "How full each department is"),
        ("/machines", "Every machine, live"),
        ("/maintenance", "Machines and their repairs"),
        ("/lines", "Every line"),
        ("/bundles", "Bundles moving through the floor"),
        ("/dye-batches", "Dye house"),
        ("/floor", "data-floor-source"),
    ):
        page = client.get(base + path)
        assert page.status_code == 200 and marker in page.text, path
    orders = client.get(f"{base}/orders")
    assert "client-chip" in orders.text and "Npa" in orders.text
    data = client.get(f"{base}/map/floor.json?site={mill.center.site_id}").get_json()
    assert data["buffer"][0]["client"]["short"] == "Npa"
