from conftest import csrf, login, root
from sqlalchemy import select

from app.extensions import db
from app.models import AuthSession, User


def test_revoke_other_and_current_session(client, app, records):
    login(client)
    other = app.test_client()
    login(other)
    sessions = db.session.scalars(select(AuthSession).order_by(AuthSession.created_at)).all()
    response = client.get("/account/sessions")
    assert response.status_code == 200
    assert "This session" in response.text
    assert all(row.token_digest not in response.text for row in sessions)
    assert (
        client.post(
            f"/account/sessions/{sessions[1].id}/revoke", data={"csrf_token": csrf(response)}
        ).status_code
        == 303
    )
    assert other.get(root(records)).status_code == 302
    assert client.get(root(records)).status_code == 200
    assert (
        client.post(
            f"/account/sessions/{sessions[0].id}/revoke",
            data={"csrf_token": csrf(client.get("/account/sessions"))},
        ).status_code
        == 303
    )
    assert client.get(root(records)).status_code == 302


def test_session_scope_csrf_and_get_readonly(client, app):
    login(client)
    other = app.test_client()
    login(other, "catalog-editor@beacon.test")
    user = db.session.scalar(select(User).where(User.email == "catalog-editor@beacon.test"))
    target = db.session.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    assert str(target.id) not in client.get("/account/sessions").text
    route = f"/account/sessions/{target.id}/revoke"
    assert client.get(route).status_code == 405
    assert client.post(route).status_code == 400
    assert (
        client.post(route, data={"csrf_token": csrf(client.get("/account/sessions"))}).status_code
        == 404
    )
    assert db.session.get(AuthSession, target.id).revoked_at is None
