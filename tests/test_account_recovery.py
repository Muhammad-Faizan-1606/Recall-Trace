import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from conftest import login, post_form, read_mail_token, root
from sqlalchemy import select

from app.extensions import db
from app.models import AuthSession, EmailVerificationToken, PasswordResetToken, User, now
from app.services.account_recovery import reset_password
from app.services.auth import digest, hasher

NEW_PASSWORD = "New fictional password 7319!"


def test_reset_generic_delivery_revocation_and_replay(client, app, records, mail_spool):
    login(client)
    response = post_form(client, "/account/reset/request", {"email": "catalog-editor@aurora.test"})
    assert response.status_code == 303
    real = client.get(response.location).text
    response = post_form(client, "/account/reset/request", {"email": "absent@aurora.test"})
    assert response.status_code == 303
    assert "If this address belongs to an eligible account" in real
    assert "If this address belongs to an eligible account" in client.get(response.location).text
    token = read_mail_token(mail_spool, "password recovery")
    row = db.session.scalar(select(PasswordResetToken))
    assert row.token_digest == digest(token)
    assert token not in real
    for path in mail_spool.glob("*.json"):
        assert path.stat().st_mode & 0o777 == 0o600
    public = app.test_client()
    response = post_form(
        public,
        "/account/reset",
        {"token": token, "password": NEW_PASSWORD, "confirmation": NEW_PASSWORD},
    )
    assert response.status_code == 303
    assert token not in response.location
    assert client.get(root(records)).status_code == 302
    db.session.expire_all()
    assert all(s.revoked_at for s in db.session.scalars(select(AuthSession)))
    assert (
        post_form(
            public,
            "/account/reset",
            {"token": token, "password": NEW_PASSWORD, "confirmation": NEW_PASSWORD},
        ).status_code
        == 400
    )
    response = post_form(
        public, "/login", {"email": "catalog-editor@aurora.test", "password": NEW_PASSWORD}
    )
    assert response.status_code == 303


def test_verification_once(client, mail_spool):
    response = post_form(client, "/account/verify/request", {"email": "catalog-editor@aurora.test"})
    assert response.status_code == 303
    token = read_mail_token(mail_spool, "email verification")
    assert post_form(client, "/account/verify", {"token": token}).status_code == 303
    user = db.session.scalar(select(User).where(User.email == "catalog-editor@aurora.test"))
    assert user.email_verified_at
    assert post_form(client, "/account/verify", {"token": token}).status_code == 400


@pytest.mark.parametrize(
    "route",
    ["/account/reset/request", "/account/verify/request", "/account/reset", "/account/verify"],
)
def test_account_csrf_and_no_get_mutations(client, route):
    assert client.get(route).status_code == 200
    assert client.post(route, data={"email": "catalog-editor@aurora.test"}).status_code == 400
    assert db.session.query(PasswordResetToken).count() == 0
    assert db.session.query(EmailVerificationToken).count() == 0


def test_invalid_expired_and_superseded_codes(client, mail_spool):
    post_form(client, "/account/reset/request", {"email": "catalog-editor@aurora.test"})
    first = read_mail_token(mail_spool, "password recovery")
    post_form(client, "/account/reset/request", {"email": "catalog-editor@aurora.test"})
    second = read_mail_token(mail_spool, "password recovery")
    assert first != second
    row = db.session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_digest == digest(second))
    )
    row.expires_at = now() - timedelta(seconds=1)
    db.session.commit()
    for token in ["bad", first, second]:
        response = post_form(
            client,
            "/account/reset",
            {"token": token, "password": NEW_PASSWORD, "confirmation": NEW_PASSWORD},
        )
        assert response.status_code == 400
        assert token not in response.text if token != "bad" else True
    assert "invalid or has expired" in response.text


def test_rate_limit_and_mismatched_password(client, mail_spool):
    for _ in range(3):
        assert (
            post_form(
                client, "/account/reset/request", {"email": "catalog-editor@aurora.test"}
            ).status_code
            == 303
        )
    assert (
        post_form(
            client, "/account/reset/request", {"email": "catalog-editor@aurora.test"}
        ).status_code
        == 429
    )
    token = read_mail_token(mail_spool, "password recovery")
    assert (
        post_form(
            client,
            "/account/reset",
            {"token": token, "password": NEW_PASSWORD, "confirmation": "mismatch"},
        ).status_code
        == 422
    )
    row = db.session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_digest == digest(token))
    )
    assert row.used_at is None


def test_missing_delivery_does_not_invent_messages(client, app):
    assert app.config.get("ACCOUNT_MAIL_DIR") is None
    assert (
        post_form(
            client, "/account/reset/request", {"email": "catalog-editor@aurora.test"}
        ).status_code
        == 303
    )
    assert db.session.query(PasswordResetToken).count() == 0


def test_concurrent_reset_has_one_winner(app):
    user = db.session.scalar(select(User).where(User.email == "catalog-editor@aurora.test"))
    token = secrets.token_urlsafe(32)
    db.session.add(
        PasswordResetToken(
            user_id=user.id, token_digest=digest(token), expires_at=now() + timedelta(minutes=5)
        )
    )
    db.session.commit()
    barrier = Barrier(2)

    def consume(_):
        with app.app_context():
            barrier.wait(timeout=10)
            return reset_password(token, NEW_PASSWORD)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, range(2))) == [False, True]
    db.session.expire_all()
    assert hasher.verify(db.session.get(User, user.id).password_hash, NEW_PASSWORD)


def test_password_reset_winning_login_race_blocks_old_password(client, monkeypatch):
    from conftest import PASSWORD
    from sqlalchemy.orm import Session

    from app.services.auth import password_hash

    user = db.session.scalar(select(User).where(User.email == "catalog-editor@aurora.test"))
    user_id = user.id
    replacement = password_hash(NEW_PASSWORD)
    engine = db.engine
    original_verify = hasher.verify

    def verify_then_reset(encoded, password):
        valid = original_verify(encoded, password)
        with Session(engine) as other:
            changed = other.get(User, user_id)
            changed.password_hash = replacement
            changed.auth_version += 1
            other.commit()
        return valid

    from types import SimpleNamespace

    from app.services import auth

    monkeypatch.setattr(auth, "hasher", SimpleNamespace(verify=verify_then_reset))
    response = post_form(
        client, "/login", {"email": "catalog-editor@aurora.test", "password": PASSWORD}
    )
    assert response.status_code == 422
    assert db.session.query(AuthSession).count() == 0
