"""Adversarial requests and evidence/approval integrity beyond the happy path."""

import uuid

import pytest
from conftest import csrf, login, post_form
from sqlalchemy import func, select
from test_quality import grant, signed
from werkzeug.exceptions import Forbidden

from app.extensions import db
from app.models import Organization
from app.models.evidence import Document
from app.models.master import Lot, Partner, PartnerContact, PartnerRoleAssignment
from app.models.operations import StockBalance
from app.models.quality import InspectionCheck, InspectionTemplate, Nonconformance
from app.models.recall import CaseAffectedShipment, CaseTask, RecallCase, RecoveryRecord
from app.services import notices, operations, quality, recall, trace
from app.services.business import DomainError
from app.services.trace_fixture import seed_c10


@pytest.fixture
def investigation(records, app):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    with signed(app, company_id) as member:
        first = Lot(
            organization_id=company_id,
            lot_code="ADVERSARIAL-A",
            variant_id=records["aurora_variants"],
        )
        second = Lot(
            organization_id=company_id,
            lot_code="ADVERSARIAL-B",
            variant_id=records["aurora_variants"],
        )
        db.session.add_all([first, second])
        db.session.commit()
        template = quality.save_template(company_id, "ADVERSARIAL", 1)
        check = quality.save_check(
            company_id, template.id, 1, "Observed condition", "text", {"equals": "ok"}
        )
        quality.publish_template(company_id, template.id)
        inspection = quality.create_inspection(company_id, "ADV-INSPECTION", first.id, template.id)
        other_inspection = quality.create_inspection(company_id, "ADV-OTHER", first.id, template.id)
        issue = quality.save_nonconformance(
            company_id, "ADV-ISSUE", first.id, "Fictional quality concern", "high", inspection.id
        )
        case = recall.save_case(
            company_id, "ADV-CASE", "Evidence test", "Fictional concern", "high"
        )
        document = Document(
            organization_id=company_id,
            object_key="adversarial-document-metadata",
            original_name="PRIVATE-EVIDENCE-NAME.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256="0" * 64,
            scan_status="clean",
            state="active",
            uploaded_by_id=member.id,
        )
        db.session.add(document)
        db.session.commit()
        return dict(
            company=company_id,
            lot=first.id,
            second=second.id,
            template=template.id,
            check=check.id,
            inspection=inspection.id,
            other_inspection=other_inspection.id,
            issue=issue.id,
            case=case.id,
            document=document.id,
        )


@pytest.mark.parametrize("version", ["garbage", "1.0", "-1", "１", "9" * 5000])
@pytest.mark.parametrize("kind", ["quality", "case"])
def test_malformed_versions_never_cause_server_error(client, investigation, version, kind):
    s = investigation
    login(client)
    if kind == "quality":
        page = f"/companies/{s['company']}/quality/inspections/{s['inspection']}"
        action = page + "/complete"
    else:
        page = f"/companies/{s['company']}/cases/{s['case']}"
        action = page + "/submit"
    response = client.post(action, data={"csrf_token": csrf(client.get(page)), "version": version})
    assert response.status_code == 409
    assert db.session.get(RecallCase, s["case"]).status == "draft"


@pytest.mark.parametrize("field", ["revision", "sequence"])
def test_oversized_definition_integers_are_rejected_before_database_write(
    app, records, client, field
):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    login(client)
    if field == "revision":
        location = f"/companies/{company_id}/quality/templates/new"
        values = {"code": "OVERFLOW", "revision": "2147483648"}
    else:
        with signed(app, company_id):
            template = quality.save_template(company_id, "OVERFLOW", 1)
            template_id = template.id
        location = f"/companies/{company_id}/quality/templates/{template_id}"
        values = {"sequence": "2147483648", "label": "Overflow", "value_type": "text", "rule": "{}"}
    assert post_form(client, location, values).status_code == 422
    assert db.session.scalar(select(func.count()).select_from(InspectionCheck)) == 0
    if field == "revision":
        assert db.session.scalar(select(func.count()).select_from(InspectionTemplate)) == 0


@pytest.mark.parametrize("page_kind", ["case", "inspection", "issue"])
def test_catalog_read_does_not_reveal_private_evidence_filenames(client, investigation, page_kind):
    s = investigation
    login(client, "auditor@aurora.test")
    if page_kind == "case":
        path = f"/companies/{s['company']}/cases/{s['case']}"
    elif page_kind == "inspection":
        path = f"/companies/{s['company']}/quality/inspections/{s['inspection']}"
    else:
        path = f"/companies/{s['company']}/quality/issues/{s['issue']}"
    response = client.get(path)
    assert response.status_code == 200
    assert "PRIVATE-EVIDENCE-NAME.pdf" not in response.text
    assert str(s["document"]) not in response.text


@pytest.mark.parametrize("link", ["hold", "case"])
@pytest.mark.parametrize("changed", ["lot", "inspection"])
def test_referenced_quality_evidence_cannot_be_reassigned(app, investigation, link, changed):
    s = investigation
    with signed(app, s["company"]):
        if link == "hold":
            quality.place_hold(s["company"], s["lot"], "Recorded hold", s["issue"])
        else:
            recall.source(s["company"], s["case"], s["lot"], "Recorded finding", s["issue"])
        with pytest.raises(DomainError, match="Referenced quality issue"):
            quality.save_nonconformance(
                s["company"],
                "ADV-ISSUE",
                s["second"] if changed == "lot" else s["lot"],
                "Changed concern",
                "high",
                None if changed == "lot" else s["other_inspection"],
                s["issue"],
            )
        issue = db.session.get(Nonconformance, s["issue"])
        assert issue.lot_id == s["lot"] and issue.inspection_id == s["inspection"]


def test_cancelled_investigation_cannot_change_task_evidence(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    with signed(app, company_id) as member:
        case = recall.save_case(
            company_id, "CANCELLED", "Cancelled work", "Fictional concern", "low"
        )
        task = recall.task(company_id, case.id, "Count stock", "Record the count", member.id)
        task_id = task.id
        recall.cancel_draft(company_id, case.id, "Investigation cancelled")
        with pytest.raises(DomainError, match="no longer editable"):
            recall.complete_task(company_id, task_id, "Late alteration")
        assert db.session.get(CaseTask, task_id).status == "open"


def test_independent_task_verification_requires_recent_real_mfa(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    grant(company_id, "auditor")
    with signed(app, company_id) as member:
        case = recall.save_case(company_id, "MFA-TASK", "Verify work", "Fictional concern", "low")
        task = recall.task(company_id, case.id, "Count stock", "Record the count", member.id)
        task_id = task.id
        recall.complete_task(company_id, task_id, "Count completed")
    with signed(app, company_id, "auditor@aurora.test"):
        with pytest.raises(Forbidden):
            recall.complete_task(company_id, task_id, "Stolen password only", verify=True)
        assert db.session.get(CaseTask, task_id).status == "completed"
    with signed(app, company_id, "auditor@aurora.test", verified=True):
        assert (
            recall.complete_task(
                company_id, task_id, "Independent evidence reviewed", verify=True
            ).status
            == "verified"
        )


def test_shipments_are_bounded_and_partial_exposure_never_authorizes_decisions(
    app, records, monkeypatch
):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    with signed(app, company_id):
        fixture = seed_c10(company_id)
        monkeypatch.setattr(trace, "MAX_EXPOSURE_LINES", 1)
        run = trace.compute(company_id, fixture["case_id"])
        assert run.status == "incomplete" and run.is_complete is False
        assert run.limits["reached_limit"] == "shipment_limit"
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(CaseAffectedShipment)
                .where(CaseAffectedShipment.trace_run_id == run.id)
            )
            == 1
        )
        with pytest.raises(DomainError, match="complete downstream"):
            recall.current_trace(company_id, fixture["case_id"])


def test_boolean_criteria_are_typed_and_false_observations_are_preserved(app, investigation):
    s = investigation
    with signed(app, s["company"]):
        template = quality.save_template(s["company"], "BOOLEAN", 1)
        template_id = template.id
        with pytest.raises(DomainError, match="Boolean criteria"):
            quality.save_check(
                s["company"],
                template_id,
                1,
                "Invalid criterion",
                "boolean",
                {"equals": {"expression": "false"}},
            )
        check = quality.save_check(
            s["company"], template_id, 1, "Disabled state", "boolean", {"equals": False}
        )
        check_id = check.id
        quality.publish_template(s["company"], template_id)
        inspection = quality.create_inspection(s["company"], "BOOLEAN-OBS", s["lot"], template_id)
        result = quality.observe(s["company"], inspection.id, check_id, False)
        assert result.outcome == "pass" and result.text_value == "false"


@pytest.mark.parametrize("target", ["case", "finding", "observation"])
def test_nul_text_is_rejected_without_changing_saved_evidence(app, investigation, target):
    s = investigation
    with signed(app, s["company"]):
        with pytest.raises(DomainError):
            if target == "case":
                recall.save_case(
                    s["company"], "ADV-CASE", "NUL\x00title", "Fictional", "high", s["case"]
                )
            elif target == "finding":
                quality.save_nonconformance(
                    s["company"],
                    "ADV-ISSUE",
                    s["lot"],
                    "NUL\x00evidence",
                    "high",
                    s["inspection"],
                    s["issue"],
                )
            else:
                quality.observe(s["company"], s["inspection"], s["check"], "ok", "NUL\x00comment")
        assert db.session.get(RecallCase, s["case"]).title == "Evidence test"
        assert db.session.get(Nonconformance, s["issue"]).description == "Fictional quality concern"


def test_recovery_retry_cannot_substitute_notice_payload(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    grant(company_id, "auditor")
    with signed(app, company_id):
        fixture = seed_c10(company_id)
        trace.compute(company_id, fixture["case_id"])
        recall.submit(company_id, fixture["case_id"])
    with signed(app, company_id, "auditor@aurora.test", verified=True):
        recall.approve(company_id, fixture["case_id"])
        values = (
            company_id,
            fixture["case_id"],
            fixture["shipment_lines"]["S1"],
            1,
            "returned",
            "Physical evidence",
            "NOTICE-PAYLOAD",
        )
        original = recall.record_recovery(*values)
        original_id = original.id
        with pytest.raises(DomainError, match="different recovery"):
            recall.record_recovery(*values, notice_id=uuid.uuid4())
        assert recall.record_recovery(*values).id == original_id
        assert db.session.scalar(select(func.count()).select_from(RecoveryRecord)) == 1


def test_recovery_notice_must_match_the_shipment_recipient(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    grant(company_id, "auditor")
    with signed(app, company_id):
        fixture = seed_c10(company_id)
        second_customer = Partner(
            organization_id=company_id, code="SECOND-CUSTOMER", name="Other recipient"
        )
        db.session.add(second_customer)
        db.session.flush()
        db.session.add(
            PartnerRoleAssignment(
                organization_id=company_id, partner_id=second_customer.id, role_code="customer"
            )
        )
        contact = PartnerContact(
            organization_id=company_id,
            partner_id=second_customer.id,
            name="Other contact",
            email="other@customer.test",
            purpose="recalls",
        )
        db.session.add(contact)
        db.session.commit()
        contact_id = contact.id
        lot = db.session.get(Lot, fixture["lots"]["L1"])
        order = operations.create_document(
            company_id,
            "sales-orders",
            {
                "reference": "SECOND-CUSTOMER-ORDER",
                "customer_id": second_customer.id,
                "destination": "Other campus",
            },
        )
        order_id = order.id
        line = operations.add_line(
            company_id, "sales-orders", order_id, {"variant_id": lot.variant_id, "quantity": 1}
        )
        line_id = line.id
        operations.post_document(company_id, "sales-orders", order_id, "second-customer-order")
        shipment = operations.create_document(
            company_id,
            "shipments",
            {
                "reference": "SECOND-CUSTOMER-SHIP",
                "sales_order_id": order_id,
                "warehouse_id": fixture["warehouse_id"],
            },
        )
        shipment_id = shipment.id
        operations.add_line(
            company_id,
            "shipments",
            shipment_id,
            {
                "lot_id": lot.id,
                "quantity": 1,
                "sales_order_line_id": line_id,
                "source_location_id": fixture["location_id"],
            },
        )
        operations.post_document(company_id, "shipments", shipment_id, "second-customer-shipment")
        trace.compute(company_id, fixture["case_id"])
        recall.submit(company_id, fixture["case_id"])
    with signed(app, company_id, "auditor@aurora.test", verified=True):
        recall.approve(company_id, fixture["case_id"])
        other_notice = notices.create_notice(company_id, fixture["case_id"], contact_id)
        with pytest.raises(DomainError, match="recipient does not own"):
            recall.record_recovery(
                company_id,
                fixture["case_id"],
                fixture["shipment_lines"]["S1"],
                1,
                "returned",
                "Misattributed receipt",
                "WRONG-RECIPIENT",
                notice_id=other_notice.id,
            )
        assert db.session.scalar(select(func.count()).select_from(RecoveryRecord)) == 0


@pytest.fixture
def overlapping_cases(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    grant(company_id, "auditor")
    with signed(app, company_id):
        fixture = seed_c10(company_id)
        overlap = recall.save_case(
            company_id, "OVERLAP", "Overlapping investigation", "Second recorded concern", "high"
        )
        overlap_id = overlap.id
        recall.source(company_id, overlap_id, fixture["lots"]["L1"], "Same dispatched lamp lot")
        # Both cases must approve the current revision, with historical snapshots
        # already present when the immutable dispositions are recorded.
        for case_id in (fixture["case_id"], overlap_id):
            trace.compute(company_id, case_id)
            trace.compute(company_id, case_id)
            recall.submit(company_id, case_id)
        return company_id, fixture, overlap_id


def test_overlapping_cases_share_dispositions_across_every_snapshot_without_restock(
    app, overlapping_cases
):
    company_id, fixture, overlap_id = overlapping_cases
    original_id = fixture["case_id"]
    line_id = fixture["shipment_lines"]["S1"]
    with signed(app, company_id, "auditor@aurora.test", verified=True):
        recall.approve(company_id, original_id)
        recall.approve(company_id, overlap_id)
        stock_before = dict(
            db.session.execute(select(StockBalance.id, StockBalance.quantity)).all()
        )
        original = recall.record_recovery(
            company_id,
            original_id,
            line_id,
            40,
            "returned",
            "Original physical receipt",
            "SHARED-RETURN",
        )
        original_record_id = original.id
        rows = db.session.scalars(
            select(CaseAffectedShipment).where(
                CaseAffectedShipment.organization_id == company_id,
                CaseAffectedShipment.shipment_line_id == line_id,
            )
        ).all()
        assert len(rows) == 4
        assert {row.case_id for row in rows} == {original_id, overlap_id}
        assert {(row.quantity_resolved, row.quantity_recovered) for row in rows} == {(40, 40)}
        recall.record_recovery(
            company_id,
            overlap_id,
            line_id,
            20,
            "destroyed",
            "Remaining units destroyed",
            "SHARED-DESTROY",
        )
        assert {(row.quantity_resolved, row.quantity_recovered) for row in rows} == {(60, 40)}
        with pytest.raises(DomainError, match="different recovery"):
            recall.record_recovery(
                company_id,
                overlap_id,
                line_id,
                40,
                "returned",
                "Original physical receipt",
                "SHARED-RETURN",
            )
        with pytest.raises(DomainError, match="cannot exceed"):
            recall.record_recovery(
                company_id,
                original_id,
                line_id,
                1,
                "returned",
                "Duplicate allocation",
                "EXCESS-RETURN",
            )
        assert (
            db.session.scalar(
                select(func.sum(RecoveryRecord.quantity)).where(
                    RecoveryRecord.organization_id == company_id,
                    RecoveryRecord.shipment_line_id == line_id,
                )
            )
            == 60
        )
        assert db.session.scalar(select(func.count()).select_from(RecoveryRecord)) == 2
        assert db.session.get(RecoveryRecord, original_record_id).case_id == original_id
        assert (
            dict(db.session.execute(select(StockBalance.id, StockBalance.quantity)).all())
            == stock_before
        )
        closed = recall.close(
            company_id,
            overlap_id,
            "Reviewed original receipt and destruction evidence",
            "Fictional customer communication intentionally not sent in this test.",
        )
        assert closed.status == "closed"
        assert db.session.scalar(select(func.count()).select_from(RecoveryRecord)) == 2


def test_later_case_inherits_disposition_with_visible_origin_and_company_isolation(
    app, records, client
):
    company_id = records["companies"]["aurora"]
    foreign_company_id = records["companies"]["beacon"]
    for company in (company_id, foreign_company_id):
        grant(company)
        grant(company, "auditor")
    with signed(app, company_id):
        fixture = seed_c10(company_id)
        original_id = fixture["case_id"]
        line_id = fixture["shipment_lines"]["S1"]
        trace.compute(company_id, original_id)
        recall.submit(company_id, original_id)
    with signed(app, company_id, "auditor@aurora.test", verified=True):
        recall.approve(company_id, original_id)
        record = recall.record_recovery(
            company_id,
            original_id,
            line_id,
            60,
            "returned",
            "Prior physical receipt",
            "PRIOR-DISPOSITION",
        )
        record_id = record.id
        recall.record_recovery(
            company_id,
            original_id,
            fixture["shipment_lines"]["S2"],
            50,
            "destroyed",
            "Outside the later case scope",
            "OUTSIDE-LATER-SCOPE",
        )
        later = recall.save_case(
            company_id, "LATER", "Later investigation", "New concern for the same dispatch", "high"
        )
        later_id = later.id
        recall.source(company_id, later_id, fixture["lots"]["L1"], "Previously disposed lamp lot")
        run = trace.compute(company_id, later_id)
        exposure = db.session.scalar(
            select(CaseAffectedShipment).where(CaseAffectedShipment.trace_run_id == run.id)
        )
        assert exposure.quantity_resolved == 60 and exposure.quantity_recovered == 60
        recall.submit(company_id, later_id)
    with signed(app, foreign_company_id, "catalog-editor@beacon.test"):
        foreign = seed_c10(foreign_company_id)
        trace.compute(foreign_company_id, foreign["case_id"])
        recall.submit(foreign_company_id, foreign["case_id"])
    with signed(app, foreign_company_id, "auditor@beacon.test", verified=True):
        recall.approve(foreign_company_id, foreign["case_id"])
        foreign_record = recall.record_recovery(
            foreign_company_id,
            foreign["case_id"],
            foreign["shipment_lines"]["S1"],
            60,
            "destroyed",
            "Foreign company private evidence",
            "FOREIGN-DISPOSITION-PRIVATE",
        )
        foreign_record_id = foreign_record.id
    # Read provenance before this user enrolls MFA below. Its fresh browser
    # session must not inherit the service request's MFA verification.
    login(client)
    response = client.get(f"/companies/{company_id}/cases/{later_id}")
    assert response.status_code == 200
    assert "Reused disposition evidence from case" in response.text
    assert "C10-INVESTIGATION" in response.text and "PRIOR-DISPOSITION" in response.text
    assert f"/companies/{company_id}/cases/{original_id}#recovery-{record_id}" in response.text
    assert str(record_id) in response.text
    assert "OUTSIDE-LATER-SCOPE" not in response.text
    assert "FOREIGN-DISPOSITION-PRIVATE" not in response.text
    assert str(foreign_record_id) not in response.text
    with signed(app, company_id, verified=True):
        assert trace.physical_resolutions(
            company_id, [line_id, foreign["shipment_lines"]["S1"]]
        ) == {line_id: (60, 60)}
        recall.approve(company_id, later_id)
        with pytest.raises(DomainError, match="cannot exceed"):
            recall.record_recovery(
                company_id,
                later_id,
                line_id,
                1,
                "returned",
                "Already disposed",
                "NO-NEW-ALLOCATION",
            )
        assert (
            recall.close(
                company_id,
                later_id,
                "Reviewed inherited physical disposition evidence",
                "Fictional customer communication intentionally not sent in this test.",
            ).status
            == "closed"
        )


def test_shared_dispositions_still_require_approved_current_shipment_scope(app, overlapping_cases):
    company_id, fixture, overlap_id = overlapping_cases
    line_id = fixture["shipment_lines"]["S1"]
    with signed(app, company_id, verified=True):
        with pytest.raises(DomainError, match="approved open case"):
            recall.record_recovery(
                company_id, overlap_id, line_id, 1, "returned", "Unapproved case", "UNAPPROVED"
            )
        with pytest.raises(DomainError, match="Only approved"):
            recall.close(company_id, overlap_id, "Unapproved closure")
    with signed(app, company_id, "auditor@aurora.test", verified=True):
        recall.approve(company_id, fixture["case_id"])
        recall.approve(company_id, overlap_id)
        recall.record_recovery(
            company_id,
            fixture["case_id"],
            line_id,
            60,
            "returned",
            "Physical receipt",
            "SCOPE-RETURN",
        )
        with pytest.raises(DomainError, match="outside the approved trace scope"):
            recall.record_recovery(
                company_id,
                overlap_id,
                fixture["shipment_lines"]["S2"],
                1,
                "returned",
                "Different shipment scope",
                "OUTSIDE-SCOPE",
            )
        db.session.get(Organization, company_id).trace_revision += 1
        db.session.commit()
        with pytest.raises(DomainError, match="Recompute"):
            recall.record_recovery(
                company_id, overlap_id, line_id, 1, "returned", "Stale case", "STALE-ALLOCATION"
            )
        with pytest.raises(DomainError, match="Recompute"):
            recall.close(
                company_id,
                overlap_id,
                "Inherited evidence does not approve a stale scope",
                "Fictional acknowledgement exception reviewed in this test.",
            )
        assert db.session.scalar(select(func.count()).select_from(RecoveryRecord)) == 1
