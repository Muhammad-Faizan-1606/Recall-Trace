"""Factory Suite step 2: styles, fabric specs, operation bulletins and SAM."""

from decimal import Decimal

import pytest
from conftest import csrf, login
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_factory import as_user, grant

from app.extensions import db
from app.models.factory import BulletinOperation, MachineClass, OperationBulletin, Style
from app.models.master import Partner, PartnerRoleAssignment
from app.services import engineering
from app.services import factory as service
from app.services.business import DomainError

D = Decimal


def sewing_classes(company_id):
    rows = {}
    for code, name in (("SEW-OL", "Overlock station"), ("SEW-FL", "Flatlock station")):
        rows[code] = service.save(
            company_id,
            "machine-classes",
            {
                "code": code,
                "name": name,
                "department": "sewing",
                "capacity_basis": "sewing",
            },
        )
    return rows


def a_style(company_id, code="TEE-1"):
    return service.save(
        company_id,
        "styles",
        {
            "code": code,
            "name": "Tee",
            "product_type": "tee",
            "season": "SS27",
        },
    )


# ---------- Pure arithmetic ----------


def test_operation_sam_rounds_half_up_to_four_places():
    assert engineering.operation_sam(D("0.35"), D("0.25")) == D("0.4375")
    assert engineering.operation_sam(D("0.33333"), D("0.25")) == D("0.4167")


def test_summary_targets_pitch_and_station_split():
    ops = [
        (
            type("Op", (), {"basic_minutes": D("0.8"), "sam": D("1.0")})(),
            type("C", (), {"name": "Overlock"})(),
        ),
        (
            type("Op", (), {"basic_minutes": D("2.4"), "sam": D("3.0")})(),
            type("C", (), {"name": "Flatlock"})(),
        ),
        (type("Op", (), {"basic_minutes": D("0.8"), "sam": D("1.0")})(), None),
    ]
    summary = engineering.summarize(ops)
    assert summary.sam == D(5) and summary.operations == 3
    # Blueprint 5.4: 50 × 480 × 70% ÷ 20 = 840; here 10 × 480 × 70% ÷ 5 = 672.
    assert summary.target(10, 480, 70) == D(672)
    assert summary.pitch(10) == D("0.5")
    stations = summary.stations(10)
    assert sum(count for *_, count in stations) == 10
    assert dict((name, count) for name, _, count in stations)["Flatlock"] == 6


# ---------- Service rules ----------


def test_buyer_must_be_a_customer(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    context = as_user(app)
    try:
        partner = Partner(organization_id=company_id, code="SUP", name="Supplier only")
        db.session.add(partner)
        db.session.commit()
        with pytest.raises(DomainError, match="customer"):
            service.save(
                company_id,
                "styles",
                {
                    "code": "S",
                    "name": "S",
                    "product_type": "tee",
                    "buyer_id": partner.id,
                },
            )
        db.session.add(
            PartnerRoleAssignment(
                organization_id=company_id, partner_id=partner.id, role_code="customer"
            )
        )
        db.session.commit()
        style = service.save(
            company_id,
            "styles",
            {
                "code": "S",
                "name": "S",
                "product_type": "tee",
                "buyer_id": partner.id,
            },
        )
        assert style.buyer_id == partner.id
    finally:
        context.pop()


def test_revisions_operations_publish_and_freeze(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    context = as_user(app)
    try:
        classes = sewing_classes(company_id)
        style = a_style(company_id)
        draft = engineering.start_revision(company_id, style.id)
        assert (draft.revision, draft.status) == (1, "draft")
        assert engineering.start_revision(company_id, style.id).id == draft.id
        operation = engineering.save_operation(
            company_id,
            draft.id,
            {
                "sequence": 10,
                "name": "Shoulder join",
                "machine_class_id": str(classes["SEW-OL"].id),
                "basic_minutes": "0.35",
                "allowance_factor": "",
            },
        )
        assert operation.sam == D("0.4375") and operation.allowance_factor == D("0.250")
        manual = engineering.save_operation(
            company_id,
            draft.id,
            {
                "sequence": 20,
                "name": "Fold",
                "machine_class_id": "",
                "basic_minutes": "0.4",
                "allowance_factor": "20",
            },
        )
        assert manual.machine_class_id is None and manual.sam == D("0.48")
        with pytest.raises(DomainError, match="sewing"):
            cutter = service.save(
                company_id,
                "machine-classes",
                {
                    "code": "CUT",
                    "name": "Cutter",
                    "department": "cutting",
                    "capacity_basis": "rate",
                    "output_unit": "panels",
                },
            )
            engineering.save_operation(
                company_id,
                draft.id,
                {
                    "sequence": 30,
                    "name": "x",
                    "machine_class_id": str(cutter.id),
                    "basic_minutes": "1",
                },
            )
        published = engineering.publish(company_id, draft.id, draft.version)
        assert published.status == "published" and published.published_at
        with pytest.raises(DomainError, match="frozen"):
            engineering.save_operation(
                company_id,
                draft.id,
                {
                    "sequence": 30,
                    "name": "x",
                    "basic_minutes": "1",
                },
            )
        # The database refuses changes to a published bulletin and its operations.
        for statement in (
            "UPDATE bulletin_operations SET name = 'edited' WHERE bulletin_id = :id",
            "UPDATE operation_bulletins SET source = 'edited' WHERE id = :id",
        ):
            with pytest.raises(DBAPIError):
                db.session.execute(text(statement), {"id": draft.id})
            db.session.rollback()
        second = engineering.start_revision(company_id, style.id)
        assert second.revision == 2 and second.status == "draft"
        copied = engineering.operations(company_id, second.id)
        assert [op.name for op, _ in copied] == ["Shoulder join", "Fold"]
        assert engineering.current_bulletins(company_id)[style.id].id == draft.id
        assert engineering.discard_draft(company_id, second.id, second.version) == style.id
        assert db.session.get(OperationBulletin, second.id) is None
    finally:
        context.pop()


def test_csv_import_is_checked_row_by_row_and_all_or_nothing(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    context = as_user(app)
    try:
        sewing_classes(company_id)
        draft = engineering.start_revision(company_id, a_style(company_id).id)
        good = (
            "sequence,operation,machine,basic_minutes,allowance\n"
            "10,Shoulder join,SEW-OL,0.35,25\n"
            "20,Bottom hem,flatlock station,0.50\n"
            "30,Fold,manual,0.40,0.2\n"
        )
        assert engineering.import_operations(company_id, draft.id, good) == 3
        rows = engineering.operations(company_id, draft.id)
        assert [op.sam for op, _ in rows] == [D("0.4375"), D("0.625"), D("0.48")]
        with pytest.raises(DomainError, match="Line 3: unknown machine"):
            engineering.import_operations(
                company_id, draft.id, "10,A,SEW-OL,0.3\n20,B,SEW-OL,0.3\n30,C,ZIGZAG,0.3\n"
            )
        with pytest.raises(DomainError, match="repeats"):
            engineering.import_operations(company_id, draft.id, "10,A,SEW-OL,0.3\n10,B,manual,1\n")
        with pytest.raises(DomainError, match="Basic minutes"):
            engineering.import_operations(company_id, draft.id, "10,A,SEW-OL,0\n")
        with pytest.raises(DomainError, match="already exist"):
            engineering.import_operations(company_id, draft.id, "10,A,SEW-OL,0.3\n", replace=False)
        with pytest.raises(DomainError, match="too large"):
            engineering.import_operations(company_id, draft.id, "x" * 70_000)
        # Failed imports changed nothing.
        assert len(engineering.operations(company_id, draft.id)) == 3
        assert (
            engineering.import_operations(
                company_id, draft.id, "40,Label,SEW-OL,0.3\n", replace=False
            )
            == 1
        )
        assert len(engineering.operations(company_id, draft.id)) == 4
    finally:
        context.pop()


def test_other_companies_cannot_touch_a_bulletin(app, records):
    aurora, beacon = records["companies"]["aurora"], records["companies"]["beacon"]
    grant(aurora)
    grant(beacon)
    context = as_user(app)
    try:
        draft = engineering.start_revision(aurora, a_style(aurora).id)
    finally:
        context.pop()
    context = as_user(app, "catalog-editor@beacon.test")
    try:
        with pytest.raises(Exception) as caught:
            engineering.save_operation(
                beacon,
                draft.id,
                {
                    "sequence": 10,
                    "name": "x",
                    "basic_minutes": "1",
                },
            )
        assert getattr(caught.value, "code", None) == 404
    finally:
        context.pop()


# ---------- Screens ----------


def test_style_and_bulletin_screens_and_forms(app, records, client):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    context = as_user(app)
    try:
        classes = sewing_classes(company_id)
        style = a_style(company_id, "HOOD-1")
    finally:
        context.pop()
    login(client)
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/styles/{style.id}")
    assert page.status_code == 200 and "Start revision 1</button>" in page.text
    response = client.post(
        f"{base}/styles/{style.id}/revisions", data={"csrf_token": csrf(page), "version": "1"}
    )
    assert response.status_code == 303
    bulletin = db.session.scalar(
        select(OperationBulletin).where(OperationBulletin.style_id == style.id)
    )
    url = f"{base}/bulletins/{bulletin.id}/operations/new"
    form = client.get(url)
    assert "Manual work" in form.text
    response = client.post(
        url,
        data={
            "csrf_token": csrf(form),
            "version": "0",
            "sequence": "10",
            "name": "Hood seam",
            "machine_class_id": str(classes["SEW-OL"].id),
            "basic_minutes": "0.6",
            "allowance_factor": "25",
        },
    )
    assert response.status_code == 303, response.text
    imported = client.get(f"{base}/bulletins/{bulletin.id}/import")
    assert "template CSV" in imported.text
    response = client.post(
        f"{base}/bulletins/{bulletin.id}/import",
        data={
            "csrf_token": csrf(imported),
            "version": "1",
            "mode": "append",
            "rows": "20,Pocket attach,SEW-FL,1.6,25\n30,Fold,manual,0.85,25\n",
        },
    )
    assert response.status_code == 303, response.text
    page = client.get(f"{base}/bulletins/{bulletin.id}?operators=28&minutes=540&efficiency=70")
    assert page.status_code == 200
    # 0.75 + 2.0 + 1.0625 = 3.8125 SAM; 28 × 540 × 70% ÷ 3.8125 = 2,776 pieces.
    assert "3.81 min" in page.text and "2,776 pcs" in page.text
    db.session.expire_all()
    bulletin = db.session.get(OperationBulletin, bulletin.id)
    response = client.post(
        f"{base}/bulletins/{bulletin.id}/publish",
        data={"csrf_token": csrf(page), "version": str(bulletin.version)},
    )
    assert response.status_code == 303
    assert client.get(f"{base}/styles").text.count("3.81 min (rev 1)") == 1
    template = client.get(f"{base}/bulletins/template.csv")
    assert template.headers["Content-Type"].startswith("text/csv")
    assert template.text.startswith("sequence,operation,machine")
    assert db.session.scalar(select(db.func.count()).select_from(BulletinOperation)) == 3
    assert db.session.scalar(select(MachineClass.id).where(MachineClass.code == "SEW-OL"))
    assert db.session.scalar(select(Style.code)) == "HOOD-1"


def test_read_only_members_cannot_change_work_content(app, records, client):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    context = as_user(app)
    try:
        style = a_style(company_id)
    finally:
        context.pop()
    grant(company_id, codes=("factory.read",), role_code="auditor")
    login(client, "auditor@aurora.test")
    page = client.get(f"/companies/{company_id}/factory/styles/{style.id}")
    assert page.status_code == 200 and "Start revision 1</button>" not in page.text
    response = client.post(
        f"/companies/{company_id}/factory/styles/{style.id}/revisions",
        data={"csrf_token": csrf(page), "version": "1"},
    )
    assert response.status_code == 403
