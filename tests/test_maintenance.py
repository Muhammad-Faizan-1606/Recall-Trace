"""Factory Suite step 7: maintenance tickets, preventive schedule, MTBF/MTTR and alerts.

Uses the one-line factory from test_balancing: overlocks OL-1..OL-3 and lockstitch LS-2
active, LS-1 already in maintenance.

Reliability worked example (90-day window, machine commissioned long before it):
two breakdowns repaired in 2 h and 4 h, work starting after 30 and 10 minutes.

    MTTR     = (2 + 4) ÷ 2 = 3 h
    MTBF     = (90 × 24 − 6) ÷ 2 = 1,077 h
    response = (30 + 10) ÷ 2 = 20 min
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import csrf, login
from sqlalchemy import select
from test_balancing import line  # noqa: F401
from test_factory import grant

from app.extensions import db
from app.models import now
from app.models.factory import (
    FactoryAlert,
    Machine,
    MachineStatusEvent,
    MaintenancePlan,
    MaintenanceTicket,
)
from app.services import alerts, capacity, maintenance
from app.services import factory as service
from app.services.business import DomainError

D = Decimal


def machine(tag):
    return db.session.scalar(select(Machine).where(Machine.asset_tag == tag))


def events(tag):
    return [
        (e.from_status, e.to_status)
        for e in db.session.scalars(
            select(MachineStatusEvent)
            .where(MachineStatusEvent.machine_id == machine(tag).id)
            .order_by(MachineStatusEvent.occurred_at)
        )
    ]


@pytest.fixture
def shop(line):  # noqa: F811
    grant(line.company_id, codes=("factory.record",))
    return line


def available(shop):
    from app.services.factory import machines_by_center

    rows = machines_by_center(shop.company_id, [shop.center.id])[shop.center.id]
    return capacity.center_capacity(shop.center, rows).available


def test_breakdown_takes_the_machine_out_of_capacity_until_closed(shop):
    company_id = shop.company_id
    assert available(shop) == 4
    ticket = maintenance.report_breakdown(
        company_id, {"asset_tag": " ol-1 ", "description": "Looper timing"}
    )
    assert (ticket.number, ticket.status, machine("OL-1").status) == (
        "MT-00001",
        "open",
        "maintenance",
    )
    assert available(shop) == 3
    with pytest.raises(DomainError, match="unfinished ticket"):
        maintenance.report_breakdown(company_id, {"asset_tag": "OL-1", "description": "Again"})
    with pytest.raises(DomainError, match="No machine"):
        maintenance.report_breakdown(company_id, {"asset_tag": "XX-9", "description": "x"})
    with pytest.raises(DomainError, match="Start work"):
        maintenance.close(company_id, ticket.id, ticket.version, "Fixed")
    ticket = maintenance.start(company_id, ticket.id, ticket.version)
    with pytest.raises(DomainError, match="changed"):
        maintenance.close(company_id, ticket.id, ticket.version - 1, "Fixed")
    with pytest.raises(DomainError, match="Work done"):
        maintenance.close(company_id, ticket.id, ticket.version, " ")
    ticket = maintenance.close(company_id, ticket.id, ticket.version, "Retimed looper", "Needle")
    assert ticket.finished_at >= ticket.started_at >= ticket.reported_at
    assert machine("OL-1").status == "active" and available(shop) == 4
    assert events("OL-1")[-2:] == [("active", "maintenance"), ("maintenance", "active")]


def plan(company_id, every=10, class_id=None):
    return service.save(
        company_id,
        "maintenance-plans",
        {
            "code": "PM-OL",
            "name": "Overlock service",
            "machine_class_id": class_id,
            "interval_days": every,
            "duration_minutes": 30,
            "tasks": "Clean and oil",
        },
    )


def test_preventive_jobs_follow_the_schedule(shop):
    company_id = shop.company_id
    today = date.today()
    pm = plan(company_id, class_id=shop.classes["OL"].id)
    for tag in ("OL-1", "OL-2", "OL-3"):
        row = machine(tag)
        row.commissioned_on = today - timedelta(days=30)
    db.session.commit()
    due = maintenance.schedule(company_id, today)
    assert [(d.machine.asset_tag, d.due_on) for d in due] == [
        (tag, today - timedelta(days=20)) for tag in ("OL-1", "OL-2", "OL-3")
    ]
    with pytest.raises(DomainError, match="different kind"):
        maintenance.plan_job(company_id, pm.id, machine("LS-2").id)
    job = maintenance.plan_job(company_id, pm.id, machine("OL-2").id)
    assert machine("OL-2").status == "active"  # keeps running until work starts
    job = maintenance.start(company_id, job.id, job.version)
    assert machine("OL-2").status == "maintenance"
    maintenance.close(company_id, job.id, job.version, "Cleaned and oiled")
    due = {d.machine.asset_tag: d for d in maintenance.schedule(company_id, today, 30)}
    assert due["OL-2"].last_done == today and due["OL-2"].due_on == today + timedelta(days=10)
    assert due["OL-1"].due_on < today


def test_reliability_matches_the_worked_example(shop):
    company_id = shop.company_id
    moment = now()
    row = machine("OL-3")
    row.commissioned_on = date(2024, 1, 1)
    for number, (days, response, repair) in enumerate(((40, 30, 2), (10, 10, 4)), 1):
        reported = moment - timedelta(days=days)
        db.session.add(
            MaintenanceTicket(
                organization_id=company_id,
                number=f"MT-H{number}",
                machine_id=row.id,
                kind="breakdown",
                description="x",
                reported_at=reported,
                started_at=reported + timedelta(minutes=response),
                finished_at=reported + timedelta(hours=repair),
                status="closed",
                work_done="y",
            )
        )
    db.session.commit()
    stats = maintenance.reliability(company_id, moment)[row.id]
    assert stats.breakdowns == 2
    assert stats.mttr == pytest.approx(3.0)
    assert stats.mtbf == pytest.approx((90 * 24 - 6) / 2)
    assert stats.response == pytest.approx(20 / 60)


def test_overdue_plans_raise_one_alert_each(shop):
    company_id = shop.company_id
    today = date.today()
    pm = plan(company_id, class_id=shop.classes["OL"].id)
    for tag in ("OL-1", "OL-2", "OL-3"):
        machine(tag).commissioned_on = today - timedelta(days=30)
    db.session.commit()
    alerts.scan(company_id, day=today)
    alert = db.session.scalar(
        select(FactoryAlert).where(FactoryAlert.kind == "maintenance_overdue")
    )
    assert alert.title == "3 machines overdue for Overlock service"
    assert alert.severity == "critical"  # 20 days late
    maintenance.plan_job(company_id, pm.id, machine("OL-1").id)
    alerts.scan(company_id, day=today)
    db.session.refresh(alert)
    assert alert.title == "2 machines overdue for Overlock service"
    assert db.session.get(MaintenancePlan, pm.id).interval_days == 10


def test_maintenance_screens_and_permissions(shop, client):
    company_id = shop.company_id
    plan(company_id, class_id=shop.classes["OL"].id)
    login(client)
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/maintenance")
    assert page.status_code == 200 and "Report a breakdown" in page.text
    response = client.post(
        f"{base}/maintenance/breakdowns",
        data={
            "csrf_token": csrf(page),
            "version": "0",
            "asset_tag": "OL-3",
            "description": "Knife blunt",
        },
    )
    assert response.status_code == 303
    ticket_page = client.get(response.headers["Location"])
    assert "Start work" in ticket_page.text and "Knife blunt" in ticket_page.text
    history = client.get(f"{base}/maintenance/machines/{machine('OL-3').id}")
    assert history.status_code == 200 and "MT-00001" in history.text
    assert "Maintenance history" in client.get(f"{base}/machines/{machine('OL-3').id}").text
    assert client.get(f"{base}/maintenance-plans").status_code == 200

    grant(company_id, codes=("factory.read",), role_code="auditor")
    client.post("/logout", data={"csrf_token": csrf(page)})
    login(client, "auditor@aurora.test")
    page = client.get(f"{base}/maintenance")
    assert page.status_code == 200 and 'name="asset_tag"' not in page.text
    response = client.post(
        f"{base}/maintenance/breakdowns",
        data={"csrf_token": csrf(page), "version": "0", "asset_tag": "OL-2", "description": "x"},
    )
    assert response.status_code == 403
    assert machine("OL-2").status == "active"
