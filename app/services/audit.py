"""Audit metadata is deliberately restricted; the caller owns the transaction."""

import uuid

from flask import g

from app.extensions import db
from app.models.security import AuditEvent
from app.policies import membership_for

# Domain callers may add identifiers/counts/states, never arbitrary submitted text.
SAFE_FIELDS = {
    "status",
    "from_status",
    "to_status",
    "count",
    "quantity",
    "reason_code",
    "version",
    "trace_revision",
    "source_id",
    "target_id",
    "operation",
    "result",
    "delivery_id",
    "document_id",
    "case_id",
    "lot_id",
    "transaction_id",
    "method",
    "step",
}


def record(company_id, action, entity_kind, entity_id=None, safe_details=None):
    member = membership_for(company_id)
    if not action or len(action) > 100 or not entity_kind or len(entity_kind) > 60:
        raise ValueError("Audit action and entity kind must be bounded.")
    details = {}
    for key, value in (safe_details or {}).items():
        if key not in SAFE_FIELDS:
            raise ValueError("Unsupported audit metadata field.")
        if value is not None and not isinstance(value, (str, int, bool)):
            value = str(value)
        if isinstance(value, str) and len(value) > 160:
            raise ValueError("Audit metadata is too long.")
        details[key] = value
    correlation_id = getattr(g, "correlation_id", None) or uuid.uuid4()
    row = AuditEvent(
        organization_id=company_id,
        action=action,
        entity_kind=entity_kind,
        entity_id=entity_id,
        actor_id=member.id,
        safe_details=details,
        correlation_id=correlation_id,
    )
    db.session.add(row)
    db.session.flush()
    return row
