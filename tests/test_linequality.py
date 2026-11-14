"""Factory Suite step 8a: in-line and end-line checks, DHU, defects by operation, alerts.

Worked example: end-line, 30 pieces checked, 3 pieces with defects, defects 2 skip stitch
(on operation B) + 2 open seam = 4 → DHU 13.3, defect rate 10%.
"""

from decimal import Decimal

import pytest
from conftest import csrf, login
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_balancing import line  # noqa: F401
from test_factory import grant
from test_shopfloor import TODAY, floor  # noqa: F401

from app.extensions import db
from app.models.factory import BulletinOperation, FactoryAlert, LineQualityCheck
from app.services import alerts, linequality
from app.services.business import DomainError


def check_values(floor, **extra):  # noqa: F811
    b_op = db.session.scalar(
        select(BulletinOperation).where(
            BulletinOperation.bulletin_id == floor.bulletin.id, BulletinOperation.name == "B"
        )
    )
    values = {
        "day": TODAY.isoformat(),
        "hour": 2,
        "stage": "endline",
        "production_order_id": str(floor.order.id),
        "pieces_checked": 30,
        "defective_pieces": 3,
        "defect_code_1": "skip_stitch",
        "operation_1": str(b_op.id),
        "defect_count_1": 2,
        "defect_code_2": "open_seam",
        "defect_count_2": 2,
    }
    values.update(extra)
    return values, b_op


def test_check_dhu_and_defects_by_operation(floor):  # noqa: F811
    company_id = floor.company_id
    values, b_op = check_values(floor)
    check = linequality.record_check(company_id, floor.center.id, values, today=TODAY)
    assert (check.pieces_checked, check.defective_pieces, check.defects) == (30, 3, 4)
    day = linequality.line_day(company_id, floor.center.id, TODAY)
    assert round(day.dhu("endline"), 1) == Decimal("13.3")
    assert day.defect_rate("endline") == Decimal(10)
    assert day.dhu("inline") is None
    assert day.by_code == {"skip_stitch": 2, "open_seam": 2}
    assert day.by_operation == {b_op.id: 2}
    fixed = linequality.correct_check(
        company_id,
        check.id,
        {
            **values,
            "defective_pieces": 2,
            "defect_count_2": 0,
            "defect_code_2": "",
            "note": "Recount",
        },
        today=TODAY,
    )
    assert fixed.corrects_id == check.id
    day = linequality.line_day(company_id, floor.center.id, TODAY)
    assert day.defects["endline"] == 2 and len(day.checks) == 1
    with pytest.raises(DBAPIError, match="immutable"):
        db.session.execute(
            text("UPDATE line_quality_checks SET defects = 0 WHERE id = :i"), {"i": check.id}
        )
    db.session.rollback()
    with pytest.raises(DBAPIError, match="immutable"):
        db.session.execute(
            text("DELETE FROM line_check_defects WHERE check_id = :i"), {"i": check.id}
        )
    db.session.rollback()


def test_check_validation(floor):  # noqa: F811
    company_id = floor.company_id
    values, b_op = check_values(floor)
    with pytest.raises(DomainError, match="at least one defect"):
        linequality.record_check(
            company_id, floor.center.id, {**values, "defective_pieces": 5}, today=TODAY
        )
    with pytest.raises(DomainError, match="which defects"):
        linequality.record_check(
            company_id,
            floor.center.id,
            {**values, "defect_code_1": "", "defect_code_2": ""},
            today=TODAY,
        )
    with pytest.raises(DomainError, match="once per operation"):
        linequality.record_check(
            company_id,
            floor.center.id,
            {**values, "defect_code_2": "skip_stitch", "operation_2": str(b_op.id)},
            today=TODAY,
        )
    with pytest.raises(DomainError, match="listed defect"):
        linequality.record_check(
            company_id, floor.center.id, {**values, "defect_code_1": "dirt"}, today=TODAY
        )
    with pytest.raises(DomainError, match="released"):
        linequality.record_check(
            company_id,
            floor.center.id,
            {**values, "production_order_id": str(floor.planned.id)},
            today=TODAY,
        )
    assert db.session.scalar(select(LineQualityCheck.id)) is None


def test_high_end_line_dhu_raises_an_alert(floor):  # noqa: F811
    company_id = floor.company_id
    for hour in (1, 2):
        values, _ = check_values(floor, hour=hour)
        linequality.record_check(company_id, floor.center.id, values, today=TODAY)
    alerts.scan(company_id, day=TODAY)
    alert = db.session.scalar(select(FactoryAlert).where(FactoryAlert.kind == "quality_dhu"))
    assert alert.title == "L1 end-line DHU 13.3, above 7.5"
    assert alert.severity == "warning" and "most often skip stitch" in alert.detail


def test_quality_screens_and_permissions(floor, client):  # noqa: F811
    company_id = floor.company_id
    login(client)
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/floor/{floor.center.id}?day={TODAY.isoformat()}")
    assert page.status_code == 200 and "Record a quality check" in page.text
    values, _ = check_values(floor)
    response = client.post(
        f"{base}/floor/{floor.center.id}/quality",
        data={"csrf_token": csrf(page), "version": "0", **values},
    )
    assert response.status_code == 303
    check = db.session.scalar(select(LineQualityCheck))
    entry = client.get(f"{base}/floor/quality/{check.id}")
    assert entry.status_code == 200 and "Correct this check" in entry.text
    assert "End-line DHU" in client.get(f"{base}/floor").text

    grant(company_id, codes=("factory.read",), role_code="auditor")
    client.post("/logout", data={"csrf_token": csrf(page)})
    login(client, "auditor@aurora.test")
    page = client.get(f"{base}/floor/{floor.center.id}")
    assert "Record a quality check" not in page.text
    response = client.post(
        f"{base}/floor/{floor.center.id}/quality",
        data={"csrf_token": csrf(page), "version": "0", **values},
    )
    assert response.status_code == 403
