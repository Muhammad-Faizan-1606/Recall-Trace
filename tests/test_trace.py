"""The specification's C10 trace fixture through real PostgreSQL posting services."""

from decimal import Decimal

import pytest
from conftest import login
from sqlalchemy import select
from test_quality import grant, signed

from app.extensions import db
from app.models.recall import CaseAffectedShipment, TraceResult
from app.services import recall, trace
from app.services.business import DomainError
from app.services.trace_fixture import seed_c10


def test_c10_deduplicates_recorded_lots_and_shipments_and_separates_skus(app, records, client):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    with signed(app, company_id):
        fixture = seed_c10(company_id)
        run = trace.compute(company_id, fixture["case_id"])
        run_id = run.id
        reached = set(
            db.session.scalars(select(TraceResult.lot_id).where(TraceResult.trace_run_id == run_id))
        )
        assert reached == {fixture["lots"][key] for key in ("C10", "L1", "L2")}
        exposed = db.session.scalars(
            select(CaseAffectedShipment).where(CaseAffectedShipment.trace_run_id == run_id)
        ).all()
        assert {r.shipment_line_id for r in exposed} == {
            fixture["shipment_lines"]["S1"],
            fixture["shipment_lines"]["S2"],
        }
        assert sum(r.quantity_dispatched for r in exposed) == Decimal("110")
        summary = {row["sku"]: row for row in trace.summary(company_id, run_id)}
        assert summary["C10-LAMP-01"]["produced"] == 150
        assert summary["C10-LAMP-01"]["dispatched"] == 110
        assert summary["C10-LAMP-01"]["on_hand"] == 40
        assert summary["C10-SWITCH-01"]["on_hand"] == 50
        assert run.is_complete
        # Multiple roots that reach the same recorded production must not multiply exposure.
        recall.source(
            company_id,
            fixture["case_id"],
            fixture["lots"]["L1"],
            "Additional root already in downstream scope",
        )
        rerun = trace.compute(company_id, fixture["case_id"])
        assert (
            len(
                db.session.scalars(
                    select(CaseAffectedShipment).where(
                        CaseAffectedShipment.trace_run_id == rerun.id
                    )
                ).all()
            )
            == 2
        )
    login(client)
    response = client.get(f"/companies/{company_id}/cases/traces/{run_id}")
    assert response.status_code == 200
    assert b"<svg" in response.data and b"Accessible evidence table" in response.data
    assert b"C10-LAMP-01" in response.data


def test_partial_and_upstream_traces_cannot_authorize_operational_decisions(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    with signed(app, company_id):
        fixture = seed_c10(company_id)
        partial = trace.compute(company_id, fixture["case_id"], max_nodes=1)
        assert not partial.is_complete
        assert partial.limits["reached_limit"] == "node_limit"
        with pytest.raises(DomainError, match="complete downstream"):
            recall.current_trace(company_id, fixture["case_id"])
        upstream = trace.compute(company_id, fixture["case_id"], direction="upstream")
        assert upstream.is_complete
        with pytest.raises(DomainError, match="complete downstream"):
            recall.current_trace(company_id, fixture["case_id"])


def test_trace_fixture_is_repeatable_without_changing_posted_stock(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    with signed(app, company_id):
        first = seed_c10(company_id)
        second = seed_c10(company_id)
        assert second == first
        run = trace.compute(company_id, first["case_id"])
        totals = {row["sku"]: row for row in trace.summary(company_id, run.id)}
        assert totals["C10-LAMP-01"]["dispatched"] == 110
        assert totals["C10-SWITCH-01"]["on_hand"] == 50
