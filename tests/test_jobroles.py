"""Job roles: area access on every screen, simple-mode home, role preview, team screen,
and the live factory map and visual line view."""

import pytest
from conftest import csrf, login
from sqlalchemy import delete, select
from test_balancing import line  # noqa: F401
from test_factory import as_user
from test_shopfloor import TODAY, floor, hour_values  # noqa: F401

from app.extensions import db
from app.models import Membership, MembershipRole, Role, User
from app.services import balancing, jobroles


@pytest.fixture
def roles(app, records, owner):
    """The aurora owner holds every permission and installs the job roles."""
    result = app.test_cli_runner().invoke(args=["init-business", "--company", "aurora"])
    assert result.exit_code == 0, result.output
    company_id = records["companies"]["aurora"]
    context = as_user(app, owner)
    created, skipped, _ = jobroles.install(company_id)
    assert created == [name for _, name, *_ in jobroles.JOB_ROLES] and skipped == []
    assert jobroles.install(company_id)[0] == []  # idempotent
    context.pop()
    return company_id


def give(company_id, email, role_code):
    """Make `role_code` the person's only role (test set-up)."""
    member = db.session.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == company_id, User.email == email)
    )
    role = db.session.scalar(
        select(Role).where(Role.organization_id == company_id, Role.code == role_code)
    )
    db.session.execute(delete(MembershipRole).where(MembershipRole.membership_id == member.id))
    db.session.add(
        MembershipRole(organization_id=company_id, membership_id=member.id, role_id=role.id)
    )
    db.session.commit()
    return member


AREA_PAGES = {
    "dashboard": "/factory/dashboard",
    "map": "/factory/map",
    "planning": "/factory/planning",
    "floor": "/factory/floor",
    "maintenance": "/factory/maintenance",
    "setup": "/factory/setup",
}


@pytest.mark.parametrize(
    "role_code, allowed_pages",
    [
        ("factory-viewer", {"dashboard", "map"}),
        ("factory-planner", {"dashboard", "map", "planning", "floor"}),
        ("factory-supervisor", {"dashboard", "map", "floor"}),
        ("factory-maintenance", {"dashboard", "map", "maintenance"}),
        ("factory-quality", {"dashboard", "map", "floor"}),
    ],
)
def test_each_job_opens_only_its_areas(roles, client, role_code, allowed_pages):
    give(roles, "auditor@aurora.test", role_code)
    login(client, "auditor@aurora.test")
    base = f"/companies/{roles}"
    for name, path in AREA_PAGES.items():
        expected = 200 if name in allowed_pages else 403
        assert client.get(base + path).status_code == expected, (role_code, name)


def test_menu_and_home_follow_the_job(roles, client):
    give(roles, "auditor@aurora.test", "factory-supervisor")
    login(client, "auditor@aurora.test")
    base = f"/companies/{roles}"
    # Non-admins land on the simple home instead of the recall overview.
    landing = client.get(f"{base}/overview")
    assert landing.status_code == 303 and landing.headers["Location"].endswith("/home")
    home = client.get(f"{base}/home")
    assert "Record hourly output" in home.text and "Scan a bundle" in home.text
    assert "Planning board" not in home.text and "Report a breakdown" not in home.text
    assert "Team and access" not in home.text and "See what each job sees" not in home.text


def test_actions_are_refused_outside_the_job(roles, floor, client):  # noqa: F811
    company_id = floor.company_id
    give(company_id, "auditor@aurora.test", "factory-planner")
    login(client, "auditor@aurora.test")
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/floor/{floor.center.id}")
    assert page.status_code == 200 and "Record an hour" not in page.text
    response = client.post(
        f"{base}/floor/{floor.center.id}/output",
        data={"csrf_token": csrf(page), "version": "0", **hour_values(floor.order)},
    )
    assert response.status_code == 403
    response = client.post(
        f"{base}/maintenance/breakdowns",
        data={"csrf_token": csrf(page), "version": "0", "asset_tag": "OL-1", "description": "x"},
    )
    assert response.status_code == 403


def test_quality_inspectors_record_checks_but_not_output(roles, floor, client):  # noqa: F811
    company_id = floor.company_id
    give(company_id, "auditor@aurora.test", "factory-quality")
    login(client, "auditor@aurora.test")
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/floor/{floor.center.id}?day={TODAY.isoformat()}")
    assert page.status_code == 200
    check = {
        "day": TODAY.isoformat(),
        "hour": 1,
        "stage": "endline",
        "production_order_id": str(floor.order.id),
        "pieces_checked": 20,
        "defective_pieces": 0,
    }
    response = client.post(
        f"{base}/floor/{floor.center.id}/quality",
        data={"csrf_token": csrf(page), "version": "0", **check},
    )
    assert response.status_code == 303
    response = client.post(
        f"{base}/floor/{floor.center.id}/output",
        data={"csrf_token": csrf(page), "version": "0", **hour_values(floor.order)},
    )
    assert response.status_code == 403


def test_admin_preview_changes_only_what_is_shown(roles, client):
    login(client, "owner@aurora.test")
    base = f"/companies/{roles}"
    home = client.get(f"{base}/home")
    assert "See what each job sees" in home.text and "Team and access" in home.text
    response = client.post(
        f"{base}/preview", data={"csrf_token": csrf(home), "role": "factory-maintenance"}
    )
    assert response.status_code == 303
    preview = client.get(f"{base}/home")
    assert "Previewing as <strong>Maintenance technician</strong>" in preview.text
    assert "Report a breakdown" in preview.text and "Planning board" not in preview.text
    # The admin's real access is unchanged while previewing.
    assert client.get(f"{base}/factory/planning").status_code == 200
    client.post(f"{base}/preview", data={"csrf_token": csrf(preview), "role": ""})
    assert "Previewing as" not in client.get(f"{base}/home").text
    response = client.post(f"{base}/preview", data={"csrf_token": csrf(preview), "role": "boss"})
    assert response.status_code == 303


def test_team_screen_changes_a_job_role(roles, client):
    member = give(roles, "auditor@aurora.test", "factory-viewer")
    login(client, "owner@aurora.test")
    base = f"/companies/{roles}"
    page = client.get(f"{base}/team")
    assert page.status_code == 200 and "Manager (dashboard only)" in page.text
    planner = db.session.scalar(
        select(Role).where(Role.organization_id == roles, Role.code == "factory-planner")
    )
    response = client.post(
        f"{base}/team/{member.id}",
        data={
            "csrf_token": csrf(page),
            "role_id": str(planner.id),
            "status": "active",
            "version": str(member.version),
        },
    )
    assert response.status_code == 303
    assigned = db.session.scalars(
        select(MembershipRole.role_id).where(MembershipRole.membership_id == member.id)
    ).all()
    assert assigned == [planner.id]
    login(client, "auditor@aurora.test")
    assert client.get(f"{base}/team").status_code == 403


def test_map_station_and_line_view(roles, floor, client):  # noqa: F811
    company_id = floor.company_id
    balance, _ = balancing.create_balance(company_id, floor.center.id, floor.bulletin.id, 6, 100)
    login(client)
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/map")
    assert page.status_code == 200 and "Sewing" in page.text
    data = client.get(f"{base}/map.json").get_json()
    sewing = next(s for s in data["stations"] if s["key"] == "sewing")
    assert sewing["running"] == 4 and sewing["down"] == 1
    assert {f["source"] for f in data["flows"]} >= {"cutting", "sewing"}
    assert client.get(f"{base}/map/sewing").status_code == 200
    assert client.get(f"{base}/map/yarn").status_code == 404
    visual = client.get(f"{base}/lines/{floor.center.id}/visual")
    assert visual.status_code == 200
    assert 'draggable="true"' in visual.text and "data-move-form" in visual.text
    assert f"balances/{balance.id}/move" in visual.text
