"""Real TOTP enrollment/replay/recovery and per-session authorization checks."""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from conftest import PASSWORD, csrf, login
from cryptography.fernet import Fernet
from flask import session
from flask_login import login_user
from sqlalchemy import select
from werkzeug.exceptions import Forbidden

from app.extensions import db
from app.models import AuthSession, User, now
from app.models.security import AuditEvent, MfaFactor
from app.services import audit, mfa


@pytest.fixture
def mfa_config(app, monkeypatch):
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setitem(app.config, "MFA_KEY_VERSION", "v1")
    monkeypatch.setattr(mfa.time, "time", lambda: 1800000000.0)


def enroll(client):
    login(client)
    page = client.get("/security/enroll")
    response = client.post(
        "/security/enroll", data={"csrf_token": csrf(page), "password": PASSWORD}
    )
    assert response.status_code == 200
    secret = re.search(r"<code>([A-Z2-7]{32})</code>", response.text).group(1)
    response = client.post(
        "/security/confirm", data={"csrf_token": csrf(response), "code": mfa.totp(secret)}
    )
    assert response.status_code == 200
    codes = re.findall(r"<code>([A-Za-z0-9_-]{24})</code>", response.text)
    assert len(codes) == 10
    return secret, codes


def test_enrollment_encryption_replay_and_one_time_recovery(client, mfa_config, records):
    secret, codes = enroll(client)
    factor = db.session.scalar(select(MfaFactor))
    assert factor.verified_at and factor.last_used_step
    assert secret not in factor.secret_ciphertext
    assert mfa.secret_for(factor) == secret
    assert all(code not in str(factor.recovery_code_hashes) for code in codes)
    assert len(factor.recovery_code_hashes) == 10
    token = csrf(client.get("/security/challenge"))
    response = client.post(
        "/security/challenge", data={"csrf_token": token, "code": mfa.totp(secret)}
    )
    assert response.status_code == 422
    assert "already used" in response.text
    response = client.post("/security/challenge", data={"csrf_token": token, "code": codes[0]})
    assert response.status_code == 303
    assert len(db.session.scalar(select(MfaFactor)).recovery_code_hashes) == 9
    response = client.post("/security/challenge", data={"csrf_token": token, "code": codes[0]})
    assert response.status_code == 422
    assert codes[0] not in response.text
    assert secret not in client.get("/security").text
    assert not db.session.scalar(select(MfaFactor)).secret_ciphertext.startswith(secret)


def test_enrolled_user_password_login_is_gated_until_mfa(client, app, mfa_config, records):
    _, codes = enroll(client)
    second = app.test_client()
    login(second)
    company_id = records["companies"]["aurora"]
    blocked = second.get(f"/companies/{company_id}/catalog/items")
    assert blocked.status_code == 303
    assert blocked.headers["Location"] == "/security/challenge"
    response = second.post(
        "/security/challenge",
        data={"csrf_token": csrf(second.get("/security/challenge")), "code": codes[0]},
    )
    assert response.status_code == 303
    assert second.get(f"/companies/{company_id}/catalog/items").status_code == 200
    # Recovery consumption revokes the other signed-in session.
    assert client.get("/").status_code == 302


def test_enrollment_requires_password_and_csrf_and_preserves_factor(client, mfa_config):
    login(client)
    assert client.post("/security/enroll", data={"password": PASSWORD}).status_code == 400
    response = client.post(
        "/security/enroll",
        data={"csrf_token": csrf(client.get("/security/enroll")), "password": "wrong"},
    )
    assert response.status_code == 422
    assert db.session.scalar(select(MfaFactor)) is None
    secret, _ = enroll(client)
    factor_id = db.session.scalar(select(MfaFactor)).id
    response = client.post(
        "/security/enroll",
        data={"csrf_token": csrf(client.get("/security/enroll")), "password": PASSWORD},
    )
    assert response.status_code == 422
    assert db.session.scalar(select(MfaFactor)).id == factor_id
    assert secret not in response.text


def test_recent_mfa_is_registry_bound_and_expires(client, app, mfa_config, records):
    enroll(client)
    with client.session_transaction() as stored:
        auth_ref = stored["auth_ref"]
    auth = db.session.scalar(
        select(AuthSession).where(AuthSession.token_digest == mfa.digest(auth_ref))
    )
    user = db.session.get(User, auth.user_id)
    with app.test_request_context():
        login_user(user)
        session["auth_ref"] = auth_ref
        mfa.require_recent_mfa(records["companies"]["aurora"])
        auth.last_mfa_at = now() - timedelta(minutes=11)
        db.session.commit()
        with pytest.raises(Forbidden):
            mfa.require_recent_mfa(records["companies"]["aurora"])


def test_disable_consumes_factor_and_revokes_all_sessions(client, mfa_config):
    _, codes = enroll(client)
    response = client.post(
        "/security/disable",
        data={
            "csrf_token": csrf(client.get("/security/disable")),
            "password": PASSWORD,
            "code": codes[0],
        },
    )
    assert response.status_code == 303
    assert db.session.scalar(select(MfaFactor)) is None
    assert all(row.revoked_at for row in db.session.scalars(select(AuthSession)))
    assert client.get("/").status_code == 302


def test_concurrent_recovery_code_consumption_only_one_wins(client, app, mfa_config):
    _, codes = enroll(client)
    with client.session_transaction() as stored:
        auth_ref = stored["auth_ref"]
    user_id = db.session.scalar(
        select(AuthSession).where(AuthSession.token_digest == mfa.digest(auth_ref))
    ).user_id
    barrier = Barrier(2)

    def consume():
        with app.app_context(), app.test_request_context():
            user = db.session.get(User, user_id)
            login_user(user)
            session["auth_ref"] = auth_ref
            barrier.wait(timeout=10)
            try:
                mfa.verify(codes[0])
                return "consumed"
            except mfa.MfaError:
                return "rejected"
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(), range(2)))
    assert sorted(results) == ["consumed", "rejected"]
    db.session.expire_all()
    assert len(db.session.scalar(select(MfaFactor)).recovery_code_hashes) == 9


def test_missing_encryption_fails_without_creating_factor(client, app, monkeypatch):
    monkeypatch.setitem(app.config, "MFA_ENCRYPTION_KEY", None)
    login(client)
    response = client.post(
        "/security/enroll",
        data={"csrf_token": csrf(client.get("/security/enroll")), "password": PASSWORD},
    )
    assert response.status_code == 422
    assert db.session.scalar(select(MfaFactor)) is None


def test_audit_actor_company_and_metadata_allowlist(app, records):
    user = db.session.scalar(select(User).where(User.email == "catalog-editor@aurora.test"))
    with app.test_request_context():
        login_user(user)
        event = audit.record(
            records["companies"]["aurora"],
            "catalog.created",
            "item",
            records["aurora_items"],
            {"count": 1},
        )
        db.session.commit()
        assert event.actor_id and event.safe_details == {"count": 1}
        with pytest.raises(ValueError, match="metadata"):
            audit.record(
                records["companies"]["aurora"],
                "bad",
                "item",
                safe_details={"password": "not permitted"},
            )
        event.action = "altered"
        with pytest.raises(ValueError, match="Audit history"):
            db.session.commit()
        db.session.rollback()
        assert db.session.get(AuditEvent, event.id).action == "catalog.created"


def test_production_access_mutation_requires_recent_mfa(
    client, app, owner, records, mfa_config, monkeypatch
):
    login(client, owner)
    company_id = records["companies"]["aurora"]
    path = f"/companies/{company_id}/access/roles/new"
    page = client.get(path)
    assert page.status_code == 200
    monkeypatch.setitem(app.config, "APP_ENV", "production")
    response = client.post(
        path,
        data={
            "csrf_token": csrf(page),
            "version": "0",
            "code": "restricted",
            "name": "Restricted",
            "permissions": ["catalog.read"],
        },
    )
    assert response.status_code == 403


def test_production_account_mail_preserves_unconfirmed_outcomes(app, monkeypatch, caplog):
    from app.services import development_mail, notices

    monkeypatch.setitem(app.config, "APP_ENV", "production")
    monkeypatch.setitem(app.config, "ACCOUNT_MAIL_DIR", "must-not-be-used")
    monkeypatch.setitem(app.config, "MAIL_MODE", "unconfigured")
    assert not development_mail.development_mail_configured()
    assert not development_mail.deliver_development_message(
        "fictional@aurora.test", "Account", "private-code"
    )
    assert development_mail._directory() is None
    monkeypatch.setitem(app.config, "MAIL_MODE", "resend")
    monkeypatch.setitem(app.config, "MAIL_API_KEY", "test-placeholder")
    monkeypatch.setitem(app.config, "MAIL_FROM", "fictional@aurora.test")
    calls = []

    def adapter(recipient, subject, body, key):
        calls.append((recipient, subject, body, key))
        return "ambiguous", None, "provider_transport_ambiguous"

    monkeypatch.setattr(notices, "send_message", adapter)
    assert development_mail.development_mail_configured()
    assert not development_mail.deliver_development_message(
        "fictional@aurora.test", "Account", "private-code"
    )
    assert "private-code" not in caplog.text
    first_key = calls[0][3]
    assert first_key.startswith("account-") and "private-code" not in first_key
    assert not development_mail.deliver_development_message(
        "fictional@aurora.test", "Account", "private-code"
    )
    assert calls[1][3] == first_key
    monkeypatch.setattr(
        notices, "send_message", lambda *args: ("sent", "synthetic-provider-id", None)
    )
    assert development_mail.deliver_development_message(
        "fictional@aurora.test", "Account", "private-code"
    )
