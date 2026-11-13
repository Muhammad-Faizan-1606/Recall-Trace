import uuid

import pytest
from conftest import csrf, login, post_form, root
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Item, ItemVariant, Membership, MembershipRole, Role, UnitsOfMeasure, User


@pytest.mark.parametrize(
    "kind,values,model,label",
    [
        (
            "items",
            {"code": "SWITCH", "name": "Switch <script>alert(1)</script>", "kind": "component"},
            Item,
            "name",
        ),
        (
            "units",
            {"code": "KG", "name": "Kilogram", "dimension": "mass", "decimal_places": 3},
            UnitsOfMeasure,
            "name",
        ),
        (
            "variants",
            {"sku": "LAMP-02", "revision": "B", "description": "Second version"},
            ItemVariant,
            "description",
        ),
    ],
)
def test_complete_crud_prg_repeat_and_stale_edit(client, records, kind, values, model, label):
    login(client)
    base = root(records, kind)
    if kind == "variants":
        values = dict(
            values, item_id=str(records["aurora_items"]), base_unit_id=str(records["aurora_units"])
        )
    payload = dict(values, version=0)
    response = post_form(client, base + "/new", payload)
    assert response.status_code == 303
    location = response.headers["Location"]
    assert "Record saved." in client.get(location).text
    if kind == "items":
        assert "<script>alert(1)</script>" not in client.get(location).text
        assert "&lt;script&gt;" in client.get(location).text
    assert client.get(location).status_code == 200  # Refresh is a GET, not a second mutation.
    assert post_form(client, base + "/new", payload).status_code == 409
    row = db.session.scalar(
        select(model).where(
            model.organization_id == records["companies"]["aurora"],
            getattr(model, "sku" if kind == "variants" else "code")
            == values.get("sku", values.get("code")),
        )
    )
    record_id = row.id
    assert (
        db.session.query(model).filter_by(organization_id=records["companies"]["aurora"]).count()
        == 2
    )
    updated = dict(values, version=row.version)
    updated[label] = "Updated catalog value"
    response = post_form(client, location + "/edit", updated)
    assert response.status_code == 303
    assert "Updated catalog value" in client.get(location).text
    assert post_form(client, location + "/edit", updated).status_code == 409
    db.session.expire_all()
    version = db.session.get(model, record_id).version
    assert (
        client.post(
            location + "/delete",
            data={"csrf_token": csrf(client.get(location)), "version": version - 1},
        ).status_code
        == 409
    )
    assert db.session.get(model, record_id) is not None
    response = client.post(
        location + "/delete", data={"csrf_token": csrf(client.get(location)), "version": version}
    )
    assert response.status_code == 303
    assert client.get(location).status_code == 404
    assert db.session.get(model, record_id) is None
    assert (
        client.post(
            location + "/delete", data={"csrf_token": csrf(client.get(base)), "version": version}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "kind,values",
    [
        ("items", {"code": " ", "name": " ", "kind": "untrusted"}),
        ("items", {"code": "X" * 41, "name": "Long", "kind": "component"}),
        ("units", {"code": "G", "name": "Gram", "dimension": "mass", "decimal_places": 7}),
        ("units", {"code": "G", "name": "Gram", "dimension": "mass", "decimal_places": -1}),
        (
            "variants",
            {
                "sku": "NEW",
                "revision": "A",
                "item_id": str(uuid.uuid4()),
                "base_unit_id": str(uuid.uuid4()),
            },
        ),
    ],
)
def test_server_validation(client, records, kind, values):
    login(client)
    before = db.session.query(
        {"items": Item, "units": UnitsOfMeasure, "variants": ItemVariant}[kind]
    ).count()
    response = post_form(client, root(records, kind) + "/new", dict(values, version=0))
    assert response.status_code == 422
    assert "Please correct" in response.text
    assert (
        db.session.query(
            {"items": Item, "units": UnitsOfMeasure, "variants": ItemVariant}[kind]
        ).count()
        == before
    )


@pytest.mark.parametrize("kind", ["items", "units", "variants"])
def test_foreign_reads_writes_and_company_denied(client, records, kind):
    login(client)
    base = root(records, kind)
    foreign_id = records[f"beacon_{kind}"]
    location = f"{base}/{foreign_id}"
    assert client.get(location).status_code == 404
    assert client.get(location + "/edit").status_code == 404
    assert (
        client.post(
            location + "/edit", data={"csrf_token": csrf(client.get(base)), "version": 1}
        ).status_code
        == 404
    )
    assert (
        client.post(
            location + "/delete", data={"version": 1, "csrf_token": csrf(client.get(base))}
        ).status_code
        == 404
    )
    assert client.get(root(records, kind, "beacon")).status_code == 404
    assert "Beacon" not in client.get("/").text


@pytest.mark.parametrize("parent", ["item_id", "base_unit_id"])
def test_foreign_parent_form_and_database_constraints(client, records, parent):
    login(client)
    values = {
        "sku": "BAD",
        "revision": "A",
        "version": 0,
        "item_id": str(records["aurora_items"]),
        "base_unit_id": str(records["aurora_units"]),
    }
    values[parent] = str(records["beacon_items" if parent == "item_id" else "beacon_units"])
    assert post_form(client, root(records, "variants") + "/new", values).status_code == 422
    values.pop("version")
    db.session.add(
        ItemVariant(
            organization_id=records["companies"]["aurora"],
            **{k: uuid.UUID(v) if k.endswith("_id") else v for k, v in values.items()},
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.parametrize("kind", ["items", "units", "variants"])
def test_readonly_direct_mutations_denied(client, records, kind):
    login(client, "auditor@aurora.test")
    base = root(records, kind)
    assert client.get(base).status_code == 200
    assert "New record" not in client.get(base).text
    token = csrf(client.get(base))
    assert client.post(base + "/new", data={"csrf_token": token, "version": 0}).status_code == 403
    location = f"{base}/{records[f'aurora_{kind}']}"
    assert client.get(location).status_code == 200
    assert (
        client.post(location + "/edit", data={"csrf_token": token, "version": 1}).status_code == 403
    )
    assert (
        client.post(location + "/delete", data={"csrf_token": token, "version": 1}).status_code
        == 403
    )


@pytest.mark.parametrize("kind", ["items", "units"])
def test_referenced_record_archives_and_remains_readable(client, records, kind):
    login(client)
    location = f"{root(records, kind)}/{records[f'aurora_{kind}']}"
    response = client.post(
        location + "/delete", data={"csrf_token": csrf(client.get(location)), "version": 1}
    )
    assert response.status_code == 303
    assert "Archived" in client.get(location).text
    variant = f"{root(records, 'variants')}/{records['aurora_variants']}"
    assert client.get(variant).status_code == 200
    values = {
        "sku": "NEW",
        "revision": "A",
        "version": 0,
        "item_id": str(records["aurora_items"]),
        "base_unit_id": str(records["aurora_units"]),
    }
    assert post_form(client, root(records, "variants") + "/new", values).status_code == 422


def test_referenced_unit_semantics_protected(client, records):
    login(client)
    location = f"{root(records, 'units')}/{records['aurora_units']}"
    assert (
        post_form(
            client,
            location + "/edit",
            {"code": "EA", "name": "Each", "dimension": "mass", "decimal_places": 2, "version": 1},
        ).status_code
        == 409
    )
    assert db.session.get(UnitsOfMeasure, records["aurora_units"]).dimension == "count"


def test_live_membership_and_partner_scope(client, records):
    login(client)
    user = db.session.scalar(select(User).where(User.email == "catalog-editor@aurora.test"))
    membership = db.session.scalar(select(Membership).where(Membership.user_id == user.id))
    from app.models.master import Partner

    partner = Partner(organization_id=membership.organization_id, code="LIMITED", name="Partner")
    db.session.add(partner)
    db.session.flush()
    membership.partner_id = partner.id
    db.session.commit()
    assert client.get(root(records)).status_code == 404
    membership.partner_id = None
    membership.status = "inactive"
    db.session.commit()
    assert client.get(root(records)).status_code == 404


def test_permission_revoked_live(client, records):
    login(client)
    role = db.session.scalar(
        select(Role).where(
            Role.organization_id == records["companies"]["aurora"], Role.code == "catalog-editor"
        )
    )
    role.archived_at = db.func.now()
    db.session.commit()
    assert client.get(root(records)).status_code == 403


def test_association_company_constraint(records):
    member = db.session.scalar(
        select(Membership).where(Membership.organization_id == records["companies"]["aurora"])
    )
    role = db.session.scalar(
        select(Role).where(Role.organization_id == records["companies"]["beacon"])
    )
    db.session.add(
        MembershipRole(
            organization_id=member.organization_id, membership_id=member.id, role_id=role.id
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_migration_inventory_and_clean_drift(app):
    assert len(db.metadata.tables) == 83  # 72 Core + 11 Factory Suite
    assert set(inspect(db.engine).get_table_names()) == set(db.metadata.tables) | {
        "alembic_version"
    }
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with db.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), db.metadata) == []
