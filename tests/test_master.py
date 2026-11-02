"""PostgreSQL-backed master data workflows with the actual CSRF/session controls."""

import uuid

import pytest
from conftest import csrf, login, post_form
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.extensions import db
from app.models import (
    Item,
    ItemVariant,
    Membership,
    Permission,
    Role,
    RolePermission,
    UnitsOfMeasure,
    User,
)
from app.models.master import (
    ItemCategory,
    Lot,
    Partner,
    PartnerRoleAssignment,
    Site,
    StorageLocation,
    Warehouse,
)
from app.models.operations import StockBalance
from app.services.master import MODELS


@pytest.fixture
def master_graph(records):
    company_id = records["companies"]["aurora"]
    site = Site(
        organization_id=company_id,
        code="HQ",
        name="Factory",
        address_text="Fictional street",
        country_code="PK",
    )
    partner = Partner(organization_id=company_id, code="PARTNER", name="Fictional supplier")
    category = ItemCategory(organization_id=company_id, code="COMPONENTS", name="Components")
    db.session.add_all([site, partner, category])
    db.session.flush()
    warehouse = Warehouse(
        organization_id=company_id, code="WH", name="Main warehouse", site_id=site.id
    )
    role = PartnerRoleAssignment(
        organization_id=company_id, partner_id=partner.id, role_code="supplier"
    )
    db.session.add_all([warehouse, role])
    db.session.flush()
    location = StorageLocation(
        organization_id=company_id,
        code="BIN",
        name="Main bin",
        kind="storage",
        warehouse_id=warehouse.id,
    )
    lot = Lot(
        organization_id=company_id,
        lot_code="START",
        variant_id=records["aurora_variants"],
        supplier_id=partner.id,
    )
    db.session.add_all([location, lot])
    db.session.commit()
    return {
        "site": site.id,
        "warehouse": warehouse.id,
        "location": location.id,
        "partner": partner.id,
        "category": category.id,
        "lot": lot.id,
        "role": role.id,
    }


def base(records, resource):
    return f"/companies/{records['companies']['aurora']}/master/{resource}"


def values(resource, records, graph):
    return {
        "sites": {
            "code": "SECOND",
            "name": "Second site",
            "address_text": "Synthetic address",
            "country_code": "pk",
        },
        "partners": {"code": "NEW-PARTNER", "name": "Synthetic partner", "status": "active"},
        "partner-roles": {"partner_id": str(graph["partner"]), "role_code": "customer"},
        "contacts": {
            "partner_id": str(graph["partner"]),
            "name": "Synthetic contact",
            "email": "contact@supplier.test",
            "phone": "",
            "purpose": "recall",
        },
        "addresses": {
            "partner_id": str(graph["partner"]),
            "label": "Delivery",
            "address_text": "Fictional delivery address",
            "country_code": "PK",
        },
        "categories": {
            "code": "NEW-CAT",
            "name": "New category",
            "parent_id": str(graph["category"]),
        },
        "classifications": {
            "item_id": str(records["aurora_items"]),
            "category_id": str(graph["category"]),
        },
        "supplier-items": {
            "partner_id": str(graph["partner"]),
            "variant_id": str(records["aurora_variants"]),
            "supplier_sku": "SUP-1",
            "lead_time_days": "5",
        },
        "warehouses": {"code": "WH-2", "name": "Second warehouse", "site_id": str(graph["site"])},
        "locations": {
            "code": "BIN-2",
            "name": "Second bin",
            "kind": "storage",
            "warehouse_id": str(graph["warehouse"]),
        },
        "lots": {
            "lot_code": "NEW-LOT",
            "variant_id": str(records["aurora_variants"]),
            "supplier_id": str(graph["partner"]),
            "supplier_lot_code": "SUP-LOT",
            "manufactured_at": "2026-01-01T12:00",
            "expires_on": "2027-01-01",
        },
        "carriers": {
            "code": "LOCAL",
            "name": "Fictional courier",
            "tracking_url_template": "https://carrier.test/track/{tracking}",
        },
    }[resource]


@pytest.mark.parametrize("resource", tuple(MODELS))
def test_master_workflow_creates_reads_edits_and_deletes(client, records, master_graph, resource):
    login(client)
    payload = dict(values(resource, records, master_graph), version=0)
    response = post_form(client, base(records, resource) + "/new", payload)
    assert response.status_code == 303, response.text
    detail_url = response.headers["Location"]
    page = client.get(detail_url)
    assert page.status_code == 200
    record_id = uuid.UUID(detail_url.rsplit("/", 1)[-1])
    row = db.session.get(MODELS[resource], record_id)
    edit = dict(payload, version=row.version)
    if "name" in edit:
        edit["name"] = "Edited fictional record"
    elif resource == "partner-roles":
        edit["role_code"] = "distributor"
    elif resource == "addresses":
        edit["label"] = "Revised delivery"
    elif resource == "supplier-items":
        edit["supplier_sku"] = "SUP-2"
    elif resource == "lots":
        edit["supplier_lot_code"] = "SUP-LOT-REVISED"
    response = post_form(client, detail_url + "/edit", edit)
    assert response.status_code == 303, response.text
    db.session.expire_all()
    row = db.session.get(MODELS[resource], record_id)
    response = client.post(
        detail_url + "/delete",
        data={"csrf_token": csrf(client.get(detail_url)), "version": row.version},
    )
    assert response.status_code == 303, response.text
    assert client.get(detail_url).status_code == 404


def test_master_csrf_scope_permissions_and_database_tenant_fk(client, records, master_graph):
    login(client)
    url = base(records, "sites")
    assert (
        client.post(
            url + "/new", data=dict(values("sites", records, master_graph), version=0)
        ).status_code
        == 400
    )
    foreign_url = f"/companies/{records['companies']['beacon']}/master/sites"
    assert client.get(foreign_url).status_code == 404
    foreign_site = Site(
        organization_id=records["companies"]["beacon"],
        code="FOREIGN",
        name="Foreign site",
        address_text="Synthetic",
        country_code="PK",
    )
    db.session.add(foreign_site)
    db.session.commit()
    assert client.get(url + f"/{foreign_site.id}").status_code == 404
    payload = dict(
        values("warehouses", records, master_graph), site_id=str(foreign_site.id), version=0
    )
    assert post_form(client, base(records, "warehouses") + "/new", payload).status_code == 422
    db.session.add(
        Warehouse(
            organization_id=records["companies"]["aurora"],
            code="ILLEGAL",
            name="Bad warehouse",
            site_id=foreign_site.id,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    other_client = client.application.test_client()
    login(other_client, "auditor@aurora.test")
    assert other_client.get(url).status_code == 200
    assert "New record" not in other_client.get(url).text
    assert (
        other_client.post(
            url + "/new",
            data=dict(
                values("sites", records, master_graph),
                version=0,
                csrf_token=csrf(other_client.get(url)),
            ),
        ).status_code
        == 403
    )


def test_category_cycle_duplicate_and_stale_edit_rejected(client, records, master_graph):
    login(client)
    parent_url = base(records, "categories") + f"/{master_graph['category']}"
    response = post_form(
        client,
        base(records, "categories") + "/new",
        dict(values("categories", records, master_graph), version=0),
    )
    assert response.status_code == 303
    child_id = response.headers["Location"].rsplit("/", 1)[-1]
    cycle = {"version": 1, "code": "COMPONENTS", "name": "Components", "parent_id": child_id}
    assert post_form(client, parent_url + "/edit", cycle).status_code == 409
    db.session.expire_all()
    assert db.session.get(ItemCategory, master_graph["category"]).parent_id is None
    payload = dict(values("sites", records, master_graph), version=0)
    created = post_form(client, base(records, "sites") + "/new", payload)
    assert created.status_code == 303
    assert post_form(client, base(records, "sites") + "/new", payload).status_code == 409
    payload.update(version=1, name="Changed")
    assert post_form(client, created.headers["Location"] + "/edit", payload).status_code == 303
    assert post_form(client, created.headers["Location"] + "/edit", payload).status_code == 409


def test_referenced_site_archives_and_supplier_role_cannot_be_removed(
    client, records, master_graph
):
    login(client)
    site_url = base(records, "sites") + f"/{master_graph['site']}"
    response = client.post(
        site_url + "/delete", data={"version": 1, "csrf_token": csrf(client.get(site_url))}
    )
    assert response.status_code == 303
    assert "Archived" in client.get(site_url).text
    role_url = base(records, "partner-roles") + f"/{master_graph['role']}"
    response = client.post(
        role_url + "/delete", data={"version": 1, "csrf_token": csrf(client.get(role_url))}
    )
    assert response.status_code == 409
    assert (
        db.session.scalar(
            select(PartnerRoleAssignment).where(PartnerRoleAssignment.id == master_graph["role"])
        )
        is not None
    )


@pytest.mark.parametrize(
    "resource,override",
    [
        ("contacts", {"email": "invalid-address", "phone": ""}),
        ("contacts", {"email": "", "phone": ""}),
        ("lots", {"manufactured_at": "2027-01-02T00:00", "expires_on": "2027-01-01"}),
        ("carriers", {"tracking_url_template": "javascript:alert(1)"}),
        ("carriers", {"tracking_url_template": "https://user:password@carrier.test/{tracking}"}),
        ("supplier-items", {"lead_time_days": "-1"}),
    ],
)
def test_master_business_validation_leaves_no_record(
    client, records, master_graph, resource, override
):
    login(client)
    model = MODELS[resource]
    before = db.session.query(model).count()
    response = post_form(
        client,
        base(records, resource) + "/new",
        dict(values(resource, records, master_graph), **override, version=0),
    )
    assert response.status_code in (409, 422)
    assert db.session.query(model).count() == before


def test_live_stock_prevents_identity_rewrite_and_archiving(client, records, master_graph):
    login(client)
    db.session.add(
        StockBalance(
            organization_id=records["companies"]["aurora"],
            lot_id=master_graph["lot"],
            location_id=master_graph["location"],
            quantity=5,
        )
    )
    db.session.commit()
    lot_url = base(records, "lots") + f"/{master_graph['lot']}"
    row = db.session.get(Lot, master_graph["lot"])
    payload = {
        "version": row.version,
        "lot_code": "REWRITTEN",
        "supplier_lot_code": "",
        "variant_id": str(records["aurora_variants"]),
        "supplier_id": str(master_graph["partner"]),
        "manufactured_at": "",
        "expires_on": "",
    }
    assert post_form(client, lot_url + "/edit", payload).status_code == 409
    for resource, key in [
        ("lots", "lot"),
        ("locations", "location"),
        ("warehouses", "warehouse"),
        ("sites", "site"),
    ]:
        row = db.session.get(MODELS[resource], master_graph[key])
        url = base(records, resource) + f"/{row.id}"
        response = client.post(
            url + "/delete", data={"csrf_token": csrf(client.get(url)), "version": row.version}
        )
        assert response.status_code == 409
        db.session.expire_all()
        assert db.session.get(MODELS[resource], master_graph[key]).archived_at is None


@pytest.mark.parametrize("field", ["sku", "revision", "item_id", "base_unit_id"])
def test_lot_variant_identity_is_frozen(client, records, master_graph, field):
    login(client)
    company_id = records["companies"]["aurora"]
    alternative_item = Item(
        organization_id=company_id, code="OTHER", name="Other item", kind="finished"
    )
    alternative_unit = UnitsOfMeasure(
        organization_id=company_id, code="BOX", name="Box", dimension="count", decimal_places=0
    )
    db.session.add_all([alternative_item, alternative_unit])
    db.session.commit()
    variant = db.session.get(ItemVariant, records["aurora_variants"])
    original = getattr(variant, field)
    payload = {
        "sku": variant.sku,
        "revision": variant.revision,
        "description": variant.description,
        "item_id": str(variant.item_id),
        "base_unit_id": str(variant.base_unit_id),
        "version": variant.version,
    }
    payload[field] = {
        "sku": "DIFFERENT-SKU",
        "revision": "Z",
        "item_id": str(alternative_item.id),
        "base_unit_id": str(alternative_unit.id),
    }[field]
    path = f"/companies/{company_id}/catalog/variants/{variant.id}"
    assert post_form(client, path + "/edit", payload).status_code == 409
    db.session.expire_all()
    assert getattr(db.session.get(ItemVariant, variant.id), field) == original


def test_lot_variant_description_remains_editable_and_delete_archives(
    client, records, master_graph
):
    login(client)
    company_id = records["companies"]["aurora"]
    variant = db.session.get(ItemVariant, records["aurora_variants"])
    path = f"/companies/{company_id}/catalog/variants/{variant.id}"
    payload = {
        "sku": variant.sku,
        "revision": variant.revision,
        "description": "A clarified description",
        "item_id": str(variant.item_id),
        "base_unit_id": str(variant.base_unit_id),
        "version": variant.version,
    }
    assert post_form(client, path + "/edit", payload).status_code == 303
    db.session.expire_all()
    row = db.session.get(ItemVariant, variant.id)
    assert row.description == "A clarified description"
    assert (
        client.post(
            path + "/delete", data={"version": row.version, "csrf_token": csrf(client.get(path))}
        ).status_code
        == 303
    )
    db.session.expire_all()
    assert db.session.get(ItemVariant, variant.id).archived_at is not None
    assert db.session.get(Lot, master_graph["lot"]).variant_id == variant.id
    assert client.get(path).status_code == 200


def test_item_kind_cannot_reclassify_existing_lots(client, records, master_graph):
    login(client)
    company_id = records["companies"]["aurora"]
    item = db.session.get(Item, records["aurora_items"])
    path = f"/companies/{company_id}/catalog/items/{item.id}"
    payload = {"version": item.version, "code": item.code, "name": item.name, "kind": "component"}
    assert post_form(client, path + "/edit", payload).status_code == 409
    db.session.expire_all()
    assert db.session.get(Item, item.id).kind == "finished"
    payload["kind"] = "finished"
    payload["name"] = "A clarified item name"
    assert post_form(client, path + "/edit", payload).status_code == 303


@pytest.mark.parametrize("change,expected_status", [("permission", 403), ("partner", 404)])
def test_master_rechecks_access_committed_while_waiting_for_guard(
    client, records, master_graph, monkeypatch, change, expected_status
):
    import app.services.master as master_service

    login(client)
    company_id = records["companies"]["aurora"]
    path = base(records, "sites") + "/new"
    token = csrf(client.get(path))
    member_id = db.session.scalar(
        select(Membership.id)
        .join(User)
        .where(Membership.organization_id == company_id, User.email == "catalog-editor@aurora.test")
    )
    actual_lock = master_service.company_lock
    changed = False

    def revoke_then_lock(target_company):
        nonlocal changed
        if not changed:
            changed = True
            # A genuinely independent committed transaction changes authorization
            # after the request has loaded membership and before it obtains the guard.
            with Session(db.engine) as other:
                if change == "permission":
                    permission_id = other.scalar(
                        select(Permission.id).where(Permission.code == "catalog.manage")
                    )
                    role_id = other.scalar(
                        select(Role.id).where(
                            Role.organization_id == company_id, Role.code == "catalog-editor"
                        )
                    )
                    grant = other.scalar(
                        select(RolePermission).where(
                            RolePermission.role_id == role_id,
                            RolePermission.permission_id == permission_id,
                        )
                    )
                    other.delete(grant)
                else:
                    membership = other.get(Membership, member_id)
                    membership.partner_id = master_graph["partner"]
                other.commit()
        return actual_lock(target_company)

    monkeypatch.setattr(master_service, "company_lock", revoke_then_lock)
    response = client.post(
        path, data=dict(values("sites", records, master_graph), version=0, csrf_token=token)
    )
    assert response.status_code == expected_status
    assert not db.session.scalar(
        select(Site.id).where(Site.organization_id == company_id, Site.code == "SECOND")
    )
