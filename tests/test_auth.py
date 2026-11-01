from datetime import timedelta

import pytest
from conftest import PASSWORD, csrf, login, post_form, root
from sqlalchemy import select

from app.extensions import db
from app.models import AuthSession, User, now


def test_login_logout_rotation_and_old_cookie_rejected(client, app, records):
    client.get("/login")
    old_anonymous = client.get_cookie("session").value
    login(client)
    authenticated_cookie = client.get_cookie("session").value
    assert authenticated_cookie != old_anonymous
    assert client.get(root(records)).status_code == 200
    token = csrf(client.get("/"))
    assert client.post("/logout", data={"csrf_token": token}).status_code == 303
    replay = app.test_client()
    replay.set_cookie("session", authenticated_cookie)
    assert replay.get(root(records)).status_code == 302
    assert db.session.scalar(select(AuthSession)).revoked_at is not None


@pytest.mark.parametrize("mutation", ["revoked", "expired", "idle", "version", "inactive"])
def test_live_registry_validation(client, records, mutation):
    login(client)
    auth = db.session.scalar(select(AuthSession))
    user = db.session.get(User, auth.user_id)
    if mutation == "revoked":
        auth.revoked_at = now()
    elif mutation == "expired":
        auth.expires_at = now() - timedelta(seconds=1)
    elif mutation == "idle":
        auth.last_seen_at = now() - timedelta(minutes=31)
    elif mutation == "version":
        user.auth_version += 1
    else:
        user.active = False
    db.session.commit()
    assert client.get(root(records)).status_code == 302


def test_csrf_and_methods(client, records):
    assert (
        client.post(
            "/login", data={"email": "catalog-editor@aurora.test", "password": PASSWORD}
        ).status_code
        == 400
    )
    login(client)
    base = root(records)
    for token in (None, "invalid"):
        data = {"code": "BAD", "name": "Bad", "kind": "component", "version": 0}
        if token:
            data["csrf_token"] = token
        assert client.post(base + "/new", data=data).status_code == 400
        assert client.post("/logout", data=data).status_code == 400
    assert client.get("/logout").status_code == 405
    assert client.get(f"{base}/{records['aurora_items']}/delete").status_code == 405
    assert client.get(base + "/not-a-uuid").status_code == 404


def test_invalid_login_generic_and_shared_limit(client, app):
    token = csrf(client.get("/login"))
    for _ in range(10):
        response = client.post(
            "/login?next=https://attacker.test",
            data={
                "csrf_token": token,
                "email": "unknown@aurora.test",
                "password": "incorrect password",
            },
        )
        assert response.status_code == 422
        assert "Invalid email or password." in response.text
        assert 'value="incorrect password"' not in response.text
    # Different browser, same shared counter; CSRF enabled in both clients.
    second = app.test_client()
    response = second.post(
        "/login",
        data={
            "csrf_token": csrf(second.get("/login")),
            "email": "catalog-editor@aurora.test",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 429


def test_no_open_redirect_and_headers(client):
    response = post_form(
        client,
        "/login?next=https://attacker.test",
        {"email": "catalog-editor@aurora.test", "password": PASSWORD},
    )
    assert response.status_code == 303
    assert response.headers["Location"] == "/"
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_seed_repeatable_without_overwrite(app):
    before = db.session.scalar(
        select(User).where(User.email == "catalog-editor@aurora.test")
    ).password_hash
    result = app.test_cli_runner().invoke(
        args=["seed-demo", "--password", "Another fictional password 818!"]
    )
    assert result.exit_code == 0
    assert "no passwords or records changed" in result.output
    db.session.expire_all()
    assert (
        db.session.scalar(
            select(User).where(User.email == "catalog-editor@aurora.test")
        ).password_hash
        == before
    )


def test_production_fails_closed():
    from app import create_app

    with pytest.raises(RuntimeError, match="Production deployment"):
        create_app(
            {
                "APP_ENV": "production",
                "SECRET_KEY": "x" * 64,
                "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://unused/unused",
            }
        )
