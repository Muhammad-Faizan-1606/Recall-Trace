"""Shared transaction guards for company-scoped operational workflows."""

import uuid
from decimal import Decimal, InvalidOperation

from flask import abort
from flask_login import current_user
from sqlalchemy import select

from app.extensions import db
from app.models import Organization
from app.policies import membership_for, require


class DomainError(ValueError):
    """A safe, actionable business validation failure."""


def actor(company_id, action):
    # Resolve login before acquiring a lock: session validation commits its heartbeat.
    if not current_user.is_authenticated:
        abort(401)
    company_lock(company_id)
    require(company_id, action)
    return membership_for(company_id)


def company_lock(company_id):
    """Serialize stock/hold/genealogy decisions before taking individual row locks.

    This deliberately favors a simple, provable locking protocol over throughput.
    Call before reading operational state, and hold until the transaction commits.
    """
    row = db.session.scalar(
        select(Organization)
        .where(Organization.id == company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.status != "active" or row.archived_at:
        abort(404)
    return row


def scoped(model, company_id, record_id, lock=False):
    try:
        record_id = uuid.UUID(str(record_id))
    except (ValueError, TypeError, AttributeError):
        abort(404)
    query = select(model).where(model.organization_id == company_id, model.id == record_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.session.scalar(query)
    if row is None:
        abort(404)
    return row


def quantity(value, places=6, positive=True):
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise DomainError("Enter a valid decimal quantity.") from exc
    if not result.is_finite() or abs(result) >= Decimal("100000000000000"):
        raise DomainError("Quantity must be finite and fit the supported range.")
    if positive and result <= 0:
        raise DomainError("Quantity must be greater than zero.")
    if not 0 <= places <= 6 or result != result.quantize(Decimal(1).scaleb(-places)):
        raise DomainError("Quantity exceeds the SKU base unit precision.")
    return result
