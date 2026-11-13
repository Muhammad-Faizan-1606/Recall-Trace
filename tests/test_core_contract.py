"""Integrated release contracts: scoped roles, immutable history and failure handling."""

import json
from pathlib import Path

import pytest
from conftest import PASSWORD, login, post_form, read_mail_token, root
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from test_quality import grant, signed

from app.core_admin import CORE_PERMISSIONS
from app.extensions import db, limiter
from app.models import Invitation, Permission, Role, RolePermission
from app.models.master import Partner
from app.models.operations import StockTransactionLine
from app.services.trace_fixture import seed_c10

FACTORY_TABLES = {
    "shift_patterns",
    "work_centers",
    "machine_classes",
    "machines",
    "machine_status_events",
    "calendar_exceptions",
    "site_transit_times",
    "styles",
    "fabric_specs",
    "operation_bulletins",
    "bulletin_operations",
    "production_orders",
    "capacity_bookings",
    "line_balances",
    "line_stations",
    "station_operations",
    "downtime_reasons",
    "output_logs",
    "downtime_events",
    "dye_batches",
    "knit_rolls",
    "cut_bundles",
    "factory_alerts",
}


def test_schema_matches_selected_72_core_models():
    schema = json.loads(
        (Path(__file__).parents[1] / "documentation/source/schema.json").read_text()
    )
    expected = {m["table"] for m in schema["models"] if m["phase"] == "Core"}
    assert len(expected) == 72
    # The 72 Core models plus exactly the Factory Suite tables (migrations f01a01 to f03a01).
    assert set(db.metadata.tables) == expected | FACTORY_TABLES


def test_limited_operational_roles_and_partner_invitation_ui(
    app, client, owner, records, mail_spool
):
    company_id = records["companies"]["aurora"]
    result = app.test_cli_runner().invoke(args=["init-business", "--company", "aurora"])
    assert result.exit_code == 0
    before = db.session.query(RolePermission).count()
    assert (
        app.test_cli_runner().invoke(args=["init-business", "--company", "aurora"]).exit_code == 0
    )
    assert db.session.query(RolePermission).count() == before
    assert set(db.session.scalars(select(Permission.code))) >= set(CORE_PERMISSIONS)
    login(client, owner)
    base = f"/companies/{company_id}/access"
    assert (
        post_form(
            client,
            base + "/roles/new",
            {
                "version": 0,
                "code": "receiver",
                "name": "Receiving clerk",
                "permissions": ["catalog.read", "inventory.receive"],
            },
        ).status_code
        == 303
    )
    assert (
        post_form(
            client,
            base + "/roles/new",
            {
                "version": 0,
                "code": "portal",
                "name": "Customer portal",
                "permissions": ["notice.read", "notice.acknowledge"],
            },
        ).status_code
        == 303
    )
    role = db.session.scalar(
        select(Role).where(Role.organization_id == company_id, Role.code == "portal")
    )
    partner = Partner(organization_id=company_id, code="PORTAL", name="Fictional customer")
    db.session.add(partner)
    db.session.commit()
    assert (
        post_form(
            client,
            base + "/invitations/new",
            {
                "email": "portal@customer.test",
                "role_id": str(role.id),
                "partner_id": str(partner.id),
            },
        ).status_code
        == 303
    )
    invitation = db.session.scalar(
        select(Invitation).where(Invitation.email == "portal@customer.test")
    )
    assert invitation.partner_id == partner.id
    public = app.test_client()
    token = read_mail_token(mail_spool, "company invitation")
    assert (
        post_form(
            public,
            "/invitations/accept",
            {
                "token": token,
                "display_name": "Fictional customer",
                "password": PASSWORD,
            },
        ).status_code
        == 303
    )
    login(public, "portal@customer.test")
    assert "Partner notices" in public.get("/").text
    assert public.get(f"/companies/{company_id}/notices").status_code == 200
    assert public.get(root(records)).status_code == 404
    # Existing partner roles cannot be broadened into internal operational access.
    assert (
        post_form(
            client,
            base + f"/roles/{role.id}/edit",
            {
                "version": role.version,
                "code": "portal",
                "name": "Try escalation",
                "permissions": ["notice.read", "inventory.receive"],
            },
        ).status_code
        == 409
    )
    read_id = db.session.scalar(select(Permission.id).where(Permission.code == "notice.read"))
    db.session.execute(
        delete(RolePermission).where(
            RolePermission.role_id == role.id, RolePermission.permission_id == read_id
        )
    )
    db.session.commit()
    assert public.get(f"/companies/{company_id}/notices").status_code == 403


def test_partner_invitation_cannot_bind_privileged_role(app, client, owner, records, mail_spool):
    company_id = records["companies"]["aurora"]
    app.test_cli_runner().invoke(args=["init-business", "--company", "aurora"])
    partner = Partner(organization_id=company_id, code="CUSTOMER", name="Customer")
    db.session.add(partner)
    db.session.commit()
    role = db.session.scalar(
        select(Role).where(Role.organization_id == company_id, Role.code == "owner")
    )
    login(client, owner)
    assert (
        post_form(
            client,
            f"/companies/{company_id}/access/invitations/new",
            {
                "email": "bad@customer.test",
                "role_id": str(role.id),
                "partner_id": str(partner.id),
            },
        ).status_code
        == 409
    )
    assert db.session.scalar(select(Invitation.id)) is None


def test_posted_history_rejects_direct_sql_rewrite(app, records):
    company_id = records["companies"]["aurora"]
    grant(company_id)
    with signed(app, company_id):
        seed_c10(company_id)
        line_id = db.session.scalar(select(StockTransactionLine.id))
        original = db.session.get(StockTransactionLine, line_id).quantity_delta
        with pytest.raises(IntegrityError, match="immutable"):
            db.session.execute(
                text("UPDATE stock_transaction_lines SET quantity_delta=999 WHERE id=:id"),
                {"id": line_id},
            )
        db.session.rollback()
        assert db.session.get(StockTransactionLine, line_id).quantity_delta == original
        with pytest.raises(IntegrityError, match="draft"):
            db.session.execute(
                text("UPDATE goods_receipts SET reference='rewrite' WHERE organization_id=:id"),
                {"id": company_id},
            )
        db.session.rollback()


def test_readiness_detects_unavailable_rate_storage(client, monkeypatch):
    monkeypatch.setattr(limiter.limiter.storage, "check", lambda: False)
    assert client.get("/health/live").json == {"status": "alive"}
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json == {"status": "unavailable"}


def test_unexpected_errors_do_not_disclose_details(app, client, caplog, monkeypatch):
    def broken():
        raise RuntimeError("private-provider-credential-example")

    login(client)
    monkeypatch.setitem(app.view_functions, "catalog.companies", broken)
    monkeypatch.setitem(app.config, "PROPAGATE_EXCEPTIONS", False)
    response = client.get("/")
    assert response.status_code == 500
    assert "private-provider-credential-example" not in response.text
    assert "private-provider-credential-example" not in caplog.text
    assert response.headers["X-Request-ID"] in response.text
