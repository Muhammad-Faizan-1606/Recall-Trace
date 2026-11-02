"""Quality version freezing, observation rules and independent hold decisions."""

from contextlib import contextmanager

import pytest
from conftest import PASSWORD, login
from cryptography.fernet import Fernet
from sqlalchemy import select
from werkzeug.exceptions import Forbidden, NotFound

from app.extensions import db
from app.models import Membership, Permission, Role, RolePermission
from app.models.master import Lot
from app.models.quality import InspectionResult, QualityHold
from app.services import mfa, quality
from app.services.auth import authenticate
from app.services.business import DomainError

CODES = (
    "quality.inspect",
    "quality.hold",
    "quality.release",
    "case.prepare",
    "case.approve",
    "case.close",
    "trace.run",
    "inventory.receive",
    "inventory.transfer",
    "inventory.dispatch",
    "production.post",
    "recovery.record",
    "evidence.read",
    "evidence.upload",
    "notice.prepare",
)


def grant(company_id, email_role="catalog-editor"):
    role = db.session.scalar(
        select(Role).where(Role.organization_id == company_id, Role.code == email_role)
    )
    for code in CODES:
        permission = db.session.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, description=code)
            db.session.add(permission)
            db.session.flush()
        if not db.session.scalar(
            select(RolePermission.id).where(
                RolePermission.role_id == role.id, RolePermission.permission_id == permission.id
            )
        ):
            db.session.add(
                RolePermission(
                    organization_id=company_id, role_id=role.id, permission_id=permission.id
                )
            )
    db.session.commit()


@contextmanager
def signed(app, company_id, email="catalog-editor@aurora.test", verified=False):
    from flask_login import current_user

    with app.test_request_context():
        assert authenticate(email, PASSWORD)
        member = db.session.scalar(
            select(Membership).where(
                Membership.organization_id == company_id, Membership.user_id == current_user.id
            )
        )
        if verified:
            # Exercise real encryption, enrollment and code confirmation, not a disabled MFA guard.
            app.config["MFA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
            secret = mfa.begin_enrollment(PASSWORD)
            mfa.confirm_enrollment(mfa.totp(secret))
        yield member


def one_lot(records):
    company_id = records["companies"]["aurora"]
    lot = Lot(
        organization_id=company_id, lot_code="QUALITY-LOT", variant_id=records["aurora_variants"]
    )
    db.session.add(lot)
    db.session.commit()
    return lot.id


def test_published_criteria_and_completed_observations_are_frozen(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    lot_id = one_lot(records)
    with signed(app, company_id):
        template = quality.save_template(company_id, "DIMENSION", 1)
        check = quality.save_check(
            company_id, template.id, 1, "Voltage", "number", {"min": "4", "max": "6"}
        )
        template_id, check_id = template.id, check.id
        quality.publish_template(company_id, template_id)
        with pytest.raises(DomainError, match="draft"):
            quality.save_check(company_id, template_id, 2, "Extra", "text", {})
        inspection = quality.create_inspection(company_id, "I-1", lot_id, template_id)
        inspection_id = inspection.id
        with pytest.raises(DomainError, match="every check"):
            quality.complete_inspection(company_id, inspection_id)
        observed = quality.observe(
            company_id, inspection_id, check_id, "9", "Outside specification"
        )
        assert observed.outcome == "fail"
        quality.complete_inspection(company_id, inspection_id)
        with pytest.raises(DomainError, match="draft"):
            quality.observe(company_id, inspection_id, check_id, "5")
        assert (
            db.session.scalar(
                select(InspectionResult.outcome).where(
                    InspectionResult.inspection_id == inspection_id
                )
            )
            == "fail"
        )


def test_rule_allowlist_and_template_parent_enforced(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    lot_id = one_lot(records)
    with signed(app, company_id):
        template = quality.save_template(company_id, "T", 1)
        template_id = template.id
        with pytest.raises(DomainError, match="only min"):
            quality.save_check(company_id, template_id, 1, "Code", "text", {"eval": "bad"})
        first = quality.save_check(company_id, template_id, 1, "Code", "text", {"equals": "ok"})
        first_id = first.id
        quality.publish_template(company_id, template_id)
        other = quality.save_template(company_id, "T", 2)
        other_id = other.id
        quality.save_check(company_id, other_id, 1, "Other", "text", {})
        quality.publish_template(company_id, other_id)
        inspection = quality.create_inspection(company_id, "I-2", lot_id, other_id)
        with pytest.raises(DomainError, match="another template"):
            quality.observe(company_id, inspection.id, first_id, "ok")


def test_independent_hold_review_and_recent_mfa_required(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    grant(company_id, "auditor")
    lot_id = one_lot(records)
    with signed(app, company_id, verified=True):
        hold = quality.place_hold(company_id, lot_id, "Suspect component")
        hold_id = hold.id
        with pytest.raises(DomainError, match="different reviewer"):
            quality.review_hold(company_id, hold_id, "release", "Self review is invalid")
    with signed(app, company_id, "auditor@aurora.test"):
        with pytest.raises(Forbidden):
            quality.review_hold(company_id, hold_id, "release", "MFA missing")
    with signed(app, company_id, "auditor@aurora.test", verified=True):
        review = quality.review_hold(company_id, hold_id, "retain", "Need more evidence")
        assert review.decision == "retain"
        assert db.session.get(QualityHold, hold_id).released_at is None
        quality.review_hold(company_id, hold_id, "release", "Evidence confirms release")
        assert db.session.get(QualityHold, hold_id).released_at is not None


def test_quality_forms_require_csrf_and_hide_other_company_lots(app, records, client):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    login(client)
    page = client.get(f"/companies/{company_id}/quality/templates/new")
    assert page.status_code == 200
    assert b"csrf_token" in page.data
    assert (
        client.post(
            f"/companies/{company_id}/quality/templates/new",
            data={"code": "NO-CSRF", "revision": "1"},
        ).status_code
        == 400
    )
    with signed(app, company_id):
        with pytest.raises(NotFound):
            quality.create_inspection(
                company_id,
                "FOREIGN",
                one_lot(
                    {
                        **records,
                        "companies": {"aurora": records["companies"]["beacon"]},
                        "aurora_variants": records["beacon_variants"],
                    }
                ),
                "00000000-0000-0000-0000-000000000000",
            )


@pytest.mark.parametrize("private_state", ["export", "source", "quarantined"])
def test_private_exports_and_import_sources_cannot_be_shared_as_quality_or_case_evidence(
    app, records, private_state
):
    from app.models.evidence import Document
    from app.services import recall

    company_id = records["companies"]["aurora"]
    grant(company_id)
    lot_id = one_lot(records)
    with signed(app, company_id) as member:
        document = Document(
            organization_id=company_id,
            object_key="private-job-result",
            original_name="private.csv",
            media_type="text/csv",
            size_bytes=1,
            sha256="0" * 64,
            scan_status="clean",
            state=private_state,
            uploaded_by_id=member.id,
        )
        db.session.add(document)
        db.session.commit()
        document_id = document.id
        issue = quality.save_nonconformance(
            company_id, "PRIVATE-EVIDENCE", lot_id, "Fictional finding", "low"
        )
        issue_id = issue.id
        case = recall.save_case(
            company_id, "PRIVATE-CASE", "Document boundaries", "Fictional concern", "low"
        )
        case_id = case.id
        with pytest.raises(DomainError, match="scanned evidence"):
            quality.attach_document(company_id, document_id, nonconformance_id=issue_id)
        with pytest.raises(DomainError, match="scanned documents"):
            recall.attach_document(company_id, case_id, document_id)
