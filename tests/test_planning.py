"""Factory Suite step 3: stage loads, finite-capacity scheduling, what-if and screens.

A tiny two-site factory makes every number checkable by hand (all at 100% efficiency,
one 8-hour shift every day):

knitting   30 RPM × 96 feeders × 60 ÷ (1 × 16 × 100) = 108 m/h × 1.8 m × 160 g ÷ 1000
           = 31.104 kg/h → 248.832 kg/day                         (site A)
dyeing     1000 kg × 0.9 ÷ (7 + 1) h = 112.5 kg/h → 900 kg/day    (site A)
finishing  40 m/min × 60 = 2,400 m/h → 19,200 m/day               (site A)
cutting    900 panels/h → 7,200 panels/day                        (site B, 5 h from A)
sewing     two lines of 10 stations: 600 SAM min/h → 4,800/day each (site B)
packing    600 pieces/h → 4,800 pieces/day                        (site B)
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import csrf, login
from sqlalchemy import select
from test_factory import as_user, grant

from app.extensions import db
from app.models.factory import (
    BulletinOperation,
    CalendarException,
    CapacityBooking,
    Machine,
    OperationBulletin,
    ProductionOrder,
)
from app.models.master import Site
from app.services import factory as service
from app.services import planning
from app.services.business import DomainError

D = Decimal
MONDAY = date(2026, 11, 16)


def mini_factory(company_id):
    site_a = Site(
        organization_id=company_id, code="A", name="Site A", address_text="x", country_code="PK"
    )
    site_b = Site(
        organization_id=company_id, code="B", name="Site B", address_text="x", country_code="PK"
    )
    db.session.add_all([site_a, site_b])
    db.session.commit()
    pattern = service.save(
        company_id,
        "shift-patterns",
        {
            "code": "D8",
            "name": "Day",
            "shifts_per_day": 1,
            "hours_per_shift": D(8),
            "break_minutes_per_shift": 0,
            "working_days": [str(i) for i in range(7)],
        },
    )
    service.save(
        company_id,
        "transit",
        {
            "from_site_id": site_a.id,
            "to_site_id": site_b.id,
            "hours": D(5),
        },
    )
    classes = {}
    for code, department, basis, extra in [
        (
            "KNIT",
            "knitting",
            "knit",
            {
                "feeders_per_course": 1,
                "courses_per_cm": D(16),
                "fabric_width_m": D("1.8"),
                "fabric_gsm": D(160),
            },
        ),
        (
            "JET",
            "dyeing",
            "batch",
            {"fill_factor": D("0.9"), "cycle_hours": D(7), "setup_hours": D(1)},
        ),
        ("STN", "finishing", "continuous", {}),
        ("CUT", "cutting", "rate", {"output_unit": "panels"}),
        ("SEW", "sewing", "sewing", {}),
        ("PACK", "packing", "rate", {"output_unit": "pieces"}),
    ]:
        classes[code] = service.save(
            company_id,
            "machine-classes",
            {
                "code": code,
                "name": code,
                "department": department,
                "capacity_basis": basis,
                **extra,
            },
        )
    centers = {}
    for code, department, site in [
        ("KNIT", "knitting", site_a),
        ("DYE", "dyeing", site_a),
        ("FIN", "finishing", site_a),
        ("CUT", "cutting", site_b),
        ("L1", "sewing", site_b),
        ("L2", "sewing", site_b),
        ("PACK", "packing", site_b),
    ]:
        centers[code] = service.save(
            company_id,
            "work-centers",
            {
                "code": code,
                "name": code,
                "department": department,
                "site_id": site.id,
                "shift_pattern_id": pattern.id,
                "target_efficiency": D(100),
            },
        )
    rated = {
        "KNIT": ("KNIT", 30),
        "DYE": ("JET", 1000),
        "FIN": ("STN", 40),
        "CUT": ("CUT", 900),
        "PACK": ("PACK", 600),
    }
    for center, (class_code, value) in rated.items():
        db.session.add(
            Machine(
                organization_id=company_id,
                asset_tag=f"M-{center}",
                make_model="x",
                machine_class_id=classes[class_code].id,
                work_center_id=centers[center].id,
                rated_value=D(value),
                feeders=96 if class_code == "KNIT" else None,
            )
        )
    for line in ("L1", "L2"):
        for n in range(10):
            db.session.add(
                Machine(
                    organization_id=company_id,
                    asset_tag=f"{line}-{n}",
                    make_model="x",
                    machine_class_id=classes["SEW"].id,
                    work_center_id=centers[line].id,
                    rated_value=D(1),
                )
            )
    db.session.commit()
    style = service.save(
        company_id,
        "styles",
        {
            "code": "TEE",
            "name": "Tee",
            "product_type": "tee",
        },
    )
    service.save(
        company_id,
        "fabric-specs",
        {
            "style_id": style.id,
            "component": "Body",
            "fabric_type": "single_jersey",
            "composition": "Cotton",
            "gsm": D(160),
            "width_m": D("1.8"),
            "consumption_kg": D("0.2"),
            "relaxation_hours": 24,
        },
    )
    bulletin = OperationBulletin(organization_id=company_id, style_id=style.id, revision=1)
    db.session.add(bulletin)
    db.session.flush()
    db.session.add(
        BulletinOperation(
            organization_id=company_id,
            bulletin_id=bulletin.id,
            sequence=10,
            name="Make",
            basic_minutes=D(4),
            allowance_factor=D("0.25"),
            sam=D(5),
        )
    )
    db.session.flush()
    bulletin.status = "published"
    bulletin.published_at = planning.now()
    db.session.commit()
    return SimpleNamespace(site_a=site_a, site_b=site_b, style=style, centers=centers)


def order_values(factory, reference="PO-1", quantity=1000, days=10, priority=3, lines=2):
    return {
        "reference": reference,
        "style_id": factory.style.id,
        "quantity": quantity,
        "colour": "Black",
        "ex_factory_on": MONDAY + timedelta(days=days),
        "priority": priority,
        "sewing_lines": lines,
        "prints_per_piece": 0,
    }


@pytest.fixture
def factory(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    context = as_user(app)
    built = mini_factory(company_id)
    built.company_id = company_id
    yield built
    context.pop()


def steps_of(company_id, order_id):
    return {stage: rest for stage, *rest in planning.stored_steps(company_id, [order_id])[order_id]}


# ---------- Loads ----------


def test_stage_loads_are_written_out():
    order = SimpleNamespace(quantity=1000, prints_per_piece=2)
    style = SimpleNamespace(product_type="hoodie")
    fabric = SimpleNamespace(consumption_kg=D("0.2"), gsm=D(160), width_m=D("1.8"))
    loads = planning.order_loads(order, style, [fabric], D(5))
    assert loads["knitting"].quantity == D(220) and loads["dyeing"].quantity == D(210)
    assert round(loads["finishing"].quantity, 2) == D("694.44")
    assert (
        loads["cutting"].quantity == D(10000) and "10 panels (hoodie)" in loads["cutting"].working
    )
    assert loads["embellishment"].quantity == D(2000)
    assert loads["sewing"].quantity == D(5000) and loads["packing"].quantity == D(1000)


# ---------- Scheduling rules ----------


def test_relaxation_and_transit_push_cutting_two_days(factory):
    order = planning.save_order(factory.company_id, order_values(factory), today=MONDAY)
    assert order.status == "planned"
    steps = steps_of(factory.company_id, order.id)
    assert steps["knitting"][:2] == [MONDAY, MONDAY]  # 220 kg < 248.832 kg/day
    assert steps["dyeing"][0] == MONDAY and steps["finishing"][0] == MONDAY  # same site
    # 5 h transit A → B plus 24 h relaxation = 29 h, rounded up to 2 days.
    assert steps["cutting"][0] == MONDAY + timedelta(days=2)
    assert steps["sewing"][3] == "SAM min" and len(steps["sewing"][4]) == 2  # split over L1, L2
    assert order.planned_finish_on == MONDAY + timedelta(days=2)
    bookings = db.session.scalars(
        select(CapacityBooking).where(
            CapacityBooking.production_order_id == order.id, CapacityBooking.stage == "sewing"
        )
    ).all()
    assert sorted(b.quantity for b in bookings) == [D(2500), D(2500)]


def test_daily_capacity_carries_over_and_holidays_are_skipped(factory):
    db.session.add(
        CalendarException(
            organization_id=factory.company_id,
            site_id=factory.site_a.id,
            day=MONDAY + timedelta(days=1),
            kind="holiday",
            hours_per_shift=D(0),
            note="Holiday",
        )
    )
    db.session.commit()
    order = planning.save_order(
        factory.company_id, order_values(factory, quantity=2500), today=MONDAY
    )
    knit = db.session.scalars(
        select(CapacityBooking)
        .where(CapacityBooking.production_order_id == order.id, CapacityBooking.stage == "knitting")
        .order_by(CapacityBooking.day)
    ).all()
    # 550 kg: 248.832 on Monday, nothing on the holiday, 248.832 Wednesday, rest Thursday.
    assert [b.day - MONDAY for b in knit] == [timedelta(0), timedelta(2), timedelta(3)]
    assert knit[0].quantity == D("248.832") and sum(b.quantity for b in knit) == D(550)


def test_priority_decides_who_gets_capacity_and_released_plans_stay(factory):
    company_id = factory.company_id
    low = planning.save_order(
        company_id, order_values(factory, "LOW", 2000, priority=4), today=MONDAY
    )
    high = planning.save_order(
        company_id, order_values(factory, "HIGH", 2000, priority=1), today=MONDAY
    )
    assert steps_of(company_id, high.id)["knitting"][0] == MONDAY
    assert steps_of(company_id, low.id)["knitting"][0] == MONDAY + timedelta(days=1)
    planning.transition(company_id, low.id, "release", low.version, today=MONDAY)
    frozen = sorted(
        (b.stage, b.day, b.quantity)
        for b in db.session.scalars(
            select(CapacityBooking).where(CapacityBooking.production_order_id == low.id)
        )
    )
    planning.save_order(company_id, order_values(factory, "URGENT", 2000, priority=1), today=MONDAY)
    again = sorted(
        (b.stage, b.day, b.quantity)
        for b in db.session.scalars(
            select(CapacityBooking).where(CapacityBooking.production_order_id == low.id)
        )
    )
    assert again == frozen  # released orders are planned around, never moved
    with pytest.raises(DomainError, match="cannot be edited"):
        planning.save_order(
            company_id,
            order_values(factory, "LOW", 10),
            low.id,
            db.session.get(ProductionOrder, low.id).version,
        )


def test_late_orders_what_if_and_cancel(factory):
    company_id = factory.company_id
    order = planning.save_order(
        company_id, order_values(factory, quantity=4000, days=3, lines=1), today=MONDAY
    )
    # 20,000 SAM min on one 4,800-a-day line takes 5 days, so it misses a 3-day window.
    assert order.planned_finish_on > order.ex_factory_on
    before = db.session.scalar(select(db.func.count()).select_from(CapacityBooking))
    plans, _, _ = planning.simulate(company_id, MONDAY, {order.id: {"sewing_lines": 2}})
    assert plans[order.id].finish < order.planned_finish_on
    assert db.session.scalar(select(db.func.count()).select_from(CapacityBooking)) == before
    planning.transition(company_id, order.id, "cancel", order.version, today=MONDAY)
    assert not db.session.scalar(
        select(CapacityBooking.id).where(CapacityBooking.production_order_id == order.id)
    )


def test_orders_need_a_published_bulletin_and_fabric(factory):
    company_id = factory.company_id
    bare = service.save(company_id, "styles", {"code": "NEW", "name": "New", "product_type": "tee"})
    with pytest.raises(DomainError, match="bulletin"):
        planning.save_order(
            company_id, {**order_values(factory), "style_id": bare.id}, today=MONDAY
        )


# ---------- Screens ----------


def test_planning_screens_and_order_actions(factory, client):
    company_id = factory.company_id
    order = planning.save_order(company_id, order_values(factory, days=30), today=date.today())
    login(client)
    base = f"/companies/{company_id}/factory"
    board = client.get(f"{base}/planning")
    assert board.status_code == 200 and "Load by department" in board.text
    assert client.get(f"{base}/planning/sewing").status_code == 200
    assert client.get(f"{base}/planning/nonsense").status_code == 404
    assert "PO-1" in client.get(f"{base}/orders").text
    page = client.get(f"{base}/orders/{order.id}?lines=1&priority=2")
    assert (
        page.status_code == 200
        and "Plan by stage" in page.text
        and "Apply this change" in page.text
    )
    token = csrf(page)
    response = client.post(
        f"{base}/orders/{order.id}/apply",
        data={"csrf_token": token, "version": str(order.version), "lines": "1", "priority": "2"},
    )
    assert response.status_code == 303
    db.session.expire_all()
    order = db.session.get(ProductionOrder, order.id)
    assert (order.sewing_lines, order.priority) == (1, 2)
    response = client.post(
        f"{base}/orders/{order.id}/release",
        data={"csrf_token": token, "version": str(order.version)},
    )
    assert response.status_code == 303
    db.session.expire_all()
    assert db.session.get(ProductionOrder, order.id).status == "released"
    form = client.get(f"{base}/orders/new")
    assert "TEE — Tee" in form.text
    response = client.post(
        f"{base}/orders/new",
        data={
            "csrf_token": csrf(form),
            "version": "0",
            "reference": "PO-2",
            "style_id": str(factory.style.id),
            "quantity": "500",
            "colour": "White",
            "ex_factory_on": (date.today() + timedelta(days=20)).isoformat(),
            "priority": "3",
            "sewing_lines": "1",
            "prints_per_piece": "0",
        },
    )
    assert response.status_code == 303, response.text
    assert (
        db.session.scalar(select(ProductionOrder.status).where(ProductionOrder.reference == "PO-2"))
        == "planned"
    )


def test_read_only_members_cannot_replan(app, records, client):
    company_id = records["companies"]["aurora"]
    grant(company_id, codes=("factory.read",), role_code="auditor")
    login(client, "auditor@aurora.test")
    board = client.get(f"/companies/{company_id}/factory/planning")
    assert board.status_code == 200 and "Replan all" not in board.text
    response = client.post(
        f"/companies/{company_id}/factory/planning/replan",
        data={"csrf_token": csrf(board), "version": "1"},
    )
    assert response.status_code == 403
