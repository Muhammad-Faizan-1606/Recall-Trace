"""Regression tests from the November 2026 security review.

See documentation/SECURITY_REVIEW.md.

The review swept every route as an outsider company and sent hostile input to every form;
these tests pin down what it found and fixed, and the boundaries it confirmed.
"""

import re

from conftest import csrf, login
from sqlalchemy import func, select
from test_balancing import line  # noqa: F401
from test_floor_map import cut  # noqa: F401
from test_shopfloor import floor  # noqa: F401

from app.extensions import db
from app.models.master import Partner


def test_nul_characters_are_refused_before_they_reach_the_database(client, records):
    company_id = records["companies"]["aurora"]
    assert client.get("/login?next=%00").status_code == 400
    page = client.get("/login")
    response = client.post(
        "/login",
        data={"email": "owner@aurora.test\x00", "password": "x", "csrf_token": csrf(page)},
    )
    assert response.status_code == 400
    login(client)
    form = client.get(f"/companies/{company_id}/master/partners/new")
    before = db.session.scalar(select(func.count(Partner.id)))
    response = client.post(
        f"/companies/{company_id}/master/partners/new",
        data={"csrf_token": csrf(form), "version": "0", "code": "NUL\x00", "name": "x"},
    )
    assert response.status_code == 400
    assert db.session.scalar(select(func.count(Partner.id))) == before


def test_security_headers(client):
    headers = client.get("/login").headers
    csp = headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp and "'unsafe-inline'" not in csp
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "camera=()" in headers["Permissions-Policy"]
    assert headers["Cache-Control"] == "no-store"


def test_factory_json_endpoints_refuse_another_company(client, cut, records):  # noqa: F811
    """A member of one company gets 404 from another company's factory endpoints, even
    with valid record IDs and a valid CSRF token, and nothing changes."""
    other = records["companies"]["beacon"]
    bundle = cut.bundles[0]
    login(client)
    page = client.get(f"/companies/{cut.company_id}/factory/map")
    token = re.search(r'data-csrf="([^"]+)"', page.text).group(1)
    base = f"/companies/{other}/factory"
    response = client.post(
        f"{base}/map/bundles/{bundle.id}",
        json={"step": "issue", "line_id": str(cut.center.id), "version": bundle.version},
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 404
    assert client.get(f"{base}/map/floor.json?site={cut.center.site_id}").status_code == 404
    assert client.get(f"{base}/map.json").status_code == 404
    db.session.expire_all()
    assert db.session.get(type(bundle), bundle.id).status == "cut"
