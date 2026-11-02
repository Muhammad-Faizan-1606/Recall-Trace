"""Notice scope, independent approval and recipient-only acknowledgement."""

from decimal import Decimal

import pytest
from conftest import login
from sqlalchemy import delete, select
from test_evidence import evidence_actor as _evidence_actor_fixture
from werkzeug.exceptions import HTTPException

from app.extensions import db
from app.models import (
    Membership,
    MembershipRole,
    Organization,
    Permission,
    Role,
    RolePermission,
    User,
    now,
)
from app.models.evidence import NoticeAcknowledgement
from app.models.master import Lot, Partner, PartnerContact, Site, StorageLocation, Warehouse
from app.models.operations import SalesOrder, SalesOrderLine, Shipment, ShipmentLine
from app.models.recall import CaseAffectedShipment, RecallCase, TraceResult, TraceRun
from app.services import notices
from app.services.business import DomainError

evidence_actor = _evidence_actor_fixture


@pytest.fixture
def notice_case(records, evidence_actor):
    company_id = records["companies"]["aurora"]
    creator = db.session.scalar(select(User).where(User.email == "catalog-editor@aurora.test"))
    member = db.session.scalar(select(Membership).where(Membership.user_id == creator.id))
    owner = db.session.scalar(select(User).where(User.email == "owner@aurora.test"))
    approver = db.session.scalar(select(Membership).where(Membership.user_id == owner.id))
    site = Site(
        organization_id=company_id,
        code="NOTICE-SITE",
        name="Notice site",
        address_text="Fictional",
        country_code="PK",
    )
    customer = Partner(
        organization_id=company_id,
        code="NOTICE-CUSTOMER",
        name="Fictional customer",
        status="active",
    )
    unrelated = Partner(
        organization_id=company_id,
        code="UNRELATED-CUSTOMER",
        name="Unrelated customer",
        status="active",
    )
    db.session.add_all([site, customer, unrelated])
    db.session.flush()
    warehouse = Warehouse(
        organization_id=company_id, code="NOTICE-WH", name="Notice warehouse", site_id=site.id
    )
    contact = PartnerContact(
        organization_id=company_id,
        partner_id=customer.id,
        name="Recipient",
        email="recipient@customer.test",
        purpose="recalls",
    )
    other_contact = PartnerContact(
        organization_id=company_id,
        partner_id=unrelated.id,
        name="Unrelated recipient",
        email="other@customer.test",
        purpose="recalls",
    )
    lot = Lot(
        organization_id=company_id, lot_code="NOTICE-LOT", variant_id=records["aurora_variants"]
    )
    order = SalesOrder(
        organization_id=company_id,
        reference="NOTICE-ORDER",
        customer_id=customer.id,
        status="draft",
        destination_snapshot={},
    )
    case = RecallCase(
        organization_id=company_id,
        reference="NOTICE-CASE",
        title="Fictional recall",
        reason="Synthetic quality concern",
        severity="high",
        status="approved",
        owner_id=member.id,
        submitted_by_id=member.id,
        approver_id=approver.id,
        approved_at=now(),
        submitted_at=now(),
    )
    db.session.add_all([warehouse, contact, other_contact, lot, order, case])
    db.session.flush()
    location = StorageLocation(
        organization_id=company_id,
        warehouse_id=warehouse.id,
        code="NOTICE-LOC",
        name="Dispatch",
        kind="storage",
    )
    line = SalesOrderLine(
        organization_id=company_id,
        sales_order_id=order.id,
        variant_id=records["aurora_variants"],
        quantity=Decimal(4),
    )
    shipment = Shipment(
        organization_id=company_id,
        reference="NOTICE-SHIP",
        sales_order_id=order.id,
        warehouse_id=warehouse.id,
        status="draft",
        dispatched_at=now(),
    )
    trace = TraceRun(
        organization_id=company_id,
        case_id=case.id,
        requested_by_id=member.id,
        direction="downstream",
        status="complete",
        trace_revision=0,
        algorithm_version="fixture",
        limits={},
        completed_at=now(),
        is_complete=True,
    )
    db.session.add_all([location, line, shipment, trace])
    db.session.flush()
    shipment_line = ShipmentLine(
        organization_id=company_id,
        shipment_id=shipment.id,
        sales_order_line_id=line.id,
        lot_id=lot.id,
        source_location_id=location.id,
        quantity=Decimal(4),
    )
    db.session.add(shipment_line)
    db.session.flush()
    db.session.add_all(
        [
            TraceResult(
                organization_id=company_id,
                trace_run_id=trace.id,
                lot_id=lot.id,
                depth=0,
                evidence_path=[str(lot.id)],
                scope_basis="conservative",
            ),
            CaseAffectedShipment(
                organization_id=company_id,
                case_id=case.id,
                trace_run_id=trace.id,
                shipment_line_id=shipment_line.id,
                quantity_dispatched=Decimal(4),
                quantity_recovered=Decimal(0),
                quantity_resolved=Decimal(0),
            ),
        ]
    )
    db.session.flush()
    order.status = "posted"
    shipment.status = "posted"
    case.approved_at = now()
    db.session.commit()
    return {
        "company": company_id,
        "case": case,
        "trace": trace,
        "contact": contact,
        "other_contact": other_contact,
        "customer": customer,
        "creator": member,
    }


def draft(scope, evidence_actor):
    with evidence_actor("catalog-editor@aurora.test"):
        return notices.create_notice(scope["company"], scope["case"].id, scope["contact"].id)


def approved(scope, evidence_actor):
    notice = draft(scope, evidence_actor)
    with evidence_actor(mfa=True):
        notices.approve_notice(scope["company"], notice.id, notice.version)
    return notice


def test_notice_recipient_scope_and_independent_mfa(notice_case, evidence_actor):
    s = notice_case
    notice = draft(s, evidence_actor)
    assert "NOTICE-SHIP" in notice.body and "UNRELATED" not in notice.body
    with evidence_actor("catalog-editor@aurora.test", mfa=True):
        with pytest.raises(DomainError, match="different eligible"):
            notices.approve_notice(s["company"], notice.id, notice.version)
    with evidence_actor():
        with pytest.raises(HTTPException) as exc:
            notices.approve_notice(s["company"], notice.id, notice.version)
        assert exc.value.code in {401, 403}
    with evidence_actor(mfa=True):
        notices.approve_notice(s["company"], notice.id, notice.version)
        assert notice.status == "approved"
        with pytest.raises(DomainError, match="unchanged draft"):
            notices.edit_notice(
                s["company"], notice.id, "Changed", "Unreviewed payload", notice.version
            )
        with pytest.raises(DomainError, match="not a customer"):
            notices.create_notice(s["company"], s["case"].id, s["other_contact"].id)


def test_stale_or_changed_recipient_blocks_queue(notice_case, evidence_actor):
    s = notice_case
    notice = approved(s, evidence_actor)
    with evidence_actor():
        s["contact"].email = "changed@customer.test"
        db.session.commit()
        with pytest.raises(DomainError, match="scope or recipient changed"):
            notices.enqueue_notice(s["company"], notice.id)
        s["contact"].email = notice.recipient_email
        # Trace snapshots are immutable; a later posting changes the company guard.
        db.session.get(Organization, s["company"]).trace_revision += 1
        db.session.commit()
        with pytest.raises(DomainError, match="changed"):
            notices.enqueue_notice(s["company"], notice.id)


def test_partner_portal_is_recipient_only_and_ack_is_not_recovery(
    notice_case, evidence_actor, client
):
    s = notice_case
    notice = approved(s, evidence_actor)
    notice.status = "sent"
    db.session.commit()
    auditor = db.session.scalar(select(User).where(User.email == "auditor@aurora.test"))
    member = db.session.scalar(select(Membership).where(Membership.user_id == auditor.id))
    member.partner_id = s["customer"].id
    portal_role = Role(organization_id=s["company"], code="portal", name="Partner portal")
    db.session.add(portal_role)
    db.session.flush()
    db.session.execute(delete(MembershipRole).where(MembershipRole.membership_id == member.id))
    db.session.add(
        MembershipRole(
            organization_id=s["company"], membership_id=member.id, role_id=portal_role.id
        )
    )
    portal_grants = {}
    for code in ("notice.read", "notice.acknowledge"):
        permission = db.session.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, description=code)
            db.session.add(permission)
            db.session.flush()
        grant = RolePermission(
            organization_id=s["company"], role_id=portal_role.id, permission_id=permission.id
        )
        db.session.add(grant)
        db.session.flush()
        portal_grants[code] = grant.id
    db.session.commit()
    login(client, "auditor@aurora.test")
    base = f"/companies/{s['company']}/notices"
    page = client.get(base)
    assert page.status_code == 200 and notice.subject in page.text
    assert client.get(base + f"/{notice.id}").status_code == 200
    with evidence_actor("auditor@aurora.test"):
        ack = notices.acknowledge(
            s["company"], notice.id, "portal", "Received in restricted portal"
        )
        assert ack.recorded_by_id == member.id
        again = notices.acknowledge(s["company"], notice.id, "portal", "repeat")
        assert again.id == ack.id
        db.session.execute(
            delete(RolePermission).where(RolePermission.id == portal_grants["notice.acknowledge"])
        )
        db.session.commit()
        with pytest.raises(HTTPException) as denied_ack:
            notices.acknowledge(s["company"], notice.id, "portal", "revoked permission")
        assert denied_ack.value.code == 403
        db.session.execute(
            delete(RolePermission).where(RolePermission.id == portal_grants["notice.read"])
        )
        db.session.commit()
        with pytest.raises(HTTPException) as denied_read:
            notices.readable(s["company"], notice.id)
        assert denied_read.value.code == 403
        # Restore only read to exercise recipient isolation independently.
        read_permission = db.session.scalar(
            select(Permission).where(Permission.code == "notice.read")
        )
        db.session.add(
            RolePermission(
                organization_id=s["company"],
                role_id=portal_role.id,
                permission_id=read_permission.id,
            )
        )
        db.session.commit()
        assert db.session.scalar(select(CaseAffectedShipment.quantity_recovered)) == Decimal(0)
        member.partner_id = s["other_contact"].partner_id
        db.session.commit()
        with pytest.raises(HTTPException) as exc:
            notices.readable(s["company"], notice.id)
        assert exc.value.code == 404
    assert db.session.scalar(select(NoticeAcknowledgement.id)) is not None


def test_resend_transport_failures_preserve_uncertainty(app, monkeypatch):
    import requests

    old = {name: app.config.get(name) for name in ["MAIL_MODE", "MAIL_API_KEY", "MAIL_FROM"]}
    app.config.update(
        MAIL_MODE="resend", MAIL_API_KEY="test-only-not-a-real-key", MAIL_FROM="sender@example.test"
    )
    try:

        def timeout(*args, **kwargs):
            raise requests.ReadTimeout("test transport timeout")

        monkeypatch.setattr(notices.requests, "post", timeout)
        assert (
            notices.send_message("recipient@example.test", "Subject", "Body", "idempotency-test")[0]
            == "ambiguous"
        )

        def connect_timeout(*args, **kwargs):
            raise requests.ConnectTimeout("test connect timeout")

        monkeypatch.setattr(notices.requests, "post", connect_timeout)
        assert notices.send_message(
            "recipient@example.test", "Subject", "Body", "idempotency-test"
        ) == ("failed", None, "provider_connect_timeout")
    finally:
        app.config.update(old)
