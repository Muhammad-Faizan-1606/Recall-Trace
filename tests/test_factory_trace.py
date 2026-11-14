"""Factory Suite step 8b: the yarn-to-carton chain posted through Core production records.

Worked example: yarn lot Y1 (300 kg received) → two 40 kg rolls → dye batch DB-1 (passed)
→ fabric FAB-DB-1, 80 kg. The style uses 0.3 kg of fabric per garment:

    lay L-1  100 pieces  30 kg   posted
    lay L-2  150 pieces  45 kg   posted (5 kg left)
    lay L-3   50 pieces  15 kg   refused: only 5 kg of FAB-DB-1 left

Sewing lay L-1 and packing posts garment lot PO-9-G1 (100 pieces). Shipping it lets the
existing recall trace, started from yarn lot Y1, find 100 garments dispatched.
"""

from decimal import Decimal

import pytest
from conftest import csrf, login
from sqlalchemy import select
from test_balancing import line  # noqa: F401
from test_factory import grant
from test_shopfloor import TODAY, floor, mill  # noqa: F401

from app.extensions import db
from app.models.factory import CutBundle, DyeBatch, FabricSpec, Style
from app.models.master import Lot, Partner, PartnerRoleAssignment
from app.models.operations import ProductionRun
from app.services import factory_trace, recall, shopfloor, trace
from app.services import operations as op
from app.services.business import DomainError

D = Decimal
CORE = (
    "production.post",
    "inventory.receive",
    "inventory.dispatch",
    "trace.run",
    "case.prepare",
)


@pytest.fixture
def chain_ready(mill):  # noqa: F811
    company_id = mill.company_id
    grant(company_id, codes=CORE)
    db.session.add(
        FabricSpec(
            organization_id=company_id,
            style_id=mill.style.id,
            component="Body",
            fabric_type="single_jersey",
            composition="Cotton",
            gsm=D(160),
            width_m=D("1.8"),
            consumption_kg=D("0.3"),
            relaxation_hours=0,
        )
    )
    spinner = Partner(organization_id=company_id, code="SPIN", name="Fictional spinner")
    db.session.add(spinner)
    db.session.flush()
    db.session.add(
        PartnerRoleAssignment(
            organization_id=company_id, partner_id=spinner.id, role_code="supplier"
        )
    )
    master = factory_trace.ensure_master(company_id)
    yarn = factory_trace.variant(company_id, "YARN-TEST", "Test yarn", "component", master.kg)
    lot = Lot(organization_id=company_id, lot_code="Y1", variant_id=yarn.id, supplier_id=spinner.id)
    db.session.add(lot)
    db.session.commit()
    purchase = op.create_document(
        company_id,
        "purchase-orders",
        {"reference": "PO-Y", "supplier_id": spinner.id, "delivery_site_id": master.site.id},
    )
    order_line = op.add_line(
        company_id, "purchase-orders", purchase.id, {"variant_id": yarn.id, "quantity": "300"}
    )
    op.post_document(company_id, "purchase-orders", purchase.id, "po-y")
    receipt = op.create_document(
        company_id,
        "receipts",
        {"reference": "GR-Y", "supplier_id": spinner.id, "warehouse_id": master.warehouse.id},
    )
    op.add_line(
        company_id,
        "receipts",
        receipt.id,
        {
            "purchase_order_line_id": order_line.id,
            "lot_id": lot.id,
            "location_id": master.location.id,
            "quantity": "300",
        },
    )
    op.post_document(company_id, "receipts", receipt.id, "gr-y")
    rolls = [
        shopfloor.record_roll(
            company_id,
            {
                "roll_number": f"R-{n}",
                "machine_id": str(mill.knitter.id),
                "kg": "40",
                "knitted_on": TODAY.isoformat(),
                "yarn_lot_id": str(lot.id),
            },
            today=TODAY,
        )
        for n in (1, 2)
    ]
    batch, _, _ = shopfloor.load_batch(
        company_id,
        {
            "batch_number": "DB-1",
            "machine_id": str(mill.vessel.id),
            "production_order_id": str(mill.order.id),
            "colour": "Black",
            "recipe_reference": "R1",
            "roll_ids": [str(r.id) for r in rolls],
        },
    )
    batch = shopfloor.batch_step(company_id, batch.id, "start", batch.version)
    mill.batch = shopfloor.batch_step(company_id, batch.id, "passed", batch.version)
    mill.yarn_lot, mill.master = lot, master
    return mill


def cut(chain_ready, lay, pieces):
    return shopfloor.cut_bundles(
        chain_ready.company_id,
        {
            "production_order_id": str(chain_ready.order.id),
            "dye_batch_id": str(chain_ready.batch.id),
            "lay_number": lay,
            "bundle_size": 50,
            "sizes": f"M:{pieces}",
        },
    )


def test_roll_yarn_lot_must_be_a_received_yarn(chain_ready):
    with pytest.raises(DomainError, match="received yarn lot"):
        shopfloor.record_roll(
            chain_ready.company_id,
            {
                "roll_number": "R-X",
                "machine_id": str(chain_ready.knitter.id),
                "kg": "1",
                "knitted_on": TODAY.isoformat(),
                "yarn_lot_id": str(chain_ready.batch.id),
            },
            today=TODAY,
        )


def test_full_chain_reaches_the_shipment_through_the_existing_trace(chain_ready):
    company_id = chain_ready.company_id
    fabric = factory_trace.post_batch(company_id, chain_ready.batch.id)
    assert fabric.lot_code == "FAB-DB-1"
    assert factory_trace.on_hand(company_id, fabric.id, chain_ready.master.location.id) == 80
    assert factory_trace.on_hand(
        company_id, chain_ready.yarn_lot.id, chain_ready.master.location.id
    ) == D(220)
    with pytest.raises(DomainError, match="already posted"):
        factory_trace.post_batch(company_id, chain_ready.batch.id)

    l1, _l2, l3 = (
        cut(chain_ready, "L-1", 100),
        cut(chain_ready, "L-2", 150),
        cut(chain_ready, "L-3", 50),
    )
    with pytest.raises(DomainError, match="needs 15.0 kg of fabric; batch DB-1 has 5.0 kg"):
        factory_trace.post_lays(company_id, chain_ready.order.id)
    # Lays before the shortfall were posted; the short lay is left for more fabric.
    posted = {b.lay_number: b.cut_lot_id for b in db.session.scalars(select(CutBundle))}
    assert posted["L-1"] and posted["L-2"] and posted["L-3"] is None
    assert db.session.scalar(select(Lot.lot_code).where(Lot.id == posted["L-1"])) == "CUT-PO-9-L-1"

    for bundle in l1:
        bundle = shopfloor.bundle_step(
            company_id, bundle.id, "issue", bundle.version, chain_ready.center.id
        )
        shopfloor.bundle_step(company_id, bundle.id, "sewn", bundle.version)
    sewn_unposted = shopfloor.bundle_step(
        company_id, l3[0].id, "issue", l3[0].version, chain_ready.center.id
    )
    shopfloor.bundle_step(company_id, sewn_unposted.id, "sewn", sewn_unposted.version)
    with pytest.raises(DomainError, match="Post the cut lays"):
        factory_trace.post_packing(company_id, chain_ready.order.id)
    # Without the unposted lay's bundle, packing goes through.
    db.session.delete(db.session.get(CutBundle, sewn_unposted.id))
    db.session.commit()
    garments = factory_trace.post_packing(company_id, chain_ready.order.id)
    assert garments.lot_code == "PO-9-G1"
    assert factory_trace.on_hand(company_id, garments.id, chain_ready.master.location.id) == 100
    assert db.session.get(Style, chain_ready.style.id).item_id is not None
    with pytest.raises(DomainError, match="No sewn bundles"):
        factory_trace.post_packing(company_id, chain_ready.order.id)
    runs = db.session.scalars(
        select(ProductionRun.reference).order_by(ProductionRun.reference)
    ).all()
    assert runs == ["CT-PO-9-L-1", "CT-PO-9-L-2", "KD-DB-1", "PK-PO-9-G1"]

    style = db.session.get(Style, chain_ready.style.id)
    buyer = Partner(organization_id=company_id, code="BUY", name="Fictional buyer")
    db.session.add(buyer)
    db.session.flush()
    db.session.add(
        PartnerRoleAssignment(organization_id=company_id, partner_id=buyer.id, role_code="customer")
    )
    db.session.commit()
    sale = op.create_document(
        company_id,
        "sales-orders",
        {"reference": "SO-9", "customer_id": buyer.id, "destination": "Fictional store"},
    )
    sale_line = op.add_line(
        company_id, "sales-orders", sale.id, {"variant_id": garments.variant_id, "quantity": "100"}
    )
    op.post_document(company_id, "sales-orders", sale.id, "so-9")
    shipment = op.create_document(
        company_id,
        "shipments",
        {
            "reference": "SH-9",
            "sales_order_id": sale.id,
            "warehouse_id": chain_ready.master.warehouse.id,
        },
    )
    op.add_line(
        company_id,
        "shipments",
        shipment.id,
        {
            "sales_order_line_id": sale_line.id,
            "lot_id": garments.id,
            "source_location_id": chain_ready.master.location.id,
            "quantity": "100",
        },
    )
    op.post_document(company_id, "shipments", shipment.id, "sh-9")
    assert style.item_id

    case = recall.save_case(company_id, "RC-Y1", "Yarn lot Y1 flagged", "Spinner warning", "high")
    recall.source(company_id, case.id, chain_ready.yarn_lot.id, "Spinner warning")
    run = trace.compute(company_id, case.id, "downstream")
    summary = {row["sku"]: row for row in trace.summary(company_id, run.id)}
    garment_sku = db.session.scalar(
        select(factory_trace.ItemVariant.sku).where(
            factory_trace.ItemVariant.id == garments.variant_id
        )
    )
    assert summary[garment_sku]["dispatched"] == 100
    assert summary["FAB-TEE"]["produced"] == 80

    chain = factory_trace.chain(company_id, chain_ready.order.id)
    assert [lot.lot_code for lot in chain.yarn.values()] == ["Y1"]
    assert [(lay, pieces, bool(lot)) for lay, pieces, lot, _ in chain.lays] == [
        ("L-1", 100, True),
        ("L-2", 150, True),
    ]  # L-3's only bundle was removed above
    assert [(lot.lot_code, pieces) for lot, pieces in chain.garments] == [("PO-9-G1", 100)]
    assert [s.reference for s, _ in chain.shipments] == ["SH-9"]


def test_trace_screens_and_permissions(chain_ready, client):
    company_id = chain_ready.company_id
    login(client)
    base = f"/companies/{company_id}/factory"
    page = client.get(f"{base}/dye-batches/{chain_ready.batch.id}")
    assert "Post fabric to traceability" in page.text
    response = client.post(
        f"{base}/dye-batches/{chain_ready.batch.id}/trace",
        data={"csrf_token": csrf(page), "version": "0"},
    )
    assert response.status_code == 303
    assert db.session.get(DyeBatch, chain_ready.batch.id).fabric_lot_id is not None
    cut(chain_ready, "L-1", 100)
    trace_page = client.get(f"{base}/orders/{chain_ready.order.id}/trace")
    assert trace_page.status_code == 200 and "Post cut lays" in trace_page.text
    response = client.post(
        f"{base}/orders/{chain_ready.order.id}/trace/lays",
        data={"csrf_token": csrf(trace_page), "version": "0"},
    )
    assert response.status_code == 303
    assert "CUT-PO-9-L-1" in client.get(f"{base}/orders/{chain_ready.order.id}/trace").text

    grant(company_id, codes=("factory.read",), role_code="auditor")
    client.post("/logout", data={"csrf_token": csrf(page)})
    login(client, "auditor@aurora.test")
    page = client.get(f"{base}/orders/{chain_ready.order.id}/trace")
    assert page.status_code == 200 and "Post packed garments" not in page.text
    response = client.post(
        f"{base}/orders/{chain_ready.order.id}/trace/packing",
        data={"csrf_token": csrf(page), "version": "0"},
    )
    assert response.status_code == 403
