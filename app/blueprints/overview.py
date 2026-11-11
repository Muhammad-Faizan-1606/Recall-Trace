"""Company overview: what needs attention, in one screen."""

from flask import Blueprint, render_template
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app.extensions import db
from app.models import Membership, Organization, User
from app.models.master import Lot
from app.models.operations import StockBalance
from app.models.quality import Nonconformance, QualityHold
from app.models.recall import CaseTask, RecallCase
from app.models.security import AuditEvent
from app.policies import membership_for, require

bp = Blueprint("overview", __name__)

CLOSED_CASE_STATES = ("closed", "cancelled", "rejected")
# Plain-language wording for audit actions, so activity reads like a sentence.
ACTIONS = {
    "quality.observe": "recorded an inspection result",
    "quality.save_check": "edited an inspection checklist",
    "quality.save_template": "saved an inspection checklist",
    "quality.publish_template": "published an inspection checklist",
    "quality.create_inspection": "started an inspection",
    "quality.complete_inspection": "completed an inspection",
    "quality.save_nonconformance": "reported a quality issue",
    "quality.resolve_nonconformance": "resolved a quality issue",
    "quality.place_hold": "placed a lot on hold",
    "quality.review_hold": "reviewed a lot hold",
    "quality.attach_document": "attached quality evidence",
    "recall.comment": "commented on an investigation",
    "recall.source": "added a suspect lot",
    "recall.remove_source": "removed a suspect lot",
    "recall.task": "assigned an investigation task",
    "recall.complete_task": "completed an investigation task",
    "recall.save_case": "saved an investigation",
    "recall.submit": "submitted an investigation for approval",
    "recall.approve": "approved an investigation",
    "recall.reject": "sent an investigation back for correction",
    "recall.reopen": "reopened an investigation",
    "recall.close": "closed an investigation",
    "recall.recovery": "recorded a verified recovery",
    "trace.compute": "computed a trace",
    "access.invitation.created": "invited a member",
    "access.invitation.revoked": "revoked an invitation",
    "access.membership.updated": "changed a member's access",
    "evidence.upload": "uploaded evidence",
    "evidence.scan": "scanned evidence",
    "evidence.delete_unused": "deleted unused evidence",
    "import.validate": "validated an item import",
    "import.commit": "imported catalog items",
    "import.cancel": "cancelled an item import",
    "notice.edit": "edited a recall notice",
    "notice.queue": "queued a recall notice",
    "notice.delete_draft": "deleted a draft notice",
}
RECORDS = {
    "item_categories": "an item category",
    "item_category_assignments": "an item classification",
    "partners": "a partner",
    "partner_contacts": "a partner contact",
    "partner_addresses": "a partner address",
    "partner_role_assignments": "a partner role",
    "supplier_items": "a supplier item",
    "sites": "a site",
    "warehouses": "a warehouse",
    "storage_locations": "a storage location",
    "lots": "a lot",
    "carriers": "a carrier",
}
DOCUMENTS = {
    "purchase_orders": "purchase order",
    "purchase_order_lines": "purchase order",
    "goods_receipts": "receipt",
    "goods_receipt_lines": "receipt",
    "production_runs": "production run",
    "production_inputs": "production run",
    "production_outputs": "production run",
    "sales_orders": "sales order",
    "sales_order_lines": "sales order",
    "shipments": "shipment",
    "shipment_lines": "shipment",
    "stock_transfers": "transfer",
    "stock_transfer_lines": "transfer",
}
MASTER_VERBS = {
    "created": "added",
    "updated": "updated",
    "deleted": "deleted",
    "archived": "archived",
}
DOCUMENT_VERBS = {
    "create_document": "created a {}",
    "edit_document": "edited a {}",
    "delete_document": "deleted a draft {}",
    "add_line": "added a line to a {}",
    "edit_line": "edited a line on a {}",
    "delete_line": "removed a line from a {}",
    "post_document": "posted a {}",
    "reverse": "reversed a {}",
}


def describe(event):
    if event.action in ACTIONS:
        return ACTIONS[event.action]
    area, _, verb = event.action.partition(".")
    if area == "master" and verb in MASTER_VERBS:
        record = RECORDS.get(event.entity_kind, "a record")
        return f"{MASTER_VERBS[verb]} {record}"
    if area == "operations" and verb in DOCUMENT_VERBS:
        return DOCUMENT_VERBS[verb].format(DOCUMENTS.get(event.entity_kind, "document"))
    return event.action.replace(".", " ").replace("_", " ")


@bp.get("/companies/<uuid:company_id>/overview")
@login_required
def overview(company_id):
    require(company_id, "catalog.read")
    member = membership_for(company_id)
    company = db.session.get(Organization, company_id)

    cases = db.session.scalars(
        select(RecallCase)
        .where(
            RecallCase.organization_id == company_id,
            RecallCase.status.not_in(CLOSED_CASE_STATES),
        )
        .order_by(RecallCase.updated_at.desc())
        .limit(5)
    ).all()
    open_cases = db.session.scalar(
        select(func.count())
        .select_from(RecallCase)
        .where(
            RecallCase.organization_id == company_id,
            RecallCase.status.not_in(CLOSED_CASE_STATES),
        )
    )
    holds = db.session.execute(
        select(QualityHold, Lot)
        .join(Lot, Lot.id == QualityHold.lot_id)
        .where(
            QualityHold.organization_id == company_id,
            Lot.organization_id == company_id,
            QualityHold.released_at.is_(None),
        )
        .order_by(QualityHold.placed_at.desc())
        .limit(5)
    ).all()
    active_holds = db.session.scalar(
        select(func.count())
        .select_from(QualityHold)
        .where(QualityHold.organization_id == company_id, QualityHold.released_at.is_(None))
    )
    open_issues = db.session.scalar(
        select(func.count())
        .select_from(Nonconformance)
        .where(Nonconformance.organization_id == company_id, Nonconformance.status == "open")
    )
    lots_in_stock = db.session.scalar(
        select(func.count(func.distinct(StockBalance.lot_id))).where(
            StockBalance.organization_id == company_id, StockBalance.quantity > 0
        )
    )
    my_tasks = db.session.execute(
        select(CaseTask, RecallCase)
        .join(RecallCase, RecallCase.id == CaseTask.case_id)
        .where(
            CaseTask.organization_id == company_id,
            RecallCase.organization_id == company_id,
            CaseTask.assignee_id == member.id,
            CaseTask.status == "open",
        )
        .order_by(CaseTask.created_at)
        .limit(5)
    ).all()
    activity = db.session.execute(
        select(AuditEvent, User.display_name)
        .outerjoin(
            Membership,
            (Membership.id == AuditEvent.actor_id) & (Membership.organization_id == company_id),
        )
        .outerjoin(User, User.id == Membership.user_id)
        .where(AuditEvent.organization_id == company_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(8)
    ).all()
    return render_template(
        "overview.html",
        company=company,
        company_id=company_id,
        cases=cases,
        open_cases=open_cases,
        holds=holds,
        active_holds=active_holds,
        open_issues=open_issues,
        lots_in_stock=lots_in_stock,
        my_tasks=my_tasks,
        activity=[(event, name or "System", describe(event)) for event, name in activity],
        first_name=(current_user.display_name or "").split(" ")[0],
    )
