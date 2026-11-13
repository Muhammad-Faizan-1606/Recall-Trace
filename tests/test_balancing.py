"""Factory Suite step 4: line balancing on a line small enough to check by hand.

Bulletin (SAM, minutes per piece), one 8-hour shift with no breaks = 480 minutes, 100%:

    10 A  overlock    1.0
    20 B  overlock    0.5
    30 C  lockstitch  0.6
    40 D  manual      0.4
    50 E  overlock    1.5          garment SAM 4.0 (overlock 3.0, lockstitch 0.6, manual 0.4)

Six operators: one per machine type, then each extra operator goes to the busiest type,
so overlock 4 (0.75 each), lockstitch 1, manual 1. Overlock work divided evenly in
sequence order: [A 75%] [A 25% + B] [E 50%] [E 50%], all 0.75 min.

    pitch time         4.0 ÷ 6 = 0.667 min
    bottleneck         0.75 min
    balance efficiency 4.0 ÷ (6 × 0.75) = 88.9%
    output             480 ÷ 0.75 = 640 pieces a day (80 an hour)
    perfectly balanced 6 × 480 ÷ 4.0 = 720 pieces a day; 80 lost to imbalance
"""

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import csrf, login
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_factory import as_user, grant

from app.extensions import db
from app.models.factory import (
    BulletinOperation,
    LineBalance,
    LineStation,
    Machine,
    OperationBulletin,
    StationOperation,
)
from app.models.master import Site
from app.services import balancing
from app.services import factory as service
from app.services.balancing import Op, auto_layout, measure, operators_by_class, suggest
from app.services.business import DomainError

D = Decimal
OL, LS = uuid.uuid4(), uuid.uuid4()
NAMES = {OL: "Overlock", LS: "Lockstitch", None: "Manual work"}
OPS = [
    Op(uuid.uuid4(), seq, name, cls, NAMES[cls], D(sam))
    for seq, name, cls, sam in [
        (10, "A", OL, "1.0"),
        (20, "B", OL, "0.5"),
        (30, "C", LS, "0.6"),
        (40, "D", None, "0.4"),
        (50, "E", OL, "1.5"),
    ]
]


def work(station):
    return [(op.name, share) for op, share in station.work]


# ---------- Pure calculations ----------


def test_operators_follow_the_work_content():
    counts = operators_by_class(OPS, 6)
    assert counts == {OL: 4, LS: 1, None: 1}
    with pytest.raises(ValueError, match="At least 3 operators"):
        operators_by_class(OPS, 2)


def test_auto_layout_divides_each_machine_type_evenly_in_sequence():
    stations = auto_layout(OPS, 6)
    assert [work(s) for s in stations] == [
        [("A", D("0.7500"))],
        [("A", D("0.2500")), ("B", D(1))],
        [("C", D(1))],
        [("D", D(1))],
        [("E", D("0.5000"))],
        [("E", D("0.5000"))],
    ]
    assert [s.number for s in stations] == [1, 2, 3, 4, 5, 6]
    # Every operation is assigned exactly once in total.
    totals = {}
    for station in stations:
        for op, share in station.work:
            totals[op.name] = totals.get(op.name, 0) + share
    assert set(totals.values()) == {D(1)}


def test_measure_matches_the_hand_calculation():
    m = measure(OPS, auto_layout(OPS, 6), 480, 100)
    assert m.total_sam == D("4.0") and m.stations == 6
    assert round(m.pitch, 4) == D("0.6667")
    assert m.bottleneck == D("0.75")
    assert round(m.balance_efficiency, 1) == D("88.9")
    assert (m.per_day, m.per_hour) == (D(640), D(80))
    assert (m.balanced_per_day, m.lost_per_day) == (D(720), D(80))
    assert m.complete and not m.unassigned and not m.mixed
    # A shorter day and lower efficiency scale output proportionally.
    assert measure(OPS, auto_layout(OPS, 6), 240, 50).per_day == D(160)


def test_unassigned_and_mixed_work_is_reported():
    stations = auto_layout(OPS, 6)
    stations[3].work = []  # D no longer done anywhere
    stations[2].work.append((OPS[0], D("0.0001")))  # lockstitch station given overlock work
    m = measure(OPS, stations, 480, 100)
    assert [(op.name, missing) for op, missing in m.unassigned] == [("D", D(1))]
    assert m.mixed == [3] and not m.complete


def test_suggestions_move_whole_work_off_the_bottleneck():
    stations = auto_layout(OPS, 6)
    assert suggest(stations, 480, 100) == []  # already as even as the machine mix allows
    # Hand B to station 1: it becomes the bottleneck at 1.25 min.
    stations[1].work = [(OPS[0], D("0.25"))]
    stations[0].work.append((OPS[1], D(1)))
    best, extra = suggest(stations, 480, 100)
    assert (best.kind, best.op.name, best.from_number, best.to_number, best.percent) == (
        "move",
        "B",
        1,
        2,
        100,
    )
    assert best.bottleneck_after == D("0.75")
    assert best.gain_per_day == D(640) - D(480) / D("1.25")
    assert (extra.kind, extra.op.name, extra.to_number) == ("add", "A", None)


# ---------- Database: drafts, moves, publishing and history ----------


@pytest.fixture
def line(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    context = as_user(app)
    site = Site(
        organization_id=company_id, code="S", name="Stitching", address_text="x", country_code="PK"
    )
    db.session.add(site)
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
            "working_days": ["0", "1", "2", "3", "4", "5"],
        },
    )
    classes = {
        code: service.save(
            company_id,
            "machine-classes",
            {"code": code, "name": name, "department": "sewing", "capacity_basis": "sewing"},
        )
        for code, name in (("OL", "Overlock"), ("LS", "Lockstitch"))
    }
    center = service.save(
        company_id,
        "work-centers",
        {
            "code": "L1",
            "name": "Line 1",
            "department": "sewing",
            "site_id": site.id,
            "shift_pattern_id": pattern.id,
            "target_efficiency": D(100),
        },
    )
    # Three overlocks for four overlock stations; one of two lockstitch machines is down.
    for tag, code, status in [
        ("OL-1", "OL", "active"),
        ("OL-2", "OL", "active"),
        ("OL-3", "OL", "active"),
        ("LS-1", "LS", "maintenance"),
        ("LS-2", "LS", "active"),
    ]:
        db.session.add(
            Machine(
                organization_id=company_id,
                asset_tag=tag,
                make_model="x",
                machine_class_id=classes[code].id,
                work_center_id=center.id,
                rated_value=D(1),
                status=status,
            )
        )
    style = service.save(
        company_id, "styles", {"code": "TEE", "name": "Tee", "product_type": "tee"}
    )
    bulletin = OperationBulletin(organization_id=company_id, style_id=style.id, revision=1)
    db.session.add(bulletin)
    db.session.flush()
    for op in OPS:
        db.session.add(
            BulletinOperation(
                organization_id=company_id,
                bulletin_id=bulletin.id,
                sequence=op.sequence,
                name=op.name,
                machine_class_id=classes[{OL: "OL", LS: "LS"}[op.class_id]].id
                if op.class_id
                else None,
                basic_minutes=op.sam,
                allowance_factor=D(0),
                sam=op.sam,
            )
        )
    db.session.flush()
    bulletin.status = "published"
    bulletin.published_at = balancing.now()
    db.session.commit()
    yield SimpleNamespace(
        company_id=company_id, center=center, bulletin=bulletin, style=style, classes=classes
    )
    context.pop()


def view_of(line, balance_id):
    return balancing.layout(line.company_id, db.session.get(LineBalance, balance_id))


def test_create_lays_out_the_line_and_equips_stations(line):
    balance, short = balancing.create_balance(
        line.company_id, line.center.id, line.bulletin.id, 6, D(100)
    )
    assert short == {"Overlock": 1}
    view = view_of(line, balance.id)
    m = view.metrics
    assert (m.stations, m.per_day, view.minutes) == (6, D(640), D(480))
    tags = [s.machine.asset_tag if s.machine else None for s in view.stations]
    assert tags == ["OL-1", "OL-2", "LS-2", None, "OL-3", None]
    assert ("Overlock", 4, 3) in m.by_class and ("Lockstitch", 1, 1) in m.by_class
    with pytest.raises(DomainError, match="already has a draft"):
        balancing.create_balance(line.company_id, line.center.id, line.bulletin.id, 6, D(100))


def test_moves_respect_machine_types_versions_and_publishing_freezes(line):
    company_id = line.company_id
    balance, _ = balancing.create_balance(company_id, line.center.id, line.bulletin.id, 6, D(100))
    b_op = OPS[1]
    b_id = db.session.scalar(
        select(BulletinOperation.id).where(
            BulletinOperation.bulletin_id == line.bulletin.id, BulletinOperation.name == "B"
        )
    )
    version = db.session.get(LineBalance, balance.id).version
    balancing.move(company_id, balance.id, 2, b_id, 1, 100, version)
    view = view_of(line, balance.id)
    assert view.metrics.bottleneck == D("1.25") and view.metrics.per_day == D(384)
    assert [s.op.name for s in view.suggestions] == [b_op.name, "A"]
    with pytest.raises(DomainError, match="One operator works one kind of machine"):
        balancing.move(company_id, balance.id, 1, b_id, 3, 100, view.balance.version)
    with pytest.raises(DomainError, match="changed"):
        balancing.move(company_id, balance.id, 1, b_id, 2, 100, version)
    # Half of B to a new station placed right after station 1.
    balancing.move(company_id, balance.id, 1, b_id, "new", 50, view.balance.version)
    view = view_of(line, balance.id)
    assert view.metrics.stations == 7
    assert [(op.name, share) for op, share in view.stations[1].work] == [("B", D("0.5000"))]

    balancing.publish(company_id, balance.id, view.balance.version)
    assert balancing.current_balances(company_id)[line.center.id].id == balance.id
    with pytest.raises(DomainError, match="frozen"):
        balancing.move(
            company_id, balance.id, 1, b_id, 2, 100, view_of(line, balance.id).balance.version
        )
    # The database itself refuses changes to a published balance's stations.
    with pytest.raises(DBAPIError, match="immutable"):
        db.session.execute(
            text("UPDATE line_stations SET machine_id = NULL WHERE balance_id = :b"),
            {"b": balance.id},
        )
    db.session.rollback()

    draft = balancing.start_revision(company_id, balance.id)
    assert (draft.revision, draft.status) == (2, "draft")
    assert view_of(line, draft.id).metrics.stations == 7
    assert balancing.start_revision(company_id, balance.id).id == draft.id
    line_id = balancing.discard(company_id, draft.id, db.session.get(LineBalance, draft.id).version)
    assert line_id == line.center.id
    assert db.session.get(LineBalance, draft.id) is None
    assert balancing.current_balances(company_id)[line.center.id].id == balance.id


def test_publishing_needs_complete_work_and_valid_inputs(line):
    company_id = line.company_id
    with pytest.raises(DomainError, match="At least 3 operators"):
        balancing.create_balance(company_id, line.center.id, line.bulletin.id, 2, D(100))
    with pytest.raises(DomainError, match="Efficiency"):
        balancing.create_balance(company_id, line.center.id, line.bulletin.id, 6, D(0))
    draft_bulletin = OperationBulletin(
        organization_id=company_id, style_id=line.style.id, revision=2
    )
    db.session.add(draft_bulletin)
    db.session.commit()
    with pytest.raises(DomainError, match="published bulletin"):
        balancing.create_balance(company_id, line.center.id, draft_bulletin.id, 6, D(100))
    balance, _ = balancing.create_balance(company_id, line.center.id, line.bulletin.id, 6, D(100))
    first = db.session.scalar(
        select(StationOperation).where(StationOperation.balance_id == balance.id).limit(1)
    )
    db.session.delete(first)
    db.session.commit()
    with pytest.raises(DomainError, match="fully assigned"):
        balancing.publish(company_id, balance.id, db.session.get(LineBalance, balance.id).version)
    assert db.session.get(LineBalance, balance.id).status == "draft"


# ---------- Screens ----------


def test_balancing_screens_and_actions(line, client):
    company_id = line.company_id
    login(client)
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/lines/{line.center.id}")
    assert page.status_code == 200 and "Lay out the line" in page.text
    response = client.post(
        f"{base}/lines/{line.center.id}/balances",
        data={
            "csrf_token": csrf(page),
            "version": "0",
            "bulletin_id": str(line.bulletin.id),
            "operators": "6",
            "target_efficiency": "100",
            "note": "",
        },
    )
    assert response.status_code == 303, response.text
    balance = db.session.scalar(
        select(LineBalance).where(LineBalance.work_center_id == line.center.id)
    )
    screen = client.get(response.headers["Location"])
    assert screen.status_code == 200
    assert "88.9%" in screen.text and "640" in screen.text and "Publish to the line" in screen.text
    b_id = db.session.scalar(
        select(BulletinOperation.id).where(
            BulletinOperation.bulletin_id == line.bulletin.id, BulletinOperation.name == "B"
        )
    )
    response = client.post(
        f"{base}/balances/{balance.id}/move",
        data={
            "csrf_token": csrf(screen),
            "version": str(balance.version),
            "work": f"2:{b_id}",
            "to_station": "1",
            "percent": "100",
        },
    )
    assert response.status_code == 303
    screen = client.get(f"{base}/balances/{balance.id}")
    assert "bottleneck" in screen.text and "Suggested" in screen.text
    db.session.expire_all()
    version = db.session.get(LineBalance, balance.id).version
    response = client.post(
        f"{base}/balances/{balance.id}/publish",
        data={"csrf_token": csrf(screen), "version": str(version)},
    )
    assert response.status_code == 303
    db.session.expire_all()
    assert db.session.get(LineBalance, balance.id).status == "published"
    listing = client.get(f"{base}/lines")
    assert listing.status_code == 200 and "TEE" in listing.text
    assert client.get(f"{base}/lines/{uuid.uuid4()}").status_code == 404
    assert (
        len(
            db.session.scalars(
                select(LineStation).where(LineStation.balance_id == balance.id)
            ).all()
        )
        == 6
    )


def test_read_only_members_see_but_cannot_change_balances(line, client):
    company_id = line.company_id
    balance, _ = balancing.create_balance(company_id, line.center.id, line.bulletin.id, 6, D(100))
    grant(company_id, codes=("factory.read",), role_code="auditor")
    login(client, "auditor@aurora.test")
    base = f"/companies/{company_id}/factory"
    screen = client.get(f"{base}/balances/{balance.id}")
    assert screen.status_code == 200 and "Move work" not in screen.text
    assert "Lay out the line" not in client.get(f"{base}/lines/{line.center.id}").text
    response = client.post(
        f"{base}/balances/{balance.id}/publish",
        data={"csrf_token": csrf(screen), "version": str(balance.version)},
    )
    assert response.status_code == 403
