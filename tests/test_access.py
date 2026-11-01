from datetime import timedelta

import pytest
from conftest import PASSWORD, csrf, login, post_form, read_mail_token, root
from sqlalchemy import select

from app.extensions import db
from app.models import Invitation, Membership, Role, User, now


def base(records):
    return f"/companies/{records['companies']['aurora']}/access"


def role(records, code="auditor", company="aurora"):
    return db.session.scalar(
        select(Role).where(Role.organization_id == records["companies"][company], Role.code == code)
    )


def member(email):
    return db.session.scalar(select(Membership).join(User).where(User.email == email))


def issue(client, records, mail_spool, email="new-member@aurora.test"):
    response = post_form(
        client,
        base(records) + "/invitations/new",
        {"email": email, "role_id": str(role(records).id)},
    )
    assert response.status_code == 303
    return read_mail_token(mail_spool, "company invitation")


def test_invitation_accept_and_no_role_injection(client, app, owner, records, mail_spool):
    login(client, owner)
    token = issue(client, records, mail_spool)
    response = client.get(base(records))
    assert token not in response.text
    assert db.session.scalar(select(Invitation)).token_digest not in response.text
    public = app.test_client()
    payload = {
        "token": token,
        "display_name": "Fictional member",
        "password": PASSWORD,
        "role_id": str(role(records, "owner").id),
    }
    assert post_form(public, "/invitations/accept", payload).status_code == 303
    assert post_form(public, "/invitations/accept", payload).status_code == 400
    login(public, "new-member@aurora.test")
    assert public.get(root(records)).status_code == 200
    assert public.get(base(records)).status_code == 403
    assert public.get(root(records, company="beacon")).status_code == 404
    assert db.session.scalar(
        select(User).where(User.email == "new-member@aurora.test")
    ).email_verified_at


@pytest.mark.parametrize("invalid", ["expired", "revoked", "issuer_removed"])
def test_invalid_invitation(client, app, owner, records, mail_spool, invalid):
    login(client, owner)
    token = issue(client, records, mail_spool)
    invitation = db.session.scalar(select(Invitation))
    if invalid == "expired":
        invitation.expires_at = now() - timedelta(seconds=1)
    elif invalid == "revoked":
        assert (
            client.post(
                base(records) + f"/invitations/{invitation.id}/revoke",
                data={"csrf_token": csrf(client.get(base(records)))},
            ).status_code
            == 303
        )
    else:
        member(owner).status = "inactive"
    db.session.commit()
    public = app.test_client()
    assert (
        post_form(
            public,
            "/invitations/accept",
            {"token": token, "display_name": "Member", "password": PASSWORD},
        ).status_code
        == 400
    )
    assert db.session.scalar(select(User).where(User.email == "new-member@aurora.test")) is None


def test_existing_account_requires_its_own_login(client, app, owner, records, mail_spool):
    login(client, owner)
    token = issue(client, records, mail_spool, "catalog-editor@beacon.test")
    public = app.test_client()
    data = {"token": token, "display_name": "Try takeover", "password": PASSWORD}
    assert post_form(public, "/invitations/accept", data).status_code == 409
    login(public, "catalog-editor@beacon.test")
    assert post_form(public, "/invitations/accept", data).status_code == 303
    login(public, "catalog-editor@beacon.test")
    assert public.get(root(records)).status_code == 200


def test_role_form_crud_and_stale_grant_rejection(client, owner, records):
    login(client, owner)
    path = base(records) + "/roles/new"
    data = {
        "code": "viewer2",
        "name": "Limited viewer",
        "permissions": ["catalog.read"],
        "version": 0,
    }
    assert post_form(client, path, data).status_code == 303
    created = role(records, "viewer2")
    edit = base(records) + f"/roles/{created.id}/edit"
    data.update(name="Renamed viewer", version=created.version)
    assert post_form(client, edit, data).status_code == 303
    assert post_form(client, edit, data).status_code == 409
    data.update(version=role(records, "viewer2").version, permissions=["unimplemented.action"])
    assert post_form(client, edit, data).status_code == 422
    protected = role(records, "owner")
    data.update(version=protected.version, permissions=["catalog.read"], code="owner-renamed")
    assert post_form(client, base(records) + f"/roles/{protected.id}/edit", data).status_code == 409


def test_last_owner_membership_and_live_revocation(client, app, owner, records):
    login(client, owner)
    own = member(owner)
    url = base(records) + f"/members/{own.id}/edit"
    assert (
        post_form(
            client,
            url,
            {"role_id": str(role(records).id), "status": "inactive", "version": own.version},
        ).status_code
        == 409
    )
    editor = app.test_client()
    login(editor)
    target = member("catalog-editor@aurora.test")
    url = base(records) + f"/members/{target.id}/edit"
    assert (
        post_form(
            client,
            url,
            {"role_id": str(role(records).id), "status": "active", "version": target.version},
        ).status_code
        == 303
    )
    assert editor.get(root(records)).status_code == 302
    login(editor)
    assert editor.get(root(records) + "/new").status_code == 403


def test_access_scope_and_csrf(client, owner, records, mail_spool):
    login(client)
    assert client.get(base(records)).status_code == 403
    assert post_form(client, "/login", {"email": owner, "password": PASSWORD}).status_code == 303
    assert client.get(f"/companies/{records['companies']['beacon']}/access").status_code == 404
    assert client.post(base(records) + "/invitations/new").status_code == 400
    assert (
        post_form(
            client,
            base(records) + "/invitations/new",
            {"email": "new@aurora.test", "role_id": str(role(records, company="beacon").id)},
        ).status_code
        == 422
    )
    foreign = member("catalog-editor@beacon.test")
    assert client.get(base(records) + f"/members/{foreign.id}/edit").status_code == 404


def test_owner_bootstrap_is_repeatable(app, owner, records):
    before = db.session.query(User).count()
    result = app.test_cli_runner().invoke(
        args=[
            "create-owner",
            "--company",
            "aurora",
            "--email",
            "different@aurora.test",
            "--password",
            PASSWORD,
        ]
    )
    assert result.exit_code == 0
    assert "active owner already exists" in result.output
    assert db.session.query(User).count() == before


def test_role_delete_archive_and_protected_history(client, owner, records):
    login(client, owner)
    assert (
        post_form(
            client,
            base(records) + "/roles/new",
            {
                "code": "unused",
                "name": "Unused role",
                "permissions": ["catalog.read"],
                "version": 0,
            },
        ).status_code
        == 303
    )
    unused = role(records, "unused")
    unused_id = unused.id
    url = base(records) + f"/roles/{unused_id}/delete"
    assert client.get(url).status_code == 405
    assert (
        client.post(
            url, data={"csrf_token": csrf(client.get(base(records))), "version": unused.version}
        ).status_code
        == 303
    )
    assert db.session.get(Role, unused_id) is None
    used = role(records, "auditor")
    assert (
        client.post(
            base(records) + f"/roles/{used.id}/delete",
            data={"csrf_token": csrf(client.get(base(records))), "version": used.version},
        ).status_code
        == 303
    )
    db.session.expire_all()
    assert db.session.get(Role, used.id).archived_at is not None
    protected = role(records, "owner")
    assert (
        client.post(
            base(records) + f"/roles/{protected.id}/delete",
            data={"csrf_token": csrf(client.get(base(records))), "version": protected.version},
        ).status_code
        == 409
    )


def test_two_owners_cannot_both_step_down(app, owner, records):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from flask_login import login_user
    from sqlalchemy import delete

    from app.models import MembershipRole
    from app.services.access import AccessConflict, change_membership

    second = member("catalog-editor@aurora.test")
    db.session.execute(delete(MembershipRole).where(MembershipRole.membership_id == second.id))
    db.session.add(
        MembershipRole(
            organization_id=second.organization_id,
            membership_id=second.id,
            role_id=role(records, "owner").id,
        )
    )
    db.session.commit()
    first = member(owner)
    targets = [
        (first.user_id, first.id, first.version),
        (second.user_id, second.id, second.version),
    ]
    company_id, auditor_id = second.organization_id, role(records).id
    barrier = Barrier(2)

    def step_down(target):
        with app.test_request_context():
            login_user(db.session.get(User, target[0]))
            barrier.wait(timeout=10)
            try:
                change_membership(company_id, target[1], auditor_id, "inactive", target[2])
                return "changed"
            except AccessConflict:
                db.session.rollback()
                return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(step_down, targets)) == ["blocked", "changed"]
