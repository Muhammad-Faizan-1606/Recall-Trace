"""Bounded, reproducible conservative traces of posted production genealogy."""

import time
from collections import defaultdict, deque
from decimal import Decimal

from sqlalchemy import func, select

from app.extensions import db
from app.models import ItemVariant, now
from app.models.master import Lot
from app.models.operations import (
    ProductionInput,
    ProductionOutput,
    ProductionRun,
    Shipment,
    ShipmentLine,
    StockBalance,
)
from app.models.recall import (
    CaseAffectedShipment,
    CaseSource,
    RecallCase,
    RecoveryRecord,
    TraceResult,
    TraceRun,
)
from app.services.business import DomainError, actor, company_lock, scoped
from app.services.quality import mutation


@mutation
def compute(company_id, case_id, direction="downstream", max_nodes=10000, max_depth=128):
    member = actor(company_id, "trace.run")
    company = company_lock(company_id)
    case = scoped(RecallCase, company_id, case_id, True)
    if case.status in {"approved", "active", "pending_closure"}:
        raise DomainError("Reopen the approved case before computing a revised operational scope.")
    if case.status in {"closed", "cancelled", "rejected"}:
        raise DomainError("Reopen the case before computing another trace.")
    if direction not in {"downstream", "upstream"}:
        raise DomainError("Choose upstream or downstream tracing.")
    if (
        not isinstance(max_nodes, int)
        or not 1 <= max_nodes <= 10000
        or not isinstance(max_depth, int)
        or not 0 <= max_depth <= 128
    ):
        raise DomainError("Trace limits exceed the supported bounds.")
    roots = sorted(
        db.session.scalars(
            select(CaseSource.lot_id).where(
                CaseSource.organization_id == company_id, CaseSource.case_id == case.id
            )
        ),
        key=str,
    )
    if not roots:
        raise DomainError("Add at least one source lot before computing a trace.")
    # Bound relation materialization as well as traversal; a partial relation set is never complete.
    query = (
        select(ProductionInput.lot_id, ProductionOutput.lot_id, ProductionRun.id)
        .join(ProductionRun, ProductionRun.id == ProductionInput.production_run_id)
        .join(ProductionOutput, ProductionOutput.production_run_id == ProductionRun.id)
        .where(
            ProductionRun.organization_id == company_id,
            ProductionRun.status == "posted",
            ProductionInput.organization_id == company_id,
            ProductionOutput.organization_id == company_id,
        )
        .order_by(ProductionRun.id, ProductionInput.lot_id, ProductionOutput.lot_id)
        .limit(100001)
    )
    edges = db.session.execute(query).all()
    complete, reached_limit = len(edges) <= 100000, None
    if not complete:
        reached_limit = "edge_limit"
    adjacency = defaultdict(list)
    for origin, destination, event in edges[:100000]:
        if direction == "upstream":
            origin, destination = destination, origin
        adjacency[origin].append((destination, event))
    paths, depth = {}, {}
    queue = deque()
    for root in roots:
        if len(paths) >= max_nodes:
            complete, reached_limit = False, "node_limit"
            break
        paths[root], depth[root] = [{"lot": str(root)}], 0
        queue.append(root)
    deadline = time.monotonic() + 5
    while queue:
        if time.monotonic() > deadline:
            complete, reached_limit = False, "time_limit"
            break
        origin = queue.popleft()
        for destination, event in adjacency[origin]:
            # A cycle is a data-integrity issue even though visited IDs bound the query.
            path_ids = {entry["lot"] for entry in paths[origin]}
            if str(destination) in path_ids:
                complete, reached_limit = False, "genealogy_cycle"
                continue
            if destination in paths:
                continue
            if depth[origin] >= max_depth:
                complete, reached_limit = False, "depth_limit"
                continue
            if len(paths) >= max_nodes:
                complete, reached_limit = False, "node_limit"
                continue
            paths[destination] = paths[origin] + [
                {"lot": str(destination), "production_run": str(event)}
            ]
            depth[destination] = depth[origin] + 1
            queue.append(destination)
    # Detect cycles in the complete reached subgraph, including cross-branch back edges.
    indegree = dict.fromkeys(paths, 0)
    for origin in paths:
        for destination, _event in adjacency[origin]:
            if destination in indegree:
                indegree[destination] += 1
    acyclic = deque(node for node, degree in indegree.items() if degree == 0)
    consumed = 0
    while acyclic:
        origin = acyclic.popleft()
        consumed += 1
        for destination, _event in adjacency[origin]:
            if destination in indegree:
                indegree[destination] -= 1
                if indegree[destination] == 0:
                    acyclic.append(destination)
    if consumed != len(paths):
        complete, reached_limit = False, "genealogy_cycle"
    run = TraceRun(
        organization_id=company_id,
        case_id=case.id,
        requested_by_id=member.id,
        direction=direction,
        status="complete" if complete else "incomplete",
        trace_revision=company.trace_revision,
        algorithm_version="core-conservative-1",
        limits={
            "max_nodes": max_nodes,
            "max_depth": max_depth,
            "max_edges": 100000,
            "time_seconds": 5,
            "reached_limit": reached_limit,
        },
        completed_at=now(),
        is_complete=complete,
    )
    db.session.add(run)
    db.session.flush()
    for lot_id in sorted(paths, key=str):
        db.session.add(
            TraceResult(
                organization_id=company_id,
                trace_run_id=run.id,
                lot_id=lot_id,
                depth=depth[lot_id],
                evidence_path=paths[lot_id],
                scope_basis="conservative",
            )
        )
    if direction == "downstream":
        lines = db.session.scalars(
            select(ShipmentLine)
            .join(Shipment, Shipment.id == ShipmentLine.shipment_id)
            .where(
                Shipment.organization_id == company_id,
                Shipment.status == "posted",
                ShipmentLine.organization_id == company_id,
                ShipmentLine.lot_id.in_(paths),
            )
            .order_by(ShipmentLine.id)
        ).all()
        for line in lines:
            # Recomputed snapshots retain immutable physical recovery history exactly once per line.
            resolved = db.session.scalar(
                select(func.coalesce(func.sum(RecoveryRecord.quantity), 0)).where(
                    RecoveryRecord.case_id == case.id, RecoveryRecord.shipment_line_id == line.id
                )
            )
            recovered = db.session.scalar(
                select(func.coalesce(func.sum(RecoveryRecord.quantity), 0)).where(
                    RecoveryRecord.case_id == case.id,
                    RecoveryRecord.shipment_line_id == line.id,
                    RecoveryRecord.disposition == "returned",
                )
            )
            db.session.add(
                CaseAffectedShipment(
                    organization_id=company_id,
                    case_id=case.id,
                    trace_run_id=run.id,
                    shipment_line_id=line.id,
                    quantity_dispatched=line.quantity,
                    quantity_recovered=recovered,
                    quantity_resolved=resolved,
                )
            )
    return run


def results(company_id, trace_id):
    actor(company_id, "catalog.read")
    run = scoped(TraceRun, company_id, trace_id)
    rows = db.session.execute(
        select(TraceResult, Lot, ItemVariant)
        .join(Lot, Lot.id == TraceResult.lot_id)
        .join(ItemVariant, ItemVariant.id == Lot.variant_id)
        .where(TraceResult.organization_id == company_id, TraceResult.trace_run_id == run.id)
        .order_by(TraceResult.depth, Lot.lot_code)
    ).all()
    return run, rows


def summary(company_id, trace_id):
    _run, rows = results(company_id, trace_id)
    buckets = {}
    lot_ids = [lot.id for _result, lot, _variant in rows]
    for _result, _lot, variant in rows:
        buckets.setdefault(
            str(variant.id),
            {
                "sku": variant.sku,
                "unit_id": variant.base_unit_id,
                "produced": Decimal(0),
                "on_hand": Decimal(0),
                "dispatched": Decimal(0),
            },
        )
    if not lot_ids:
        return []
    queries = {
        "on_hand": select(Lot.variant_id, func.sum(StockBalance.quantity))
        .join(StockBalance, StockBalance.lot_id == Lot.id)
        .where(
            Lot.organization_id == company_id,
            StockBalance.organization_id == company_id,
            Lot.id.in_(lot_ids),
        )
        .group_by(Lot.variant_id),
        "produced": select(Lot.variant_id, func.sum(ProductionOutput.quantity))
        .join(ProductionOutput, ProductionOutput.lot_id == Lot.id)
        .join(ProductionRun, ProductionRun.id == ProductionOutput.production_run_id)
        .where(
            Lot.organization_id == company_id,
            ProductionOutput.organization_id == company_id,
            ProductionRun.status == "posted",
            Lot.id.in_(lot_ids),
        )
        .group_by(Lot.variant_id),
        "dispatched": select(Lot.variant_id, func.sum(ShipmentLine.quantity))
        .join(ShipmentLine, ShipmentLine.lot_id == Lot.id)
        .join(Shipment, Shipment.id == ShipmentLine.shipment_id)
        .where(
            Lot.organization_id == company_id,
            ShipmentLine.organization_id == company_id,
            Shipment.status == "posted",
            Lot.id.in_(lot_ids),
        )
        .group_by(Lot.variant_id),
    }
    for field, query in queries.items():
        for variant_id, amount in db.session.execute(query):
            buckets[str(variant_id)][field] = amount
    return list(buckets.values())
