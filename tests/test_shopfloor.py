"""Factory Suite step 5: hourly output, downtime, efficiency, batch cards and bundle tickets.

Efficiency worked example (garment SAM 4.0, 6 operators, full hours):

    hour 1: 60 good → 240 earned of 360 clock minutes
    hour 2: 50 good → 200 earned of 360
    power cut 20 min × 6 operators = 120 off-standard minutes (left out)
    needle change 10 min × 1 operator counts against the line (stays in)

    efficiency = 440 ÷ (720 − 120) = 73.3%; restating hour 2 as 70 good → 520 ÷ 600 = 86.7%
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import csrf, login
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_balancing import line  # noqa: F401  (fixture: one sewing line with a bulletin)
from test_factory import grant

from app.extensions import db
from app.models.factory import (
    CutBundle,
    DowntimeReason,
    KnitRoll,
    Machine,
    OutputLog,
    ProductionOrder,
)
from app.services import factory as service
from app.services import shopfloor
from app.services.business import DomainError

D = Decimal
TODAY = date(2026, 11, 13)


def log(hour, good, operators=6, minutes=60, corrects=None, at=0, sam="4.0"):
    return SimpleNamespace(
        id=object(),
        corrects_id=corrects,
        hour=hour,
        good_pieces=good,
        rejects=1,
        operators=operators,
        minutes=minutes,
        sam=D(sam),
        recorded_at=at,
    )


def stop(minutes, operators, reason_id, corrects=None, at=0):
    return SimpleNamespace(
        id=object(),
        corrects_id=corrects,
        hour=2,
        minutes=minutes,
        operators_affected=operators,
        reason_id=reason_id,
        recorded_at=at,
    )


def test_efficiency_leaves_out_approved_stops_and_uses_the_newest_restatement():
    reasons = {
        "PWR": SimpleNamespace(efficiency_rule="off_standard"),
        "NDL": SimpleNamespace(efficiency_rule="operator"),
    }
    first, second = log(1, 60), log(2, 50)
    power, needle = stop(20, 6, "PWR"), stop(10, 1, "NDL")
    day = shopfloor.summarize([first, second], [power, needle], reasons)
    assert (day.good, day.rejects, day.earned, day.clock) == (110, 2, D(440), D(720))
    assert (day.off_standard, day.lost) == (D(120), D(10))
    assert round(day.efficiency, 1) == D("73.3")
    assert day.downtime_minutes == 30

    fixed = log(2, 70, corrects=second.id, at=1)
    withdrawn = stop(0, 1, "NDL", corrects=needle.id, at=1)
    day = shopfloor.summarize([first, second, fixed], [power, needle, withdrawn], reasons)
    assert day.good == 130 and round(day.efficiency, 1) == D("86.7")
    assert [row for _, row, _ in day.hours][1] is fixed
    assert day.downtime_minutes == 20 and day.lost == 0


# ---------- Database ----------


@pytest.fixture
def floor(line):  # noqa: F811
    company_id = line.company_id
    grant(company_id, codes=("factory.record",))
    order = ProductionOrder(
        organization_id=company_id,
        reference="PO-9",
        style_id=line.style.id,
        bulletin_id=line.bulletin.id,
        quantity=300,
        colour="Black",
        ex_factory_on=TODAY + timedelta(days=20),
        status="released",
    )
    planned = ProductionOrder(
        organization_id=company_id,
        reference="PO-10",
        style_id=line.style.id,
        bulletin_id=line.bulletin.id,
        quantity=100,
        colour="White",
        ex_factory_on=TODAY + timedelta(days=30),
        status="planned",
    )
    db.session.add_all([order, planned])
    db.session.commit()
    reasons = {
        code: service.save(
            company_id,
            "downtime-reasons",
            {"code": code, "name": code, "category": category, "efficiency_rule": rule},
        )
        for code, category, rule in (
            ("PWR", "power", "off_standard"),
            ("NDL", "needle_bobbin", "operator"),
        )
    }
    line.order, line.planned, line.reasons = order, planned, reasons
    return line


def hour_values(order, hour=1, good=60, **extra):
    return {
        "day": TODAY.isoformat(),
        "hour": hour,
        "production_order_id": str(order.id),
        "good_pieces": good,
        "rejects": 1,
        "operators": 6,
        "minutes": 60,
        **extra,
    }


def test_output_rules_corrections_and_immutability(floor):
    company_id, line_id = floor.company_id, floor.center.id
    with pytest.raises(DomainError, match="released"):
        shopfloor.record_output(company_id, line_id, hour_values(floor.planned), today=TODAY)
    with pytest.raises(DomainError, match="future"):
        shopfloor.record_output(
            company_id,
            line_id,
            hour_values(floor.order, day=(TODAY + timedelta(days=1)).isoformat()),
            today=TODAY,
        )
    with pytest.raises(DomainError, match="7 days"):
        shopfloor.record_output(
            company_id,
            line_id,
            hour_values(floor.order, day=(TODAY - timedelta(days=8)).isoformat()),
            today=TODAY,
        )
    with pytest.raises(DomainError, match="operator"):
        shopfloor.record_output(
            company_id, line_id, hour_values(floor.order, operators=0), today=TODAY
        )
    first = shopfloor.record_output(company_id, line_id, hour_values(floor.order), today=TODAY)
    second = shopfloor.record_output(
        company_id, line_id, hour_values(floor.order, hour=2, good=50), today=TODAY
    )
    assert first.sam == D("4.0")
    with pytest.raises(DomainError, match="already recorded"):
        shopfloor.record_output(company_id, line_id, hour_values(floor.order), today=TODAY)
    with pytest.raises(DomainError, match="Nothing changed"):
        shopfloor.correct_output(
            company_id, second.id, hour_values(floor.order, hour=2, good=50, note="x"), today=TODAY
        )
    with pytest.raises(DomainError, match="why"):
        shopfloor.correct_output(
            company_id, second.id, hour_values(floor.order, hour=2, good=70), today=TODAY
        )
    fixed = shopfloor.correct_output(
        company_id,
        second.id,
        hour_values(floor.order, hour=2, good=70, note="Bundle counted late"),
        today=TODAY,
    )
    assert fixed.corrects_id == second.id and fixed.hour == 2
    # Correcting the correction still points at the original.
    again = shopfloor.correct_output(
        company_id,
        fixed.id,
        hour_values(floor.order, hour=2, good=68, note="Recount"),
        today=TODAY,
    )
    assert again.corrects_id == second.id
    day = shopfloor.line_day(company_id, line_id, TODAY)
    assert day.good == 128 and len(day.hours) == 2
    assert [r.good_pieces for r in shopfloor.history(company_id, OutputLog, second.id)] == [
        50,
        70,
        68,
    ]
    with pytest.raises(DBAPIError, match="immutable"):
        db.session.execute(
            text("UPDATE output_logs SET good_pieces = 0 WHERE id = :i"), {"i": first.id}
        )
    db.session.rollback()
    with pytest.raises(DBAPIError, match="immutable"):
        db.session.execute(text("DELETE FROM output_logs WHERE id = :i"), {"i": first.id})
    db.session.rollback()


def test_downtime_counts_and_withdrawals(floor):
    company_id, line_id = floor.company_id, floor.center.id
    shopfloor.record_output(company_id, line_id, hour_values(floor.order), today=TODAY)
    shopfloor.record_output(
        company_id, line_id, hour_values(floor.order, hour=2, good=50), today=TODAY
    )
    base = {"day": TODAY.isoformat(), "hour": 2}
    power = shopfloor.record_downtime(
        company_id,
        line_id,
        {**base, "reason_id": str(floor.reasons["PWR"].id), "minutes": 20, "operators_affected": 6},
        today=TODAY,
    )
    machine = db.session.scalar(select(Machine).where(Machine.asset_tag == "OL-1"))
    needle = shopfloor.record_downtime(
        company_id,
        line_id,
        {
            **base,
            "reason_id": str(floor.reasons["NDL"].id),
            "machine_id": str(machine.id),
            "minutes": 10,
            "operators_affected": 1,
        },
        today=TODAY,
    )
    day = shopfloor.line_day(company_id, line_id, TODAY)
    assert round(day.efficiency, 1) == D("73.3") and day.downtime_minutes == 30
    with pytest.raises(DomainError, match="why"):
        shopfloor.correct_downtime(
            company_id,
            needle.id,
            {
                **base,
                "reason_id": str(floor.reasons["NDL"].id),
                "minutes": 0,
                "operators_affected": 1,
            },
            today=TODAY,
        )
    shopfloor.correct_downtime(
        company_id,
        needle.id,
        {
            **base,
            "reason_id": str(floor.reasons["NDL"].id),
            "minutes": 0,
            "operators_affected": 1,
            "note": "Logged on the wrong line",
        },
        today=TODAY,
    )
    day = shopfloor.line_day(company_id, line_id, TODAY)
    assert day.downtime_minutes == 20 and len(day.downtime) == 1 and power
    with pytest.raises(DomainError, match="At least one operator"):
        shopfloor.record_downtime(
            company_id,
            line_id,
            {
                **base,
                "reason_id": str(floor.reasons["PWR"].id),
                "minutes": 5,
                "operators_affected": 0,
            },
            today=TODAY,
        )


@pytest.fixture
def mill(floor):
    """Add a knitting frame and a 100 kg dyeing vessel to the line's site."""
    company_id = floor.company_id
    pattern_id = floor.center.shift_pattern_id
    site_id = floor.center.site_id
    knit_class = service.save(
        company_id,
        "machine-classes",
        {
            "code": "KN",
            "name": "Knit",
            "department": "knitting",
            "capacity_basis": "knit",
            "feeders_per_course": 1,
            "courses_per_cm": D(16),
            "fabric_width_m": D("1.8"),
            "fabric_gsm": D(160),
        },
    )
    jet_class = service.save(
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
    centers = {
        department: service.save(
            company_id,
            "work-centers",
            {
                "code": department[:4].upper(),
                "name": department,
                "department": department,
                "site_id": site_id,
                "shift_pattern_id": pattern_id,
                "target_efficiency": D(80),
            },
        )
        for department in ("knitting", "dyeing")
    }
    knitter = Machine(
        organization_id=company_id,
        asset_tag="KN-1",
        make_model="x",
        machine_class_id=knit_class.id,
        work_center_id=centers["knitting"].id,
        rated_value=D(30),
        feeders=96,
    )
    vessel = Machine(
        organization_id=company_id,
        asset_tag="JET-1",
        make_model="x",
        machine_class_id=jet_class.id,
        work_center_id=centers["dyeing"].id,
        rated_value=D(100),
    )
    db.session.add_all([knitter, vessel])
    db.session.commit()
    floor.knitter, floor.vessel = knitter, vessel
    return floor


def test_rolls_dye_batches_and_re_dye(mill):
    company_id = mill.company_id
    rolls = [
        shopfloor.record_roll(
            company_id,
            {
                "roll_number": f"R-{n}",
                "machine_id": str(mill.knitter.id),
                "kg": "40",
                "grade": "C" if n == 4 else "A",
                "knitted_on": TODAY.isoformat(),
            },
            today=TODAY,
        )
        for n in range(1, 5)
    ]
    with pytest.raises(DomainError, match="knitting machine"):
        shopfloor.record_roll(
            company_id,
            {
                "roll_number": "R-X",
                "machine_id": str(mill.vessel.id),
                "kg": "1",
                "knitted_on": TODAY,
            },
            today=TODAY,
        )
    assert {r.roll_number for r in shopfloor.loadable_rolls(company_id)} == {"R-1", "R-2", "R-3"}
    batch_values = {
        "batch_number": "DB-1",
        "machine_id": str(mill.vessel.id),
        "colour": "Black",
        "recipe_reference": "RCP-1",
    }
    with pytest.raises(DomainError, match="more than the vessel"):
        shopfloor.load_batch(
            company_id, {**batch_values, "roll_ids": [str(r.id) for r in rolls[:3]]}
        )
    with pytest.raises(DomainError, match="graded C"):
        shopfloor.load_batch(company_id, {**batch_values, "roll_ids": [str(rolls[3].id)]})
    batch, total, capacity = shopfloor.load_batch(
        company_id, {**batch_values, "roll_ids": [str(r.id) for r in rolls[:2]]}
    )
    assert (total, capacity) == (D(80), D(100))
    assert [r.roll_number for r in shopfloor.loadable_rolls(company_id)] == ["R-3"]
    with pytest.raises(DomainError, match="cannot do that"):
        shopfloor.batch_step(company_id, batch.id, "passed", batch.version)
    batch = shopfloor.batch_step(company_id, batch.id, "start", batch.version)
    with pytest.raises(DomainError, match="changed"):
        shopfloor.batch_step(company_id, batch.id, "re_dye", batch.version - 1)
    batch = shopfloor.batch_step(company_id, batch.id, "re_dye", batch.version)
    assert batch.finished_at is not None
    # Rolls of a batch needing re-dye can go into a new batch.
    assert len(shopfloor.loadable_rolls(company_id)) == 3
    again, _, _ = shopfloor.load_batch(
        company_id,
        {**batch_values, "batch_number": "DB-2", "roll_ids": [str(r.id) for r in rolls[:2]]},
    )
    assert {
        r.dye_batch_id for r in db.session.scalars(select(KnitRoll).where(KnitRoll.grade == "A"))
    } == {again.id, None}


def test_bundles_are_numbered_capped_and_move_to_the_line(mill):
    company_id = mill.company_id
    values = {
        "production_order_id": str(mill.order.id),
        "lay_number": "L-1",
        "bundle_size": 30,
        "sizes": "s:70, M:90",
    }
    assert shopfloor.parse_sizes("s:70, M:90") == [("S", 70), ("M", 90)]
    with pytest.raises(DomainError, match="once"):
        shopfloor.parse_sizes("S:1, s:2")
    bundles = shopfloor.cut_bundles(company_id, values)
    assert [(b.bundle_number, b.size, b.pieces) for b in bundles] == [
        ("PO-9-0001", "S", 30),
        ("PO-9-0002", "S", 30),
        ("PO-9-0003", "S", 10),
        ("PO-9-0004", "M", 30),
        ("PO-9-0005", "M", 30),
        ("PO-9-0006", "M", 30),
    ]
    with pytest.raises(DomainError, match="5% cutting allowance"):
        shopfloor.cut_bundles(company_id, {**values, "sizes": "L:160"})
    more = shopfloor.cut_bundles(company_id, {**values, "lay_number": "L-2", "sizes": "L:155"})
    assert more[0].bundle_number == "PO-9-0007"
    with pytest.raises(DomainError, match="released"):
        shopfloor.cut_bundles(company_id, {**values, "production_order_id": str(mill.planned.id)})
    bundle = shopfloor.find_bundle(company_id, " po-9-0001 ")
    with pytest.raises(DomainError, match="Only bundles on a line"):
        shopfloor.bundle_step(company_id, bundle.id, "sewn", bundle.version)
    bundle = shopfloor.bundle_step(company_id, bundle.id, "issue", bundle.version, mill.center.id)
    assert bundle.status == "issued" and bundle.issued_line_id == mill.center.id
    bundle = shopfloor.bundle_step(company_id, bundle.id, "sewn", bundle.version)
    assert bundle.status == "sewn" and bundle.sewn_at is not None


# ---------- Screens and permissions ----------


def test_floor_screens_record_and_print(mill, client):
    company_id = mill.company_id
    login(client)
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/floor/{mill.center.id}")
    assert page.status_code == 200 and "Record an hour" in page.text
    response = client.post(
        f"{base}/floor/{mill.center.id}/output",
        data={
            "csrf_token": csrf(page),
            "version": "0",
            **hour_values(mill.order, day=date.today().isoformat()),
        },
    )
    assert response.status_code == 303
    page = client.get(f"{base}/floor/{mill.center.id}")
    assert "Hour 1" in page.text and "Correct" in page.text
    floor_page = client.get(f"{base}/floor")
    assert floor_page.status_code == 200 and "Line 1" in floor_page.text
    shopfloor.cut_bundles(
        company_id,
        {
            "production_order_id": str(mill.order.id),
            "lay_number": "L-1",
            "bundle_size": 50,
            "sizes": "M:100",
        },
    )
    tickets = client.get(f"{base}/bundles/tickets?order={mill.order.id}")
    assert tickets.status_code == 200 and tickets.text.count('class="qr"') == 2
    found = client.get(f"{base}/bundles?number=PO-9-0002")
    assert found.status_code == 303
    bundle_page = client.get(found.headers["Location"])
    assert "Issue bundle" in bundle_page.text and "<svg" in bundle_page.text
    for path in ("/rolls", "/dye-batches", "/bundles", "/setup", "/downtime-reasons"):
        assert client.get(base + path).status_code == 200, path


def test_recording_needs_the_record_permission(mill, client):
    company_id = mill.company_id
    grant(company_id, codes=("factory.read",), role_code="auditor")
    login(client, "auditor@aurora.test")
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/floor/{mill.center.id}")
    assert page.status_code == 200 and "Record an hour" not in page.text
    response = client.post(
        f"{base}/floor/{mill.center.id}/output",
        data={"csrf_token": csrf(page), "version": "0", **hour_values(mill.order)},
    )
    assert response.status_code == 403
    assert db.session.scalar(select(OutputLog.id)) is None
    assert db.session.scalar(select(CutBundle.id)) is None
    assert db.session.scalar(select(DowntimeReason.id).where(DowntimeReason.code == "PWR"))
