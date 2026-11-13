"""Factory Suite step 6: factory checks, alert lifecycle and the management dashboard.

The line from test_balancing has no published balance unless a test adds one, so its plan
is the work centre's own 100% target: 6 operators × 60 min at SAM 4.0 earn 90 pieces an
hour at plan. 60 pieces an hour is therefore 66.7% (low); 99 is 110% (high).
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from conftest import csrf, login
from sqlalchemy import select
from test_balancing import line  # noqa: F401
from test_factory import grant
from test_shopfloor import TODAY, floor, hour_values, mill  # noqa: F401

from app.extensions import db
from app.models import now
from app.models.evidence import Notification
from app.models.factory import DyeBatch, FabricSpec, FactoryAlert, Machine, ProductionOrder
from app.services import alerts, balancing, shopfloor
from app.services import factory as service
from app.services.business import DomainError

D = Decimal


def kinds(company_id):
    return sorted(
        (a.kind, a.severity, a.status, a.cleared_at is not None)
        for a in db.session.scalars(
            select(FactoryAlert).where(FactoryAlert.organization_id == company_id)
        )
    )


def test_efficiency_window_raises_low_and_high(mill):  # noqa: F811
    company_id = mill.company_id
    for hour in (1, 2, 3, 4):
        shopfloor.record_output(
            company_id, mill.center.id, hour_values(mill.order, hour=hour, good=60), today=TODAY
        )
    raised, cleared, active = alerts.scan(company_id, day=TODAY)
    assert (raised, cleared, active) == (1, 0, 1)
    alert = db.session.scalar(select(FactoryAlert))
    assert alert.kind == "efficiency_low" and "66.7% against a plan of 100.0%" in alert.title
    assert "Hours 2–4" in alert.detail
    # Running the checks again keeps one alert for the condition.
    assert alerts.scan(company_id, day=TODAY)[0] == 0
    # Restating the last three hours above plan clears the low alert and raises a high one.
    for hour in (2, 3, 4):
        original = db.session.scalar(
            select(shopfloor.OutputLog).where(shopfloor.OutputLog.hour == hour)
        )
        shopfloor.correct_output(
            company_id,
            original.id,
            hour_values(mill.order, hour=hour, good=99, note="Recount"),
            today=TODAY,
        )
    alerts.scan(company_id, day=TODAY)
    assert kinds(company_id) == [("efficiency_high", "info", "open", False)]
    # The same key: the low alert was updated in place, not duplicated.
    assert db.session.scalar(select(FactoryAlert)).id == alert.id


def test_late_orders_machine_down_and_clearing(mill):  # noqa: F811
    company_id = mill.company_id
    order = mill.planned
    order.planned_start_on = TODAY
    order.planned_finish_on = order.ex_factory_on + timedelta(days=3)
    db.session.commit()
    machine = db.session.scalar(select(Machine).where(Machine.asset_tag == "OL-2"))
    service.change_status(company_id, machine.id, "maintenance", "Looper timing", machine.version)
    moment = now()
    alerts.scan(company_id, day=TODAY, moment=moment)
    assert kinds(company_id) == [("order_late", "warning", "open", False)]
    alerts.scan(company_id, day=TODAY, moment=moment + timedelta(minutes=31))
    assert ("machine_down", "warning", "open", False) in kinds(company_id)
    alerts.scan(company_id, day=TODAY, moment=moment + timedelta(hours=25))
    assert ("machine_down", "critical", "open", False) in kinds(company_id)
    order.planned_finish_on = order.ex_factory_on
    db.session.commit()
    alerts.scan(company_id, day=TODAY, moment=moment + timedelta(hours=26))
    assert ("order_late", "warning", "open", True) in kinds(company_id)


def test_relaxation_and_starving_lines(mill):  # noqa: F811
    company_id = mill.company_id
    db.session.add(
        FabricSpec(
            organization_id=company_id,
            style_id=mill.style.id,
            component="Body",
            fabric_type="single_jersey",
            composition="Cotton",
            gsm=D(160),
            width_m=D("1.8"),
            consumption_kg=D("0.2"),
            relaxation_hours=24,
        )
    )
    batch = DyeBatch(
        organization_id=company_id,
        batch_number="DB-1",
        machine_id=mill.vessel.id,
        colour="Black",
        recipe_reference="R",
        status="passed",
        started_at=now() - timedelta(hours=9),
        finished_at=now() - timedelta(hours=2),
    )
    db.session.add(batch)
    db.session.commit()
    balance, _ = balancing.create_balance(company_id, mill.center.id, mill.bulletin.id, 6, D(100))
    balancing.publish(company_id, balance.id, db.session.get(type(balance), balance.id).version)
    bundles = shopfloor.cut_bundles(
        company_id,
        {
            "production_order_id": str(mill.order.id),
            "dye_batch_id": str(batch.id),
            "lay_number": "L-1",
            "bundle_size": 10,
            "sizes": "M:20",
        },
    )
    shopfloor.bundle_step(company_id, bundles[0].id, "issue", bundles[0].version, mill.center.id)
    shopfloor.record_output(
        company_id, mill.center.id, hour_values(mill.order, good=80), today=TODAY
    )
    alerts.scan(company_id, day=TODAY)
    found = {a.kind: a for a in db.session.scalars(select(FactoryAlert))}
    assert found["relaxation_breach"].severity == "critical"
    assert "22 h before batch DB-1 relaxed" in found["relaxation_breach"].title
    # Plan: 640 pieces in 480 min = 80 an hour; 10 pieces waiting is under an hour.
    assert "10 pieces waiting" in found["line_starving"].title
    shopfloor.bundle_step(company_id, bundles[1].id, "issue", bundles[1].version, mill.center.id)
    more = shopfloor.cut_bundles(
        company_id,
        {
            "production_order_id": str(mill.order.id),
            "lay_number": "L-2",
            "bundle_size": 70,
            "sizes": "L:70",
        },
    )
    shopfloor.bundle_step(company_id, more[0].id, "issue", more[0].version, mill.center.id)
    alerts.scan(company_id, day=TODAY)
    assert db.session.get(FactoryAlert, found["line_starving"].id).cleared_at is not None


def test_acknowledge_assign_notify_and_resolve(mill):  # noqa: F811
    company_id = mill.company_id
    order = mill.planned
    order.planned_start_on = TODAY
    order.planned_finish_on = order.ex_factory_on + timedelta(days=1)
    db.session.commit()
    alerts.scan(company_id, day=TODAY)
    alert = db.session.scalar(select(FactoryAlert))
    from app.policies import membership_for

    me = membership_for(company_id)
    alert = alerts.acknowledge(company_id, alert.id, alert.version, me.id)
    assert (alert.status, alert.owner_id) == ("acknowledged", me.id)
    note = db.session.scalar(select(Notification).where(Notification.membership_id == me.id))
    assert note.event_type == "factory_alert" and order.reference in note.safe_payload["message"]
    with pytest.raises(DomainError, match="Say what was done"):
        alerts.resolve(company_id, alert.id, alert.version, " ")
    with pytest.raises(DomainError, match="changed"):
        alerts.resolve(company_id, alert.id, alert.version - 1, "Added a line")
    alerts.resolve(company_id, alert.id, alert.version, "Added a sewing line; replanned")
    # The condition still exists, so the next check raises a fresh alert for it.
    alerts.scan(company_id, day=TODAY)
    assert kinds(company_id) == [
        ("order_late", "warning", "open", False),
        ("order_late", "warning", "resolved", False),
    ]
    resolved = db.session.scalar(select(FactoryAlert).where(FactoryAlert.status == "resolved"))
    with pytest.raises(DomainError, match="already resolved"):
        alerts.resolve(company_id, resolved.id, resolved.version, "again")


def test_dashboard_and_alert_screens(mill, client):  # noqa: F811
    company_id = mill.company_id
    for hour in (1, 2):
        shopfloor.record_output(
            company_id,
            mill.center.id,
            hour_values(mill.order, hour=hour, good=60, day=TODAY.isoformat()),
            today=TODAY,
        )
    login(client)
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/alerts")
    assert page.status_code == 200 and "Run checks now" in page.text
    response = client.post(f"{base}/alerts/check", data={"csrf_token": csrf(page), "version": "0"})
    assert response.status_code == 303
    dashboard = client.get(f"{base}/dashboard")
    assert dashboard.status_code == 200
    for heading in (
        "Capacity booked",
        "Sewing efficiency by day",
        "Top downtime reasons",
        "Orders at risk",
    ):
        assert heading in dashboard.text
    assert client.get(f"{base}/alerts?show=resolved").status_code == 200
    assert client.get(f"{base}/alerts?show=nonsense").status_code == 404


def test_read_only_members_can_check_but_not_act(mill, client):  # noqa: F811
    company_id = mill.company_id
    order = mill.planned
    order.planned_start_on = TODAY
    order.planned_finish_on = order.ex_factory_on + timedelta(days=1)
    db.session.commit()
    alerts.scan(company_id, day=TODAY)
    alert = db.session.scalar(select(FactoryAlert))
    grant(company_id, codes=("factory.read",), role_code="auditor")
    login(client, "auditor@aurora.test")
    page = client.get(f"/companies/{company_id}/factory/alerts")
    assert page.status_code == 200 and "Acknowledge or resolve" not in page.text
    response = client.post(
        f"/companies/{company_id}/factory/alerts/{alert.id}/resolve",
        data={"csrf_token": csrf(page), "version": str(alert.version), "note": "x"},
    )
    assert response.status_code == 403
    assert db.session.get(FactoryAlert, alert.id).status == "open"
    assert db.session.get(ProductionOrder, order.id).status == "planned"
