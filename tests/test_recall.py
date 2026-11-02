"""Independent approvals, trace freshness, bounded recovery and closure review."""

import pytest
from sqlalchemy import func, select
from test_quality import grant, signed

from app.extensions import db
from app.models import Organization
from app.models.quality import QualityHold
from app.models.recall import CaseAffectedShipment, CaseComment, RecallCase, RecoveryRecord
from app.services import recall, trace
from app.services.business import DomainError
from app.services.trace_fixture import seed_c10


def test_self_approval_stale_scope_and_independent_atomic_holds(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    grant(company_id, "auditor")
    with signed(app, company_id, verified=True):
        fixture = seed_c10(company_id)
        case_id = fixture["case_id"]
        trace.compute(company_id, case_id)
        recall.submit(company_id, case_id)
        with pytest.raises(DomainError, match="different quality reviewer"):
            recall.approve(company_id, case_id)
    with signed(app, company_id, "auditor@aurora.test", verified=True):
        company = db.session.get(Organization, company_id)
        company.trace_revision += 1
        db.session.commit()
        with pytest.raises(DomainError, match="Recompute"):
            recall.approve(company_id, case_id)
        assert db.session.scalar(select(func.count()).select_from(QualityHold)) == 0
        trace.compute(company_id, case_id)
        case = recall.approve(company_id, case_id)
        assert case.status == "approved"
        with pytest.raises(DomainError, match="Reopen the approved"):
            trace.compute(company_id, case_id)
        holds = db.session.scalars(select(QualityHold).where(QualityHold.case_id == case_id)).all()
        assert {row.lot_id for row in holds} == {
            fixture["lots"][code] for code in ("C10", "L1", "L2")
        }


def test_recovery_repeat_payload_caps_and_reviewed_closure(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    grant(company_id, "auditor")
    with signed(app, company_id):
        fixture = seed_c10(company_id)
        case_id = fixture["case_id"]
        trace.compute(company_id, case_id)
        recall.submit(company_id, case_id)
    with signed(app, company_id, "auditor@aurora.test", verified=True):
        recall.approve(company_id, case_id)
        with pytest.raises(DomainError, match="all dispatched exposure"):
            recall.close(company_id, case_id, "All reviewed")
        first = recall.record_recovery(
            company_id,
            case_id,
            fixture["shipment_lines"]["S1"],
            60,
            "returned",
            "Fictional signed warehouse receipt",
            "RECOVERY-1",
        )
        first_id = first.id
        repeated = recall.record_recovery(
            company_id,
            case_id,
            fixture["shipment_lines"]["S1"],
            60,
            "returned",
            "Fictional signed warehouse receipt",
            "RECOVERY-1",
        )
        assert repeated.id == first_id
        with pytest.raises(DomainError, match="different recovery"):
            recall.record_recovery(
                company_id,
                case_id,
                fixture["shipment_lines"]["S1"],
                59,
                "returned",
                "Fictional signed warehouse receipt",
                "RECOVERY-1",
            )
        with pytest.raises(DomainError, match="cannot exceed"):
            recall.record_recovery(
                company_id,
                case_id,
                fixture["shipment_lines"]["S1"],
                1,
                "returned",
                "Duplicate physical count",
                "RECOVERY-2",
            )
        recall.record_recovery(
            company_id,
            case_id,
            fixture["shipment_lines"]["S2"],
            50,
            "destroyed",
            "Fictional destruction certificate",
            "RECOVERY-3",
        )
        with pytest.raises(DomainError, match="acknowledgements"):
            recall.close(company_id, case_id, "Reviewed quantities")
        case = recall.close(
            company_id,
            case_id,
            "All fictional disposition evidence reviewed",
            "Demonstration customer communication was intentionally not sent.",
        )
        assert case.status == "closed"
        rows = db.session.scalars(
            select(CaseAffectedShipment).where(CaseAffectedShipment.case_id == case_id)
        ).all()
        assert sum(row.quantity_resolved for row in rows) == 110
        assert sum(row.quantity_recovered for row in rows) == 60
        assert db.session.scalar(select(func.count()).select_from(RecoveryRecord)) == 2
        assert db.session.scalar(select(CaseComment.id).where(CaseComment.case_id == case_id))
        assert db.session.get(RecallCase, case_id).closed_at is not None


def test_task_requires_independent_evidence_verification(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    grant(company_id, "auditor")
    with signed(app, company_id) as member:
        case = recall.save_case(
            company_id, "TASK-CASE", "Task evidence", "Fictional concern", "low"
        )
        case_id = case.id
        task = recall.task(
            company_id, case_id, "Inspect stock", "Review the physical count", member.id
        )
        task_id = task.id
        recall.complete_task(company_id, task_id, "Counted all items")
        with pytest.raises(DomainError, match="different reviewer"):
            recall.complete_task(company_id, task_id, "Self verify", verify=True)
    with signed(app, company_id, "auditor@aurora.test"):
        task = recall.complete_task(company_id, task_id, "Reviewed count evidence", verify=True)
        assert task.status == "verified"
        assert task.verifier_id != task.assignee_id


def test_comment_amendments_preserve_attributed_originals(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    with signed(app, company_id):
        case = recall.save_case(
            company_id, "COMMENT-CASE", "Correction history", "Fictional concern", "low"
        )
        case_id = case.id
        original = recall.comment(company_id, case_id, "Original recorded finding")
        original_id = original.id
        correction = recall.comment(
            company_id, case_id, "Corrected finding with evidence", original_id, original.version
        )
        assert correction.id != original_id
        assert db.session.get(CaseComment, original_id).body == "Original recorded finding"
        assert str(original_id) in correction.body
        assert "Corrected finding" in correction.body
