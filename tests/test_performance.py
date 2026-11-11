"""Speed work must not weaken session, authorization or caching guarantees."""

from datetime import timedelta

from conftest import login, root
from sqlalchemy import delete, select

from app.extensions import db
from app.models import (
    AuthSession,
    Membership,
    MembershipRole,
    Permission,
    RolePermission,
    User,
    now,
)
from app.policies import allowed
from app.services.business import company_lock


def test_static_assets_are_versioned_cacheable_and_sessionless(client, records):
    login(client)
    page = client.get(root(records)).text
    assert "/static/app.css?v=" in page
    href = page.split('href="/static/app.css?v=', 1)[1].split('"', 1)[0]
    response = client.get(f"/static/app.css?v={href}")
    assert response.status_code == 200
    assert "immutable" in response.headers["Cache-Control"]
    assert "max-age=31536000" in response.headers["Cache-Control"]
    assert "Set-Cookie" not in response.headers
    stale = client.get("/static/app.css?v=not-the-current-hash")
    assert "immutable" not in stale.headers["Cache-Control"]


def test_pages_stay_private_and_report_timing(client, records):
    login(client)
    response = client.get(root(records))
    assert response.headers["Cache-Control"] == "no-store"
    timing = response.headers["Server-Timing"]
    for metric in ("db;dur=", "db-connect;dur=", "redis;dur=", "app;dur=", "total;dur="):
        assert metric in timing
    assert "SELECT" not in timing


def test_activity_is_recorded_at_most_once_a_minute(client, records):
    login(client)
    auth = db.session.scalar(select(AuthSession))
    recent = now() - timedelta(seconds=20)
    auth.last_seen_at = recent
    db.session.commit()
    assert client.get(root(records)).status_code == 200
    db.session.expire_all()
    assert db.session.get(AuthSession, auth.id).last_seen_at == recent

    stale = now() - timedelta(minutes=5)
    auth = db.session.get(AuthSession, auth.id)
    auth.last_seen_at = stale
    db.session.commit()
    assert client.get(root(records)).status_code == 200
    db.session.expire_all()
    assert db.session.get(AuthSession, auth.id).last_seen_at > stale


def test_cached_authorization_is_reread_under_the_company_lock(app, records):
    from flask_login import login_user

    company_id = records["companies"]["aurora"]
    with app.test_request_context():
        user = db.session.scalar(select(User).where(User.email == "catalog-editor@aurora.test"))
        login_user(user)
        assert allowed(company_id, "catalog.manage")
        membership = db.session.scalar(
            select(Membership).where(
                Membership.organization_id == company_id, Membership.user_id == user.id
            )
        )
        role_ids = select(MembershipRole.role_id).where(
            MembershipRole.membership_id == membership.id
        )
        permission_id = db.session.scalar(
            select(Permission.id).where(Permission.code == "catalog.manage")
        )
        # Revoke inside the same transaction; a cached answer must not survive the lock.
        db.session.execute(
            delete(RolePermission).where(
                RolePermission.role_id.in_(role_ids),
                RolePermission.permission_id == permission_id,
            )
        )
        assert allowed(company_id, "catalog.manage"), "cached within one unlocked read"
        company_lock(company_id)
        assert not allowed(company_id, "catalog.manage")
        db.session.rollback()
