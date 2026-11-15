"""The 3D factory map's sewing floor: live line data and drag-and-drop bundle moves.

Dragging a bundle on the map calls the same `shopfloor.bundle_step` as the bundle forms, so
the server applies the same rules (status, active sewing line, record version, company
scope, factory.record permission, CSRF) and writes the same audit row.
"""

import re
from decimal import Decimal

import pytest
from conftest import login
from sqlalchemy import select
from test_balancing import line  # noqa: F401
from test_factory import grant
from test_shopfloor import floor  # noqa: F401

from app.extensions import db
from app.models.security import AuditEvent
from app.services import factory as service
from app.services import factorymap, shopfloor
from app.services.business import DomainError


@pytest.fixture
def cut(floor):  # noqa: F811
    """A second sewing line on the same site and three cut bundles waiting in the buffer."""
    company_id = floor.company_id
    floor.other = service.save(
        company_id,
        "work-centers",
        {
            "code": "L2",
            "name": "Line 2",
            "department": "sewing",
            "site_id": floor.center.site_id,
            "shift_pattern_id": floor.center.shift_pattern_id,
            "target_efficiency": Decimal(80),
        },
    )
    floor.bundles = shopfloor.cut_bundles(
        company_id,
        {
            "production_order_id": str(floor.order.id),
            "lay_number": "L-1",
            "bundle_size": 30,
            "sizes": "M:90",
        },
    )
    return floor


def map_token(page):
    match = re.search(r'data-csrf="([^"]+)"', page.text)
    assert match, page.text
    return match.group(1)


def test_transfer_moves_issued_work_between_lines(cut):
    company_id = cut.company_id
    first = cut.bundles[0]
    with pytest.raises(DomainError, match="Only bundles on a line can move"):
        shopfloor.bundle_step(company_id, first.id, "transfer", first.version, cut.other.id)
    first = shopfloor.bundle_step(company_id, first.id, "issue", first.version, cut.center.id)
    with pytest.raises(DomainError, match="already on that line"):
        shopfloor.bundle_step(company_id, first.id, "transfer", first.version, cut.center.id)
    with pytest.raises(DomainError):
        shopfloor.bundle_step(company_id, first.id, "transfer", first.version - 1, cut.other.id)
    first = shopfloor.bundle_step(company_id, first.id, "transfer", first.version, cut.other.id)
    assert first.status == "issued" and first.issued_line_id == cut.other.id
    operations = db.session.scalars(
        select(AuditEvent.safe_details).where(
            AuditEvent.action == "factory.bundle_step", AuditEvent.entity_id == first.id
        )
    ).all()
    assert sorted(d["operation"] for d in operations) == ["issue", "transfer"]


def test_floor_data_lists_lines_and_the_cutting_buffer(cut):
    company_id = cut.company_id
    sites = factorymap.sites_with_lines(company_id)
    assert [(site[0], site[3]) for site in sites] == [(cut.center.site_id, 2)]
    shopfloor.bundle_step(
        company_id, cut.bundles[0].id, "issue", cut.bundles[0].version, cut.center.id
    )
    data = factorymap.floor(company_id, cut.center.site_id)
    assert {row["name"] for row in data["lines"]} == {cut.center.name, "Line 2"}
    by_id = {row["id"]: row for row in data["lines"]}
    assert by_id[str(cut.center.id)]["pieces_on_line"] == 30
    assert [b["number"] for b in by_id[str(cut.center.id)]["bundles"]] == ["PO-9-0001"]
    assert by_id[str(cut.other.id)]["bundles"] == []
    assert [b["number"] for b in data["buffer"]] == ["PO-9-0002", "PO-9-0003"]


def test_drag_and_drop_moves_through_the_endpoint(cut, client):
    company_id = cut.company_id
    login(client)
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/map")
    assert page.status_code == 200 and "data-floor-source" in page.text
    token = map_token(page)
    data = client.get(f"{base}/map/floor.json?site={cut.center.site_id}").get_json()
    assert data["can_move"] is True and len(data["buffer"]) == 3
    box = data["buffer"][0]
    url = f"{base}/map/bundles/{box['id']}"
    headers = {"X-CSRFToken": token}

    # No CSRF token: refused before anything changes.
    response = client.post(url, json={"step": "issue", "line_id": str(cut.center.id)})
    assert response.status_code == 400

    moves = [
        ({"step": "issue", "line_id": str(cut.center.id)}, "issued to the line"),
        ({"step": "transfer", "line_id": str(cut.other.id)}, "moved to the line"),
        ({"step": "sewn"}, "marked sewn"),
    ]
    version = box["version"]
    for payload, words in moves:
        response = client.post(url, json={**payload, "version": version}, headers=headers)
        assert response.status_code == 200, response.get_json()
        assert words in response.get_json()["message"]
        version += 1

    # A stale version, an unknown step and a wrong step are refused with a message.
    stale = client.post(url, json={"step": "sewn", "version": 0}, headers=headers)
    assert stale.status_code == 409 and stale.get_json()["error"]
    unknown = client.post(url, json={"step": "delete", "version": version}, headers=headers)
    assert unknown.status_code == 400
    again = client.post(url, json={"step": "sewn", "version": version}, headers=headers)
    assert again.status_code == 409 and "Only bundles on a line" in again.get_json()["error"]

    # Moving onto a line that is not a sewing line is refused.
    second = data["buffer"][1]
    response = client.post(
        f"{base}/map/bundles/{second['id']}",
        json={"step": "issue", "line_id": "not-a-line", "version": second["version"]},
        headers=headers,
    )
    assert response.status_code in (404, 409)


def test_read_only_staff_see_the_floor_but_cannot_move(cut, client):
    company_id = cut.company_id
    grant(company_id, codes=("factory.read", "factory.read_all"), role_code="auditor")
    login(client, "auditor@aurora.test")
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/map")
    assert page.status_code == 200
    data = client.get(f"{base}/map/floor.json?site={cut.center.site_id}").get_json()
    assert data["can_move"] is False and len(data["buffer"]) == 3
    box = data["buffer"][0]
    response = client.post(
        f"{base}/map/bundles/{box['id']}",
        json={"step": "issue", "line_id": str(cut.center.id), "version": box["version"]},
        headers={"X-CSRFToken": map_token(page)},
    )
    assert response.status_code == 403
    assert client.get(f"{base}/map/floor.json?site=nope").status_code == 404
