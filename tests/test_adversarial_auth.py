"""Adversarial authentication checks keep CSRF, Redis and real factors enabled."""

import re

import pytest
from conftest import PASSWORD, csrf, login, post_form
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.extensions import db, limiter
from app.models import Membership, Role, User
from app.models.security import AuditEvent
from app.services import mfa


def test_role_grants_leave_atomic_scoped_audit_history(client, owner, records):
    login(client, owner)
    company_id = records["companies"]["aurora"]
    base = f"/companies/{company_id}/access/roles"
    payload = {
        "version": "0",
        "code": "audited-role",
        "name": "Audited role",
        "permissions": ["catalog.read"],
    }
    assert post_form(client, base + "/new", payload).status_code == 303
    role = db.session.scalar(
        select(Role).where(Role.organization_id == company_id, Role.code == "audited-role")
    )
    edit = base + f"/{role.id}/edit"
    payload.update(version=str(role.version), permissions=["catalog.read", "catalog.manage"])
    assert post_form(client, edit, payload).status_code == 303
    assert post_form(client, edit, payload).status_code == 409
    events = db.session.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == role.id).order_by(AuditEvent.created_at)
    ).all()
    assert [e.action for e in events] == ["access.role.created", "access.role.updated"]
    user_id = db.session.scalar(select(User.id).where(User.email == owner))
    member_id = db.session.scalar(
        select(Membership.id).where(
            Membership.organization_id == company_id, Membership.user_id == user_id
        )
    )
    assert all(e.organization_id == company_id and e.actor_id == member_id for e in events)
    assert [e.safe_details["count"] for e in events] == [1, 2]


@pytest.mark.parametrize("code", ["١٢٣٤٥٦", "１２３４５６"])
def test_unicode_digits_are_rejected_without_server_error(client, app, monkeypatch, code):
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    login(client)
    response = client.post(
        "/security/enroll",
        data={"csrf_token": csrf(client.get("/security/enroll")), "password": PASSWORD},
    )
    secret = re.search(r"<code>([A-Z2-7]{32})</code>", response.text).group(1)
    assert (
        client.post(
            "/security/confirm", data={"csrf_token": csrf(response), "code": mfa.totp(secret)}
        ).status_code
        == 200
    )
    response = client.post(
        "/security/challenge",
        data={"csrf_token": csrf(client.get("/security/challenge")), "code": code},
    )
    assert response.status_code == 422
    assert "Invalid authenticator" in response.text


def test_rotating_ips_do_not_reset_account_password_attempt_budget(client):
    token = csrf(client.get("/login"))
    for attempt in range(10):
        response = client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "catalog-editor@aurora.test",
                "password": "Wrong password with no account access",
            },
            environ_overrides={"REMOTE_ADDR": f"192.0.2.{attempt + 1}"},
        )
        assert response.status_code == 422
    blocked = client.post(
        "/login",
        data={
            "csrf_token": token,
            "email": " CATALOG-EDITOR@AURORA.TEST ",
            "password": PASSWORD,
        },
        environ_overrides={"REMOTE_ADDR": "198.51.100.20"},
    )
    assert blocked.status_code == 429
    # A different account does not inherit the targeted account's budget.
    other = client.post(
        "/login",
        data={"csrf_token": token, "email": "auditor@aurora.test", "password": PASSWORD},
        environ_overrides={"REMOTE_ADDR": "198.51.100.21"},
    )
    assert other.status_code == 303


def test_mfa_guess_budget_survives_ip_and_endpoint_rotation(client, app, monkeypatch):
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(mfa.time, "time", lambda: 1800000000.0)
    login(client)
    response = client.post(
        "/security/enroll",
        data={"csrf_token": csrf(client.get("/security/enroll")), "password": PASSWORD},
    )
    secret = re.search(r"<code>([A-Z2-7]{32})</code>", response.text).group(1)
    confirmed = client.post(
        "/security/confirm", data={"csrf_token": csrf(response), "code": mfa.totp(secret)}
    )
    assert confirmed.status_code == 200
    limiter.reset()
    token = csrf(client.get("/security/challenge"))
    # Malformed values cannot match the TOTP/recovery formats, regardless of time.
    for attempt in range(10):
        endpoint = "/security/challenge" if attempt % 2 == 0 else "/security/disable"
        response = client.post(
            endpoint,
            data={"csrf_token": token, "code": "invalid-factor-code!", "password": PASSWORD},
            environ_overrides={"REMOTE_ADDR": f"192.0.2.{attempt + 1}"},
        )
        assert response.status_code == 422
    response = client.post(
        "/security/challenge",
        data={"csrf_token": token, "code": "invalid-factor-code!"},
        environ_overrides={"REMOTE_ADDR": "198.51.100.20"},
    )
    assert response.status_code == 429


def test_separate_sessions_share_the_same_factor_guess_budget(client, app, monkeypatch):
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    login(client)
    response = client.post(
        "/security/enroll",
        data={"csrf_token": csrf(client.get("/security/enroll")), "password": PASSWORD},
    )
    secret = re.search(r"<code>([A-Z2-7]{32})</code>", response.text).group(1)
    assert (
        client.post(
            "/security/confirm", data={"csrf_token": csrf(response), "code": mfa.totp(secret)}
        ).status_code
        == 200
    )
    second = app.test_client()
    login(second)
    limiter.reset()
    tokens = [csrf(client.get("/security/challenge")), csrf(second.get("/security/challenge"))]
    for attempt in range(11):
        index = attempt % 2
        browser = [client, second][index]
        response = browser.post(
            "/security/challenge",
            data={"csrf_token": tokens[index], "code": "invalid-factor-code!"},
            environ_overrides={"REMOTE_ADDR": f"192.0.2.{attempt + 1}"},
        )
        assert response.status_code == (429 if attempt == 10 else 422)
