"""Private bytes, fail-closed scan state, atomic imports and own notifications."""

import io
from contextlib import contextmanager
from datetime import timedelta

import pytest
from conftest import csrf, login
from flask import session
from flask_login import login_user
from sqlalchemy import select
from werkzeug.exceptions import HTTPException

from app.extensions import db
from app.models import (
    AuthSession,
    Item,
    Membership,
    MembershipRole,
    Permission,
    RolePermission,
    User,
    now,
)
from app.models.evidence import Document, ImportJob, Notification
from app.models.security import MfaFactor
from app.services import evidence
from app.services.auth import digest
from app.services.business import DomainError

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"


@pytest.fixture
def evidence_actor(app, records, owner, tmp_path):
    previous = {
        key: app.config.get(key)
        for key in [
            "EVIDENCE_ROOT",
            "STORAGE_BACKEND",
            "SCANNER_ENDPOINT",
            "CLAMAV_HOST",
            "MAIL_MODE",
        ]
    }
    app.config.update(
        EVIDENCE_ROOT=str(tmp_path / "private"),
        STORAGE_BACKEND="filesystem",
        SCANNER_ENDPOINT=None,
        CLAMAV_HOST=None,
        MAIL_MODE="unconfigured",
    )
    actions = {
        "evidence.read",
        "evidence.upload",
        "reports.export",
        "notice.prepare",
        "notice.approve",
        "notice.acknowledge",
        "catalog.read",
        "catalog.manage",
    }
    company_id = records["companies"]["aurora"]
    for email in ["owner@aurora.test", "catalog-editor@aurora.test"]:
        user = db.session.scalar(select(User).where(User.email == email))
        member = db.session.scalar(
            select(Membership).where(
                Membership.user_id == user.id, Membership.organization_id == company_id
            )
        )
        role_id = db.session.scalar(
            select(MembershipRole.role_id).where(MembershipRole.membership_id == member.id)
        )
        for action in actions:
            permission = db.session.scalar(select(Permission).where(Permission.code == action))
            if permission is None:
                permission = Permission(code=action, description=action)
                db.session.add(permission)
                db.session.flush()
            if not db.session.scalar(
                select(RolePermission.id).where(
                    RolePermission.role_id == role_id, RolePermission.permission_id == permission.id
                )
            ):
                db.session.add(
                    RolePermission(
                        organization_id=company_id, role_id=role_id, permission_id=permission.id
                    )
                )
    db.session.commit()

    @contextmanager
    def as_user(email="owner@aurora.test", mfa=False):
        with app.test_request_context():
            user = db.session.scalar(select(User).where(User.email == email))
            login_user(user)
            if mfa:
                reference = "evidence-test-private-session-" + email
                session["auth_ref"] = reference
                factor = db.session.scalar(select(MfaFactor).where(MfaFactor.user_id == user.id))
                if factor is None:
                    factor = MfaFactor(
                        user_id=user.id,
                        secret_ciphertext="not-used-by-session-guard",
                        key_version="v1",
                        recovery_code_hashes=[],
                        verified_at=now(),
                    )
                    db.session.add(factor)
                auth = AuthSession(
                    user_id=user.id,
                    token_digest=digest(reference),
                    expires_at=now() + timedelta(hours=8),
                    last_seen_at=now(),
                    auth_version=user.auth_version,
                    last_mfa_at=now(),
                )
                previous_auth = db.session.scalar(
                    select(AuthSession).where(AuthSession.token_digest == digest(reference))
                )
                if previous_auth:
                    previous_auth.last_mfa_at = now()
                else:
                    db.session.add(auth)
                db.session.commit()
            yield user
            db.session.rollback()

    yield as_user
    app.config.update(previous)


def test_missing_scanner_quarantines_bytes_and_blocks_download(records, evidence_actor):
    company_id = records["companies"]["aurora"]
    with evidence_actor():
        row = evidence.upload(company_id, "report.pdf", io.BytesIO(PDF))
        assert (row.scan_status, row.state) == ("unavailable", "quarantined")
        assert evidence.read_bytes(row) == PDF
        with pytest.raises(HTTPException) as exc:
            evidence.downloadable(company_id, row.id)
        assert exc.value.code == 404


def test_clean_scan_download_integrity_and_tenant_scope(records, evidence_actor, monkeypatch):
    company_id = records["companies"]["aurora"]
    monkeypatch.setattr(evidence, "scan_bytes", lambda data: "clean")
    with evidence_actor():
        row = evidence.upload(company_id, "../../report.pdf", io.BytesIO(PDF))
        assert row.original_name == "report.pdf"
        assert evidence.downloadable(company_id, row.id)[1] == PDF
        foreign = records["companies"]["beacon"]
        with pytest.raises(HTTPException) as exc:
            evidence.downloadable(foreign, row.id)
        assert exc.value.code == 404
        path = evidence._storage_root() / row.object_key
        path.write_bytes(b"changed")
        with pytest.raises(DomainError, match="integrity"):
            evidence.downloadable(company_id, row.id)


def test_reject_mismatched_or_oversized_upload(records, evidence_actor):
    company_id = records["companies"]["aurora"]
    with evidence_actor():
        for name, content in [
            ("image.png", b"<script>alert(1)</script>"),
            ("image.svg", PDF),
            ("huge.pdf", b"x" * (evidence.MAX_BYTES + 1)),
        ]:
            with pytest.raises(DomainError):
                evidence.upload(company_id, name, io.BytesIO(content))
        assert db.session.scalar(select(Document.id)) is None


def test_import_preview_and_idempotent_commit(records, evidence_actor):
    company_id = records["companies"]["aurora"]
    data = b"code,name,kind\nIMPORT-1,Imported switch,component\nIMPORT-2,Imported lamp,finished\n"
    with evidence_actor():
        job = evidence.prepare_import(
            company_id, "items.csv", io.BytesIO(data), "import_identifier_12345"
        )
        assert job.status == "validated" and job.row_count == 2
        assert not db.session.scalar(select(Item.id).where(Item.code == "IMPORT-1"))
        same = evidence.prepare_import(
            company_id, "items.csv", io.BytesIO(data), "import_identifier_12345"
        )
        assert same.id == job.id
        evidence.commit_import(company_id, job.id)
        evidence.commit_import(company_id, job.id)
        assert (
            len(
                db.session.scalars(
                    select(Item).where(Item.code.in_(["IMPORT-1", "IMPORT-2"]))
                ).all()
            )
            == 2
        )
        assert job.status == "committed"
        with pytest.raises(DomainError, match="another payload"):
            evidence.prepare_import(
                company_id,
                "items.csv",
                io.BytesIO(data.replace(b"switch", b"SWITCH")),
                "import_identifier_12345",
            )


def test_import_revalidates_all_rows_and_rolls_back_whole_batch(records, evidence_actor):
    company_id = records["companies"]["aurora"]
    with evidence_actor():
        with pytest.raises(DomainError):
            evidence.prepare_import(
                company_id,
                "invalid.csv",
                io.BytesIO(b"code,name,kind\nOK,Good,component\nBAD,Wrong,invalid\n"),
                "invalid_identifier_123",
            )
        assert db.session.scalar(select(ImportJob.id)) is None
        data = b"code,name,kind\nBATCH-1,First,component\nBATCH-2,Second,finished\n"
        job = evidence.prepare_import(
            company_id, "items.csv", io.BytesIO(data), "atomic_identifier_12345"
        )
        db.session.add(
            Item(
                organization_id=company_id, code="BATCH-2", name="Competing insert", kind="finished"
            )
        )
        db.session.commit()
        with pytest.raises(DomainError, match="entire import"):
            evidence.commit_import(company_id, job.id)
        assert db.session.scalar(select(Item.id).where(Item.code == "BATCH-1")) is None
        assert db.session.get(ImportJob, job.id).status == "validated"


def test_export_formula_escaping_expiry_and_owner(records, evidence_actor):
    company_id = records["companies"]["aurora"]
    with evidence_actor():
        db.session.add(
            Item(organization_id=company_id, code="FORMULA", name="=HYPERLINK(1)", kind="component")
        )
        db.session.commit()
        job = evidence.create_export(company_id)
        document, data = evidence.downloadable(company_id, job.output_document_id)
        assert b"'=HYPERLINK(1)" in data
        assert document.state == "export"
    with evidence_actor("catalog-editor@aurora.test"):
        with pytest.raises(HTTPException) as exc:
            evidence.downloadable(company_id, job.output_document_id)
        assert exc.value.code == 404
    with evidence_actor():
        job.expires_at = now() - timedelta(seconds=1)
        db.session.commit()
        with pytest.raises(HTTPException):
            evidence.downloadable(company_id, job.output_document_id)


def test_notifications_preferences_and_own_only(records, evidence_actor):
    company_id = records["companies"]["aurora"]
    with evidence_actor() as user:
        member = db.session.scalar(select(Membership).where(Membership.user_id == user.id))
        evidence.set_preference(company_id, "export", False)
        assert evidence.notify(company_id, member.id, "export", {"message": "suppressed"}) is None
        evidence.set_preference(company_id, "export", True)
        row = evidence.notify(company_id, member.id, "export", {"message": "private"})
        db.session.commit()
        own_id = row.id
        evidence.mark_notification(company_id, own_id)
        assert row.read_at is not None
    with evidence_actor("catalog-editor@aurora.test"):
        with pytest.raises(HTTPException) as exc:
            evidence.mark_notification(company_id, own_id)
        assert exc.value.code == 404
    assert db.session.scalar(select(Notification.id)) == own_id


def test_evidence_html_requires_csrf_and_clean_download(
    app, records, evidence_actor, client, monkeypatch
):
    company_id = records["companies"]["aurora"]
    login(client, "owner@aurora.test")
    base = f"/companies/{company_id}/evidence"
    assert (
        client.post(base + "/upload", data={"file": (io.BytesIO(PDF), "doc.pdf")}).status_code
        == 400
    )
    page = client.get(base)
    assert page.status_code == 200
    monkeypatch.setattr(evidence, "scan_bytes", lambda data: "clean")
    response = client.post(
        base + "/upload", data={"csrf_token": csrf(page), "file": (io.BytesIO(PDF), "doc.pdf")}
    )
    assert response.status_code == 303
    detail = client.get(response.location)
    assert detail.status_code == 200 and "Download evidence" in detail.text
    row = db.session.scalar(select(Document).where(Document.original_name == "doc.pdf"))
    download = client.get(base + f"/{row.id}/download")
    assert download.data == PDF
    assert download.headers["Content-Disposition"].startswith("attachment;")


def test_remote_storage_rejects_unverified_public_bucket(app, evidence_actor, monkeypatch):
    previous = {
        key: app.config.get(key)
        for key in ("SUPABASE_URL", "SUPABASE_STORAGE_BUCKET", "SUPABASE_SERVICE_KEY")
    }
    app.config.update(
        SUPABASE_URL="https://fictional-project.supabase.co",
        SUPABASE_STORAGE_BUCKET="evidence",
        SUPABASE_SERVICE_KEY="unit-test-placeholder",
    )

    class PublicBucket:
        def raise_for_status(self):
            pass

        def json(self):
            return {"public": True}

    monkeypatch.setattr(evidence.requests, "get", lambda *args, **kwargs: PublicBucket())
    try:
        with pytest.raises(DomainError, match="private"):
            evidence._storage_url("safe-key")
    finally:
        app.config.update(previous)
