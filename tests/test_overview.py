"""Company overview: scoped counts, links and readable activity."""

from datetime import UTC, datetime
from types import SimpleNamespace

from conftest import login
from test_quality import grant, signed

from app.blueprints.overview import describe
from app.presentation import day_text, when_text
from app.services import trace
from app.services.trace_fixture import seed_c10


def test_overview_shows_open_work_for_the_members_company(app, records, client):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    with signed(app, company_id):
        fixture = seed_c10(company_id)
        trace.compute(company_id, fixture["case_id"])
    login(client)
    response = client.get(f"/companies/{company_id}/overview")
    assert response.status_code == 200
    page = response.text
    assert "Open investigations" in page and "Suspect C10 switch lot" in page
    assert f"/companies/{company_id}/cases/{fixture['case_id']}" in page
    assert "computed a trace" in page
    assert response.headers["Cache-Control"] == "no-store"


def test_overview_is_private_to_members(app, records, client):
    aurora, beacon = records["companies"]["aurora"], records["companies"]["beacon"]
    assert client.get(f"/companies/{aurora}/overview").status_code == 302
    login(client)
    assert client.get(f"/companies/{beacon}/overview").status_code == 404


def test_companies_page_opens_the_overview(records, client):
    login(client)
    page = client.get("/").text
    assert f"/companies/{records['companies']['aurora']}/overview" in page


def test_activity_reads_as_plain_language():
    def event(action, kind):
        return SimpleNamespace(action=action, entity_kind=kind)

    assert describe(event("quality.complete_inspection", "complete_inspection")) == (
        "completed an inspection"
    )
    assert describe(event("operations.post_document", "shipments")) == "posted a shipment"
    assert describe(event("operations.add_line", "production_outputs")) == (
        "added a line to a production run"
    )
    assert describe(event("master.created", "partner_contacts")) == "added a partner contact"
    assert describe(event("something.new_action", "x")) == "something new action"


def test_dates_are_readable():
    moment = datetime(2026, 11, 4, 22, 6, 37, 221724, tzinfo=UTC)
    assert when_text(moment) == "4 Nov 2026, 22:06 UTC"
    assert day_text(moment) == "4 Nov 2026"
    assert when_text(None) is None
