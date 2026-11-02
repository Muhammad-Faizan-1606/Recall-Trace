"""Versioned quality evidence and independently reviewed lot holds."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models import Owned, now


def tenant_fk(field, table):
    return ForeignKeyConstraint(
        ["organization_id", field], [f"{table}.organization_id", f"{table}.id"]
    )


def owned(*constraints):
    return (UniqueConstraint("organization_id", "id"), *constraints)


class InspectionTemplate(Owned, db.Model):
    __tablename__ = "inspection_templates"
    code: Mapped[str] = mapped_column(db.String(60))
    revision: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(db.String(20), default="draft")
    __table_args__ = owned(
        UniqueConstraint("organization_id", "code", "revision"),
        CheckConstraint("revision > 0", name="positive_revision"),
        CheckConstraint("status IN ('draft','published','retired')", name="template_status"),
    )


class InspectionCheck(Owned, db.Model):
    __tablename__ = "inspection_checks"
    sequence: Mapped[int]
    label: Mapped[str] = mapped_column(db.String(160))
    value_type: Mapped[str] = mapped_column(db.String(20))
    rule_definition: Mapped[dict] = mapped_column(JSONB, default=dict)
    template_id: Mapped[uuid.UUID]
    unit_id: Mapped[uuid.UUID | None]
    __table_args__ = owned(
        tenant_fk("template_id", "inspection_templates"),
        tenant_fk("unit_id", "units_of_measure"),
        UniqueConstraint("template_id", "sequence"),
        CheckConstraint("sequence > 0", name="positive_sequence"),
        CheckConstraint("value_type IN ('number','text','boolean')", name="check_type"),
    )


class Inspection(Owned, db.Model):
    __tablename__ = "inspections"
    reference: Mapped[str] = mapped_column(db.String(80))
    status: Mapped[str] = mapped_column(db.String(20), default="draft")
    inspected_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    lot_id: Mapped[uuid.UUID]
    template_id: Mapped[uuid.UUID]
    inspector_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("lot_id", "lots"),
        tenant_fk("template_id", "inspection_templates"),
        tenant_fk("inspector_id", "memberships"),
        UniqueConstraint("organization_id", "reference"),
        CheckConstraint("status IN ('draft','completed')", name="inspection_status"),
    )


class InspectionResult(Owned, db.Model):
    __tablename__ = "inspection_results"
    numeric_value: Mapped[Decimal | None] = mapped_column(db.Numeric(20, 6))
    text_value: Mapped[str | None] = mapped_column(db.Text)
    outcome: Mapped[str] = mapped_column(db.String(20))
    comment: Mapped[str | None] = mapped_column(db.Text)
    inspection_id: Mapped[uuid.UUID]
    check_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("inspection_id", "inspections"),
        tenant_fk("check_id", "inspection_checks"),
        UniqueConstraint("inspection_id", "check_id"),
        CheckConstraint("outcome IN ('pass','fail')", name="result_outcome"),
    )


class Nonconformance(Owned, db.Model):
    __tablename__ = "nonconformances"
    reference: Mapped[str] = mapped_column(db.String(80))
    description: Mapped[str] = mapped_column(db.Text)
    severity: Mapped[str] = mapped_column(db.String(20))
    status: Mapped[str] = mapped_column(db.String(20), default="open")
    lot_id: Mapped[uuid.UUID]
    inspection_id: Mapped[uuid.UUID | None]
    test_result_id: Mapped[uuid.UUID | None]
    owner_id: Mapped[uuid.UUID]
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = owned(
        tenant_fk("lot_id", "lots"),
        tenant_fk("inspection_id", "inspections"),
        tenant_fk("owner_id", "memberships"),
        UniqueConstraint("organization_id", "reference"),
        CheckConstraint(
            "severity IN ('low','medium','high','critical')", name="nonconformance_severity"
        ),
        CheckConstraint("status IN ('open','resolved')", name="nonconformance_status"),
    )


class QualityHold(Owned, db.Model):
    __tablename__ = "quality_holds"
    reason: Mapped[str] = mapped_column(db.Text)
    placed_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    released_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    lot_id: Mapped[uuid.UUID] = mapped_column(index=True)
    placed_by_id: Mapped[uuid.UUID]
    case_id: Mapped[uuid.UUID | None]
    nonconformance_id: Mapped[uuid.UUID | None]
    __table_args__ = owned(
        tenant_fk("lot_id", "lots"),
        tenant_fk("placed_by_id", "memberships"),
        tenant_fk("case_id", "recall_cases"),
        tenant_fk("nonconformance_id", "nonconformances"),
        CheckConstraint("released_at IS NULL OR released_at >= placed_at", name="release_time"),
    )


class HoldReview(Owned, db.Model):
    __tablename__ = "hold_reviews"
    decision: Mapped[str] = mapped_column(db.String(20))
    reason: Mapped[str] = mapped_column(db.Text)
    reviewed_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    hold_id: Mapped[uuid.UUID]
    reviewer_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("hold_id", "quality_holds"),
        tenant_fk("reviewer_id", "memberships"),
        CheckConstraint("decision IN ('release','retain')", name="review_decision"),
    )


class QualityDocument(Owned, db.Model):
    __tablename__ = "quality_documents"
    inspection_id: Mapped[uuid.UUID | None]
    nonconformance_id: Mapped[uuid.UUID | None]
    document_id: Mapped[uuid.UUID]
    __table_args__ = owned(
        tenant_fk("inspection_id", "inspections"),
        tenant_fk("nonconformance_id", "nonconformances"),
        tenant_fk("document_id", "documents"),
        UniqueConstraint("inspection_id", "document_id"),
        UniqueConstraint("nonconformance_id", "document_id"),
        CheckConstraint(
            "(inspection_id IS NULL) <> (nonconformance_id IS NULL)", name="one_parent"
        ),
    )
