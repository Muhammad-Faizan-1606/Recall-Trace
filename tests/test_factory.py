"""Factory Suite step 1: capacity formulas, register rules, status history and access."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import PASSWORD, csrf, login
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.extensions import db
from app.models import Organization, Permission, Role, RolePermission
from app.models.factory import Machine, MachineClass, MachineStatusEvent, WorkCenter
from app.models.master import Site
from app.services import capacity
from app.services import factory as service
from app.services.business import DomainError
from app.services.factory_demo import SLUG

D = Decimal


def grant(company_id, codes=("factory.read", "factory.manage"), role_code="catalog-editor"):
    role = db.session.scalar(
        select(Role).where(Role.organization_id == company_id, Role.code == role_code)
    )
    for code in codes:
        permission = db.session.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, description=code)
            db.session.add(permission)
            db.session.flush()
        db.session.add(
            RolePermission(organization_id=company_id, role_id=role.id, permission_id=permission.id)
        )
    db.session.commit()


def as_user(app, email="catalog-editor@aurora.test"):
    from flask_login import login_user

    from app.models import User

    context = app.test_request_context()
    context.push()
    login_user(db.session.scalar(select(User).where(User.email == email)))
    return context


# ---------- Pure capacity formulas (worked examples from the MCM blueprint) ----------


def knit_class():
    return SimpleNamespace(
        capacity_basis="knit",
        feeders_per_course=1,
        courses_per_cm=D("16"),
        fabric_width_m=D("1.80"),
        fabric_gsm=D("160"),
        output_unit="kg",
    )


def test_knitting_formula_matches_hand_calculation():
    machine = SimpleNamespace(rated_value=D("30"), feeders=96, efficiency=None)
    center = SimpleNamespace(target_efficiency=D("85"))
    rate = capacity.machine_rate(machine, knit_class(), center)
    metres = D(30) * 96 * D("0.85") * 60 / (1 * D(16) * 100)  # 91.8 m/h
    assert rate.unit == "kg"
    assert rate.per_hour == metres * D("1.80") * D(160) / 1000  # 26.4384 kg/h
    assert "91.8 m/h" in rate.steps[0] and "26.4 kg/h" in rate.steps[1]


def test_knitting_without_feeders_is_reported_not_guessed():
    machine = SimpleNamespace(rated_value=D("30"), feeders=None, efficiency=None)
    rate = capacity.machine_rate(machine, knit_class(), SimpleNamespace(target_efficiency=D(85)))
    assert rate.per_hour == 0 and rate.problem


def test_dyeing_batch_formula_and_daily_throughput():
    vessel = SimpleNamespace(rated_value=D("1000"), feeders=None, efficiency=D("85"))
    jet = SimpleNamespace(
        capacity_basis="batch",
        fill_factor=D("0.90"),
        cycle_hours=D("7"),
        setup_hours=D("1"),
        output_unit="kg",
    )
    rate = capacity.machine_rate(vessel, jet, SimpleNamespace(target_efficiency=D(50)))
    # Blueprint: C = 24 × V × K ÷ (T_cycle + T_setup) × η  (machine efficiency wins over target)
    assert rate.per_hour * 24 == D(24) * 1000 * D("0.90") / 8 * D("0.85")
    assert rate.efficiency == D("0.85")


def test_continuous_rate_and_sewing_bases():
    center = SimpleNamespace(target_efficiency=D("80"))
    stenter = SimpleNamespace(capacity_basis="continuous", output_unit="m")
    assert capacity.machine_rate(
        SimpleNamespace(rated_value=D(40), efficiency=None, feeders=None), stenter, center
    ).per_hour == D(40) * 60 * D("0.8")
    cutter = SimpleNamespace(capacity_basis="rate", output_unit="panels")
    rate = capacity.machine_rate(
        SimpleNamespace(rated_value=D(900), efficiency=None, feeders=None), cutter, center
    )
    assert (rate.per_hour, rate.unit) == (D(720), "panels")


def test_sewing_line_target_output_matches_blueprint_example():
    # 50 operators × 480 min × 70% ÷ 20 SAM = 840 pieces per shift.
    station = SimpleNamespace(capacity_basis="sewing", output_unit="SAM min")
    line = SimpleNamespace(target_efficiency=D("70"))
    machines = [
        (
            SimpleNamespace(
                rated_value=D(1),
                efficiency=None,
                feeders=None,
                status="active",
                archived_at=None,
                asset_tag=f"S{n}",
            ),
            station,
        )
        for n in range(50)
    ]
    result = capacity.center_capacity(line, machines)
    minutes = result.per_day(D(8))["SAM min"]
    assert minutes == D(16800) and minutes / 20 == 840


def test_unavailable_machines_add_nothing():
    station = SimpleNamespace(capacity_basis="sewing", output_unit="SAM min")
    machines = [
        (
            SimpleNamespace(
                rated_value=D(1),
                efficiency=None,
                feeders=None,
                status=status,
                archived_at=None,
                asset_tag=status,
            ),
            station,
        )
        for status in ("active", "idle", "maintenance", "decommissioned")
    ]
    result = capacity.center_capacity(SimpleNamespace(target_efficiency=D(100)), machines)
    assert (result.available, result.total, result.per_hour["SAM min"]) == (2, 4, D(120))


def test_shift_hours_respect_working_days_breaks_and_exceptions():
    pattern = SimpleNamespace(
        shifts_per_day=2,
        hours_per_shift=D("10"),
        break_minutes_per_shift=60,
        working_days="1111110",
    )
    friday, sunday = date(2026, 11, 13), date(2026, 11, 15)
    assert capacity.shift_hours(pattern, friday, {}) == (D(18), "normal day")
    assert capacity.shift_hours(pattern, sunday, {})[0] == 0
    holiday = SimpleNamespace(hours_per_shift=D(0), kind="holiday", note="Quaid-e-Azam Day")
    assert capacity.shift_hours(pattern, friday, {friday: holiday})[0] == 0
    overtime = SimpleNamespace(hours_per_shift=D(12), kind="overtime", note="Late order")
    hours, reason = capacity.shift_hours(pattern, sunday, {sunday: overtime})
    assert hours == D(22) and "overtime" in reason


# ---------- Register rules through the service layer ----------


def build_register(company_id):
    site = Site(
        organization_id=company_id, code="S1", name="Site one", address_text="x", country_code="PK"
    )
    db.session.add(site)
    db.session.commit()
    pattern = service.save(
        company_id,
        "shift-patterns",
        {
            "code": "DAY",
            "name": "Day",
            "shifts_per_day": 1,
            "hours_per_shift": D(9),
            "break_minutes_per_shift": 60,
            "working_days": ["0", "1", "2", "3", "4", "5"],
        },
    )
    center = service.save(
        company_id,
        "work-centers",
        {
            "code": "KNIT",
            "name": "Knitting",
            "department": "knitting",
            "site_id": site.id,
            "shift_pattern_id": pattern.id,
            "target_efficiency": D(85),
        },
    )
    knit = service.save(
        company_id,
        "machine-classes",
        {
            "code": "SJ",
            "name": "Single jersey",
            "department": "knitting",
            "capacity_basis": "knit",
            "feeders_per_course": 1,
            "courses_per_cm": D(16),
            "fabric_width_m": D("1.8"),
            "fabric_gsm": D(160),
        },
    )
    return site, pattern, center, knit


def machine_values(knit, center, **extra):
    values = {
        "asset_tag": "K-01",
        "make_model": "Frame",
        "machine_class_id": knit.id,
        "work_center_id": center.id,
        "rated_value": D(30),
        "feeders": 96,
    }
    values.update(extra)
    return values


def test_register_validates_formula_inputs_and_department(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    context = as_user(app)
    try:
        site, pattern, center, knit = build_register(company_id)
        assert pattern.working_days == "1111110"
        with pytest.raises(DomainError, match="needs"):
            service.save(
                company_id,
                "machine-classes",
                {
                    "code": "BAD",
                    "name": "Bad",
                    "department": "dyeing",
                    "capacity_basis": "batch",
                },
            )
        with pytest.raises(DomainError, match="output unit"):
            service.save(
                company_id,
                "machine-classes",
                {
                    "code": "CUT",
                    "name": "Cutter",
                    "department": "cutting",
                    "capacity_basis": "rate",
                },
            )
        with pytest.raises(DomainError, match="feeders"):
            service.save(company_id, "machines", machine_values(knit, center, feeders=None))
        jet = service.save(
            company_id,
            "machine-classes",
            {
                "code": "JET",
                "name": "Jet",
                "department": "dyeing",
                "capacity_basis": "batch",
                "fill_factor": D("0.9"),
                "cycle_hours": D(7),
                "setup_hours": D(1),
            },
        )
        assert jet.output_unit == "kg" and jet.courses_per_cm is None
        with pytest.raises(DomainError, match="cannot be placed"):
            service.save(company_id, "machines", machine_values(jet, center, asset_tag="J-1"))
        with pytest.raises(DomainError, match="different sites"):
            service.save(
                company_id,
                "transit",
                {"from_site_id": site.id, "to_site_id": site.id, "hours": D(4)},
            )
        machine = service.save(company_id, "machines", machine_values(knit, center))
        assert machine.status == "active"
        events = db.session.scalars(
            select(MachineStatusEvent).where(MachineStatusEvent.machine_id == machine.id)
        ).all()
        assert [e.reason for e in events] == ["Registered"]
    finally:
        context.pop()


def test_status_changes_are_recorded_and_history_is_immutable(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    context = as_user(app)
    try:
        _, _, center, knit = build_register(company_id)
        machine = service.save(company_id, "machines", machine_values(knit, center))
        service.change_status(company_id, machine.id, "maintenance", "Needle bed", machine.version)
        db.session.refresh(machine)
        assert machine.status == "maintenance"
        result = capacity.center_capacity(center, service.machines_by_center(company_id)[center.id])
        assert result.available == 0 and result.per_hour == {}
        with pytest.raises(DomainError, match="already"):
            service.change_status(company_id, machine.id, "maintenance", "x", machine.version)
        with pytest.raises(DomainError, match="reason"):
            service.change_status(company_id, machine.id, "active", "  ", machine.version)
        event_id = db.session.scalar(
            select(MachineStatusEvent.id).where(MachineStatusEvent.to_status == "maintenance")
        )
        with pytest.raises(DBAPIError):
            db.session.execute(
                text("UPDATE machine_status_events SET reason = 'edited' WHERE id = :id"),
                {"id": event_id},
            )
        db.session.rollback()
        # A machine with history is archived, not deleted.
        machine = db.session.get(Machine, machine.id)
        message = service.remove(company_id, "machines", machine.id, machine.version)
        assert "archived" in message
    finally:
        context.pop()


def test_related_records_must_belong_to_the_same_company(app, records):
    aurora, beacon = records["companies"]["aurora"], records["companies"]["beacon"]
    grant(aurora)
    grant(beacon)
    context = as_user(app)
    try:
        _, _, center, knit = build_register(aurora)
    finally:
        context.pop()
    context = as_user(app, "catalog-editor@beacon.test")
    try:
        with pytest.raises(Exception) as caught:
            service.save(beacon, "machines", machine_values(knit, center))
        assert getattr(caught.value, "code", None) == 404
    finally:
        context.pop()


# ---------- Screens, permissions and the demo seed ----------


def test_factory_pages_need_permission(app, records, client):
    company_id = records["companies"]["aurora"]
    login(client)
    assert client.get(f"/companies/{company_id}/factory").status_code == 403
    grant(company_id, codes=("factory.read",))
    assert client.get(f"/companies/{company_id}/factory").status_code == 200
    form = client.get(f"/companies/{company_id}/factory/machines")
    assert form.status_code == 200
    assert client.get(f"/companies/{company_id}/factory/machines/new").status_code == 403
    other = records["companies"]["beacon"]
    assert client.get(f"/companies/{other}/factory").status_code == 404


def test_demo_factory_seeds_once_and_every_screen_renders(app, records, client):
    runner = app.test_cli_runner()
    result = runner.invoke(
        args=["seed-factory-demo", "--owner-email", "catalog-editor@aurora.test"]
    )
    assert result.exit_code == 0, result.output
    assert "1156 machines" in result.output
    again = runner.invoke(args=["seed-factory-demo", "--owner-email", "catalog-editor@aurora.test"])
    assert "nothing changed" in again.output
    company = db.session.scalar(select(Organization).where(Organization.slug == SLUG))
    assert (
        db.session.scalar(
            select(db.func.count())
            .select_from(Machine)
            .where(Machine.organization_id == company.id)
        )
        == 1156
    )
    login(client)
    base = f"/companies/{company.id}/factory"
    page = client.get(base)
    assert page.status_code == 200
    assert "Dye house" in page.text and "Sewing lines (10)" in page.text and "T-shirts" in page.text
    for resource in service.RESOURCES:
        assert client.get(f"{base}/{resource}").status_code == 200
        assert client.get(f"{base}/{resource}/new").status_code == 200
    assert client.get(f"{base}/setup").status_code == 200
    dye = db.session.scalar(
        select(WorkCenter).where(
            WorkCenter.organization_id == company.id, WorkCenter.code == "MANGA-DYE"
        )
    )
    detail = client.get(f"{base}/work-centers/{dye.id}")
    assert "Next 14 days" in detail.text and "not counted while in maintenance" in detail.text
    vessel = db.session.scalar(
        select(Machine).where(
            Machine.organization_id == company.id, Machine.asset_tag == "DYE-JET-09"
        )
    )
    page = client.get(f"{base}/machines/{vessel.id}")
    assert "Main circulation pump seal leaking" in page.text and "kg/h" in page.text
    # Status change through the real form, with CSRF.
    token = csrf(page)
    response = client.post(
        f"{base}/machines/{vessel.id}/status",
        data={
            "csrf_token": token,
            "version": str(vessel.version),
            "to_status": "active",
            "reason": "Seal replaced",
        },
    )
    assert response.status_code == 303
    db.session.expire_all()
    assert db.session.get(Machine, vessel.id).status == "active"
    assert PASSWORD  # the seeded owner signs in with the shared fictional password


def test_new_machine_class_through_the_form(app, records, client):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    login(client)
    url = f"/companies/{company_id}/factory/machine-classes/new"
    token = csrf(client.get(url))
    response = client.post(
        url,
        data={
            "csrf_token": token,
            "version": "0",
            "code": "PRT",
            "name": "Oval printer",
            "department": "embellishment",
            "capacity_basis": "rate",
            "output_unit": "impressions",
        },
    )
    assert response.status_code == 303, response.text
    row = db.session.scalar(select(MachineClass).where(MachineClass.code == "PRT"))
    assert row.output_unit == "impressions" and row.organization_id == company_id
