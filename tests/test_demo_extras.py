"""Demonstration records and readable labels for first-time viewers."""

from conftest import login
from sqlalchemy import select
from test_quality import grant, signed

from app.extensions import db
from app.models import Membership, User
from app.models.master import Lot
from app.models.quality import Nonconformance
from app.services import trace
from app.services.demo_extras import seed_extras
from app.services.trace_fixture import seed_c10


def test_extras_are_idempotent_and_pages_explain_codes(app, records, client):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    with signed(app, company_id):
        fixture = seed_c10(company_id)
        run = trace.compute(company_id, fixture["case_id"])
        run_id = run.id
        member = db.session.scalar(
            select(Membership)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == company_id,
                User.email == "catalog-editor@aurora.test",
            )
        )
        first = seed_extras(company_id, member.id)
        assert "Renamed C10-LAMP: LED desk lamp" in first
        assert any("INSPECTION-C10-001" in line for line in first)
        assert seed_extras(company_id, member.id) == []
        issue = db.session.scalar(
            select(Nonconformance).where(
                Nonconformance.organization_id == company_id,
                Nonconformance.reference == "QUALITY-ISSUE-C10-001",
            )
        )
        assert issue.severity == "high" and issue.inspection_id is not None
        lot_l1 = db.session.scalar(
            select(Lot).where(Lot.organization_id == company_id, Lot.lot_code == "L1")
        )
        l1_id = lot_l1.id
    login(client)
    case_page = client.get(f"/companies/{company_id}/cases/{fixture['case_id']}").text
    assert "Shipment C10-S1 to Northside Home Stores (fictional retailer), lot L1" in case_page
    assert "C10 — Lamp power switch" in case_page
    trace_page = client.get(f"/companies/{company_id}/cases/traces/{run_id}").text
    assert "L1 — LED desk lamp" in trace_page
    assert "made in production run C10-RUN-A" in trace_page
    assert "LED desk lamp (C10-LAMP-01)" in trace_page
    lot_page = client.get(f"/companies/{company_id}/master/lots/{l1_id}").text
    assert "Product (SKU)" in lot_page and "Variant id" not in lot_page
    stock_page = client.get(f"/companies/{company_id}/operations").text
    assert "L1 — LED desk lamp" in stock_page
    assert " / Catalog</p>" not in stock_page
